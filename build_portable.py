"""
流光 免安装版打包脚本

用法: python build_portable.py
输出: dist/流光-Portable/  → 直接压缩成 zip 即可分发

原理:
1. 下载 Python 3.11 embeddable 包 (~10MB)
2. 注入 pip，安装 requirements.txt 中的依赖
3. 复制项目源码 + themes/ + bin/ffmpeg.exe
4. 生成启动脚本 流光.bat
"""

import os
import shutil
import subprocess
import zipfile
import urllib.request
from pathlib import Path

# ── 配置 ──
PYTHON_VERSION = "3.11.9"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

PROJECT_DIR = Path(__file__).parent
BUILD_DIR = PROJECT_DIR / "dist" / "流光-Portable"
PYTHON_DIR = BUILD_DIR / "python"
SITE_PACKAGES = PYTHON_DIR / "Lib" / "site-packages"

# 不打包的文件/目录
# 注意：此处只能放真正不需要的文件。任何被代码 import 的模块
# （如 engines/gpu_scheduler.py 被 workers.py 引用）绝不能放进此集合，
# 否则免安装版启动即 ImportError 闪退。
EXCLUDE = {
    "venv", ".git", "__pycache__", ".pytest_cache",
    "dist", "build", "logs", ".claude",
    "流光.exe", "流光.spec", "build_portable.py",
    ".github", "screenshots",
}

PIP_ARGS = ["--disable-pip-version-check", "--no-warn-script-location", "--quiet"]


def log(msg: str):
    print(f"[流光打包] {msg}")


def download(url: str, dest: Path):
    """下载文件，带进度显示。"""
    log(f"下载 {url}")
    urllib.request.urlretrieve(url, dest)
    log(f"  → {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")


def setup_python_embed():
    """下载并配置 Python embeddable 包。"""
    embed_zip = BUILD_DIR / "_python_embed.zip"
    download(PYTHON_EMBED_URL, embed_zip)

    log("解压 Python embeddable...")
    with zipfile.ZipFile(embed_zip) as zf:
        zf.extractall(PYTHON_DIR)
    embed_zip.unlink()

    # 启用 site-packages：编辑 python311._pth，取消 import site 注释
    pth_file = PYTHON_DIR / f"python311._pth"
    content = pth_file.read_text(encoding="utf-8")
    content = content.replace("#import site", "import site")
    pth_file.write_text(content, encoding="utf-8")
    log(f"  已启用 site-packages: {pth_file.name}")


def _run(args: list[str], *, cwd: Path | None = None) -> None:
    """运行命令并在失败时直接抛错。"""
    subprocess.run(args, check=True, cwd=str(cwd) if cwd else None)


def install_pip():
    """在 embeddable Python 中安装 pip。"""
    get_pip = BUILD_DIR / "_get_pip.py"
    download(GET_PIP_URL, get_pip)

    log("安装 pip...")
    python_exe = PYTHON_DIR / "python.exe"
    _run([str(python_exe), str(get_pip), *PIP_ARGS])
    get_pip.unlink()
    log("  pip 安装完成")


def install_dependencies():
    """安装 requirements.txt 中的依赖。"""
    req_file = PROJECT_DIR / "requirements.txt"
    python_exe = PYTHON_DIR / "python.exe"

    log("安装项目依赖...")
    _run([
        str(python_exe), "-m", "pip", "install",
        "-r", str(req_file),
        "--target", str(SITE_PACKAGES),
        "--upgrade",
        *PIP_ARGS,
    ])
    log("  依赖安装完成")


def copy_project_files():
    """复制项目源码到打包目录。"""
    log("复制项目文件...")

    # 复制 Python 源码
    for py_file in PROJECT_DIR.glob("*.py"):
        if py_file.name in EXCLUDE:
            continue
        shutil.copy2(py_file, BUILD_DIR / py_file.name)

    # 复制 engines/
    engines_dst = BUILD_DIR / "engines"
    engines_dst.mkdir(exist_ok=True)
    for py_file in (PROJECT_DIR / "engines").glob("*.py"):
        shutil.copy2(py_file, engines_dst / py_file.name)

    # 复制 themes/
    themes_dst = BUILD_DIR / "themes"
    themes_dst.mkdir(exist_ok=True)
    for f in (PROJECT_DIR / "themes").iterdir():
        if f.suffix in (".qss", ".py") and f.name != "__pycache__":
            shutil.copy2(f, themes_dst / f.name)

    # 复制 icon
    icon = PROJECT_DIR / "icon.ico"
    if icon.exists():
        shutil.copy2(icon, BUILD_DIR / "icon.ico")

    # 复制 bin/ffmpeg.exe
    ffmpeg_src = PROJECT_DIR / "bin" / "ffmpeg.exe"
    if ffmpeg_src.exists():
        ffmpeg_dst = BUILD_DIR / "bin"
        ffmpeg_dst.mkdir(exist_ok=True)
        shutil.copy2(ffmpeg_src, ffmpeg_dst / "ffmpeg.exe")
        log(f"  ffmpeg.exe ({ffmpeg_src.stat().st_size / 1024 / 1024:.0f} MB)")
    else:
        log("  ⚠ bin/ffmpeg.exe 不存在，跳过")


def create_launcher():
    """生成启动脚本。"""
    log("生成启动脚本...")

    bat_content = """@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 流光 - 格式流转，光影随行
python\\python.exe main.py %*
"""
    bat_path = BUILD_DIR / "流光.bat"
    bat_path.write_text(bat_content, encoding="utf-8")

    # 也生成一个 vbs 隐藏窗口启动器（双击不弹黑框）
    vbs_content = """Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "python\\python.exe main.py", 0, False
"""
    vbs_path = BUILD_DIR / "流光.vbs"
    vbs_path.write_text(vbs_content, encoding="utf-8")


def clean_build():
    """清理打包产物中的冗余文件。"""
    log("清理冗余文件...")
    removed = 0

    # 删除 pip/setuptools 安装元数据（运行时不需要）
    for d in SITE_PACKAGES.glob("*.dist-info"):
        shutil.rmtree(d, ignore_errors=True)
        removed += 1

    # 删除 __pycache__
    for d in BUILD_DIR.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
        removed += 1

    # 删除测试文件
    for d in SITE_PACKAGES.rglob("tests"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1

    # 删除 Scripts 目录（pip 自身，运行时不需要）
    scripts_dir = PYTHON_DIR / "Scripts"
    if scripts_dir.exists():
        shutil.rmtree(scripts_dir, ignore_errors=True)
        removed += 1

    # 删除 include 目录
    include_dir = PYTHON_DIR / "include"
    if include_dir.exists():
        shutil.rmtree(include_dir, ignore_errors=True)
        removed += 1

    # 删除 tcl/tk（PyQt6 不需要 Tcl/Tk）
    for pattern in ["tcl*", "tk*", "_tkinter*"]:
        for f in PYTHON_DIR.rglob(pattern):
            if f.is_file():
                f.unlink()
                removed += 1
            elif f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
                removed += 1

    log(f"  清理了 {removed} 个冗余项")


def make_zip():
    """将打包目录压缩为 zip。"""
    zip_path = PROJECT_DIR / "dist" / "流光-Portable.zip"
    log(f"压缩 {zip_path}...")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(BUILD_DIR):
            for f in files:
                file_path = Path(root) / f
                arcname = file_path.relative_to(BUILD_DIR.parent)
                zf.write(file_path, arcname)

    size_mb = zip_path.stat().st_size / 1024 / 1024
    log(f"  → {zip_path} ({size_mb:.0f} MB)")


def main():
    log("=" * 50)
    log("流光 免安装版打包")
    log("=" * 50)

    # 清理旧的打包目录
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    setup_python_embed()
    install_pip()
    install_dependencies()
    copy_project_files()
    create_launcher()
    clean_build()
    make_zip()

    log("=" * 50)
    log("✅ 打包完成!")
    log(f"   目录: {BUILD_DIR}")
    log(f"   ZIP:  dist/流光-Portable.zip")
    log("   用户解压后双击 流光.bat 或 流光.vbs 即可运行")
    log("=" * 50)


if __name__ == "__main__":
    main()
