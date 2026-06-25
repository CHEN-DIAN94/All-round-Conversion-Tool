"""
engines.compress_engine — 批量图片压缩引擎

不改变格式，只压缩文件大小。
支持质量迭代、目标文件大小限制。
"""


__all__ = ['compress_image']

import os
from pathlib import Path

from utils import finalize_file
from engines._common import _prepare_output


def compress_image(
    input_path: str,
    output_path: str,
    target_size_kb: int = 0,
    quality: int = 80,
    max_dimension: int = 0,
) -> str:
    """
    压缩图片（保持原格式）。

    两种模式：
    1. 固定质量：直接用指定 quality 保存
    2. 目标大小：二分法迭代 quality 直到文件大小接近目标

    Args:
        input_path: 输入图片路径
        output_path: 输出路径（格式与输入相同）
        target_size_kb: 目标文件大小（KB），0=使用固定质量模式
        quality: 固定质量模式的质量值（1-100）
        max_dimension: 最大边长（像素），0=不缩放

    Returns:
        输出文件路径
    """
    from PIL import Image, UnidentifiedImageError

    temp_path = _prepare_output(output_path)

    try:
        img = Image.open(input_path)
    except UnidentifiedImageError:
        raise RuntimeError(f'无法识别的图片格式: {os.path.basename(input_path)}')

    try:
        # 缩放
        if max_dimension > 0:
            w, h = img.size
            if max(w, h) > max_dimension:
                ratio = max_dimension / max(w, h)
                new_w = int(w * ratio)
                new_h = int(h * ratio)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 处理透明通道（JPEG 不支持 RGBA）
        output_ext = Path(output_path).suffix.lower()
        if output_ext in ('.jpg', '.jpeg') and img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1])
            img = background

        if target_size_kb > 0:
            # 目标大小模式：二分法迭代
            _save_with_target_size(img, temp_path, output_ext, target_size_kb)
        else:
            # 固定质量模式
            _save_with_quality(img, temp_path, output_ext, quality)

    finally:
        img.close()

    finalize_file(temp_path, output_path)
    return output_path


def _save_with_quality(img, path: str, ext: str, quality: int) -> None:
    """用指定质量保存。"""
    kwargs = {}
    if ext in ('.jpg', '.jpeg', '.webp'):
        kwargs['quality'] = quality
        kwargs['optimize'] = True
    elif ext == '.png':
        kwargs['optimize'] = True
        # PNG 无 quality 参数，用 compress_level 替代
        kwargs['compress_level'] = max(1, min(9, (100 - quality) // 10 + 1))
    img.save(path, **kwargs)


def _save_with_target_size(img, path: str, ext: str, target_kb: int) -> None:
    """二分法迭代 quality 达到目标文件大小。"""
    if ext == '.png':
        # PNG 用 compress_level
        for level in range(1, 10):
            img.save(path, optimize=True, compress_level=level)
            if os.path.getsize(path) / 1024 <= target_kb:
                return
        return

    # JPEG/WEBP 用 quality 二分
    lo, hi = 10, 95
    best_quality = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        img.save(path, quality=mid, optimize=True)
        size_kb = os.path.getsize(path) / 1024
        if size_kb <= target_kb:
            best_quality = mid
            lo = mid + 1
        else:
            hi = mid - 1

    img.save(path, quality=best_quality, optimize=True)
