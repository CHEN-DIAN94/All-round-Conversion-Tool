"""
utils.py — 底层工具函数
提供资源寻址、幽灵黑框消除、文件直出等基础能力。
"""

import sys
import os
import subprocess
from pathlib import Path


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


def run_subprocess(args: list, **kwargs) -> subprocess.CompletedProcess:
    """
    包装 subprocess.run，自动添加 CREATE_NO_WINDOW 隐藏黑框。

    所有外部进程调用必须通过此函数，确保桌面体验。
    """
    # 仅在 Windows 下添加隐藏窗口标志
    if sys.platform == 'win32':
        kwargs.setdefault('creationflags', CREATE_NO_WINDOW)
        # 也禁止创建新窗口组的标志
        kwargs.setdefault('startupinfo', None)

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


def safe_temp_path(target_path: str) -> str:
    """
    生成安全的临时输出路径（同目录 + .tmp 后缀）。

    废弃系统 tempfile：直接在与目标相同的目录下写入，
    转换成功后再原子重命名，避免跨分区移动导致 I/O 开销。
    """
    return target_path + '.tmp'


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

    if target_path.exists():
        target_path.unlink()

    if temp_path.exists():
        temp_path.rename(target_path)


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


def map_format_to_category(fmt: str) -> str:
    """
    根据文件扩展名（不包含点号）推测所属类别。
    返回 'video', 'audio', 'image', 'document' 或 'unknown'。
    """
    fmt = fmt.lower().lstrip('.')

    video_exts = {
        'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm', 'm4v',
        'ts', 'mts', 'm2ts', '3gp', 'ogv', 'vob',
    }
    audio_exts = {
        'mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus',
        'ac3', 'dts', 'ape', 'aiff',
    }
    image_exts = {
        'jpg', 'jpeg', 'png', 'bmp', 'gif', 'tiff', 'tif', 'webp',
        'ico', 'svg',
    }
    document_exts = {
        'pdf', 'docx', 'doc', 'txt', 'rtf', 'html', 'htm', 'md',
    }

    if fmt in video_exts:
        return 'video'
    if fmt in audio_exts:
        return 'audio'
    if fmt in image_exts:
        return 'image'
    if fmt in document_exts:
        return 'document'
    return 'unknown'
