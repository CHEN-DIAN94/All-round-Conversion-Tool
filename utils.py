"""
utils.py — 底层工具函数
提供资源寻址、幽灵黑框消除、文件直出等基础能力。
"""


__all__ = ['get_resource_path', 'get_ffmpeg_path', 'get_ffprobe_path', 'get_ffmpeg_version', 'run_subprocess', 'run_subprocess_popen', 'kill_process_tree', 'ProcessContext', 'safe_temp_path', 'finalize_file', 'get_file_size_str', 'ensure_output_dir', 'map_format_to_category', 'CREATE_NO_WINDOW', 'get_disk_free']

import sys
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


# Windows 下隐藏控制台窗口的标志
CREATE_NO_WINDOW = 0x08000000


def get_resource_path(relative_path: str) -> str:
    """
    获取资源的绝对路径。

    在 PyInstaller 打包环境下，资源位于 sys._MEIPASS 目录；
    在开发环境下，相对于项目根目录。
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的临时解压目录
        base_path = Path(sys._MEIPASS)
    else:
        # 开发环境：当前文件所在目录的上级（项目根目录）
        base_path = Path(__file__).resolve().parent

    return str(base_path / relative_path)


def get_ffmpeg_path() -> str:
    """
    获取 ffmpeg.exe 的路径。
    优先查找项目 bin/ 目录下的 ffmpeg.exe，否则回退到系统 PATH。
    """
    bundled = get_resource_path(os.path.join('bin', 'ffmpeg.exe'))
    if os.path.isfile(bundled):
        return bundled
    # 系统 PATH 中的 ffmpeg
    return 'ffmpeg'


def get_ffprobe_path() -> str:
    """
    获取 ffprobe.exe 的路径。
    优先查找项目 bin/ 目录，否则回退到系统 PATH。
    """
    bundled = get_resource_path(os.path.join('bin', 'ffprobe.exe'))
    if os.path.isfile(bundled):
        return bundled
    # 与 ffmpeg 同目录查找
    ffmpeg = get_ffmpeg_path()
    if os.path.isfile(ffmpeg):
        candidate = str(Path(ffmpeg).parent / 'ffprobe.exe')
        if os.path.isfile(candidate):
            return candidate
    return 'ffprobe'


def get_ffmpeg_version() -> str:
    """获取 ffmpeg 版本字符串，失败返回空字符串。"""
    try:
        ffmpeg = get_ffmpeg_path()
        result = subprocess.run(
            [ffmpeg, '-version'],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            timeout=5,
        )
        # 输出格式: "ffmpeg version 6.0-full_build ..."
        first_line = result.stdout.splitlines()[0] if result.stdout else ''
        if 'version' in first_line:
            parts = first_line.split()
            idx = parts.index('version')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return first_line[:50] if first_line else ''
    except Exception:
        return ''


def get_disk_free(path: str) -> int:
    """
    获取指定路径所在磁盘的剩余空间（字节）。

    Args:
        path: 任意路径（文件或目录）。不存在时取其父目录。

    Returns:
        剩余字节数；获取失败返回 -1。
    """
    if not path:
        return -1
    # 找到真实存在的祖先目录
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return -1


def run_subprocess(args: list, **kwargs) -> subprocess.CompletedProcess:
    """
    包装 subprocess.run，自动添加 CREATE_NO_WINDOW 隐藏黑框。

    所有外部进程调用必须通过此函数，确保桌面体验。
    """
    # 仅在 Windows 下添加隐藏窗口标志
    if sys.platform == 'win32':
        kwargs.setdefault('creationflags', CREATE_NO_WINDOW)

    # 默认使用 UTF-8 编码捕获输出
    kwargs.setdefault('encoding', 'utf-8')
    kwargs.setdefault('errors', 'replace')

    return subprocess.run(args, **kwargs)


def run_subprocess_popen(args: list, **kwargs) -> subprocess.Popen:
    """
    包装 subprocess.Popen，自动添加 CREATE_NO_WINDOW 隐藏黑框。

    适用于需要持有进程句柄以支持后续 kill() 的场景。
    返回 Popen 对象，调用方负责管理其生命周期。
    """
    if sys.platform == 'win32':
        kwargs.setdefault('creationflags', CREATE_NO_WINDOW)

    kwargs.setdefault('encoding', 'utf-8')
    kwargs.setdefault('errors', 'replace')

    return subprocess.Popen(args, **kwargs)


def kill_process_tree(proc: subprocess.Popen) -> None:
    """
    安全终止进程及其子进程树。

    Windows 下用 taskkill /F /T 杀掉整棵进程树，
    其他平台用 proc.kill()。超时后强制 kill。
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == 'win32':
            run_subprocess(
                ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        try:
            proc.kill()
        except Exception:
            pass


class ProcessContext:
    """
    进程上下文管理器，确保子进程被正确清理。

    用法:
        with ProcessContext(cmd, stdout=subprocess.PIPE) as proc:
            # 使用 proc
            proc.wait()
        # 退出 with 时自动杀死进程树（如果还在运行）
    """

    def __init__(self, cmd: list, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> subprocess.Popen:
        self.proc = subprocess.Popen(self.cmd, **self.kwargs)
        return self.proc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.proc is None:
            return False
        if self.proc.poll() is None:
            self._kill_tree()
        return False

    def _kill_tree(self):
        """杀死整个进程树。"""
        kill_process_tree(self.proc)


def safe_temp_path(target_path: str) -> str:
    """
    生成安全的临时输出路径（同目录，保留原扩展名）。

    关键：必须保留真实扩展名作为路径末尾，否则 ffmpeg 无法
    从文件名推断输出 muxer / 容器格式，会报 "Unable to choose
    an output format" 并以 EINVAL 退出。

    例：foo.wmv  →  foo.~tmp.wmv

    转换成功后再原子重命名为最终文件，避免跨分区移动导致 I/O 开销。
    """
    p = Path(target_path)
    return str(p.with_name(p.stem + '.~tmp' + p.suffix))


def finalize_file(temp_path: str, target_path: str) -> None:
    """
    将临时文件重命名为最终文件（原子操作）。

    如果目标已存在，先删除再重命名，避免 os.rename
    在 Windows 上因目标存在而失败。
    """
    temp_path = Path(temp_path)
    target_path = Path(target_path)

    if temp_path == target_path:
        return

    if temp_path.exists():
        os.replace(str(temp_path), str(target_path))


def get_file_size_str(file_path: str) -> str:
    """返回文件的可读大小字符串。"""
    try:
        size = os.path.getsize(file_path)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'
    except (OSError, FileNotFoundError):
        return '未知'


def ensure_output_dir(file_path: str) -> None:
    """确保输出文件所在的目录存在。"""
    Path(file_path).resolve().parent.mkdir(parents=True, exist_ok=True)


# 扩展名 → 类别映射（懒加载，从 formats.py 的 CATEGORY_EXTS 自动生成，保证 SSOT）
_CATEGORY_MAP: Optional[dict[str, str]] = None


def _ensure_category_map() -> dict[str, str]:
    """懒加载 _CATEGORY_MAP，从 formats.CATEGORY_EXTS 生成。"""
    global _CATEGORY_MAP
    if _CATEGORY_MAP is not None:
        return _CATEGORY_MAP
    # 延迟导入，打破循环引用：utils ← workers ← formats
    from formats import CATEGORY_EXTS
    _CATEGORY_MAP = {}
    # RUNTIME-01: 使用 setdefault 避免后注册覆盖（如 spreadsheet 的 .jpg/.png 覆盖 image）
    for _cat_key, _exts in CATEGORY_EXTS.items():
        for _ext in _exts:
            _CATEGORY_MAP.setdefault(_ext.lstrip('.'), _cat_key)
    # 补充输入侧有但输出侧没有的扩展名（如 .doc, .svg 等）
    _EXTRA_INPUT_MAP = {
        'video': ('mts', 'm2ts', '3gp', 'ogv', 'vob', 'm4v', 'ts'),  # RUNTIME-05
        'audio': ('ac3', 'dts', 'ape', 'aiff', 'opus'),  # RUNTIME-06
        'image': ('tiff', 'tif', 'ico', 'svg', 'jpeg', 'heic', 'heif'),  # RUNTIME-04
        'document': ('doc', 'txt', 'rtf', 'html', 'htm', 'md'),
        'spreadsheet': ('xls', 'xlsx'),
    }
    for _cat_key, _exts in _EXTRA_INPUT_MAP.items():
        for _ext in _exts:
            _CATEGORY_MAP.setdefault(_ext, _cat_key)
    # FIX-10: GIF 默认归入 image（用户持有 .gif 文件时通常期望图片类别）
    # 视频转 GIF 场景仍可用，用户手动选"视频"类别即可
    _CATEGORY_MAP['gif'] = 'image'
    return _CATEGORY_MAP


def map_format_to_category(fmt: str) -> str:
    """根据文件扩展名（不包含点号）推测所属类别。"""
    return _ensure_category_map().get(fmt.lower().lstrip('.'), 'unknown')
