"""
engines._common — 转换引擎共享辅助函数
"""

import shutil
from pathlib import Path

from utils import safe_temp_path, ensure_output_dir


def _check_disk_space(output_path: str, min_free_mb: int = 0) -> None:
    """
    检查输出磁盘剩余空间。

    min_free_mb=0 时自动根据输入推算（至少 100MB）。
    """
    if min_free_mb <= 0:
        min_free_mb = 100  # 最低保底 100MB
    try:
        usage = shutil.disk_usage(str(Path(output_path).resolve().parent))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < min_free_mb:
            raise RuntimeError(
                f'磁盘空间不足：剩余 {free_mb:.0f} MB，'
                f'建议至少预留 {min_free_mb} MB 可用空间。'
            )
    except (OSError, PermissionError):
        pass  # 无法获取磁盘信息时跳过检查（不阻塞转换）


def _prepare_output(output_path: str, min_free_mb: int = 0) -> str:
    """
    检查磁盘空间、确保输出目录存在、生成临时路径。

    返回临时文件路径，转换成功后需调用 finalize_file 重命名为最终路径。
    """
    _check_disk_space(output_path, min_free_mb)
    ensure_output_dir(output_path)
    return safe_temp_path(output_path)
