"""
engines.image_resize — 图片批量缩放引擎

支持按像素尺寸、百分比、最大边长缩放。
"""

import os
from pathlib import Path
from typing import Callable, Optional

from utils import finalize_file
from engines._common import _prepare_output

__all__ = ['resize_image']



def resize_image(
    input_path: str,
    output_path: str,
    width: int = 0,
    height: int = 0,
    percentage: float = 0,
    max_dimension: int = 0,
    keep_aspect: bool = True,
    quality: int = 95,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """
    缩放图片。

    四种模式（优先级从高到低）：
    1. width + height: 指定尺寸（keep_aspect=True 时等比缩放到包含框）
    2. percentage: 按百分比
    3. max_dimension: 最大边长限制
    4. 仅 width 或仅 height: 指定一边，另一边自动计算

    Args:
        input_path: 输入图片路径
        output_path: 输出路径
        width: 目标宽度（像素），0=自动
        height: 目标高度（像素），0=自动
        percentage: 缩放百分比（如 50 = 缩小一半）
        max_dimension: 最大边长（像素）
        keep_aspect: 是否保持宽高比
        quality: 输出质量 (1-100)

    Returns:
        输出文件路径
    """
    from PIL import Image, UnidentifiedImageError

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')

    temp_path = _prepare_output(output_path)

    try:
        img = Image.open(input_path)
    except UnidentifiedImageError:
        raise RuntimeError(f'无法识别的图片: {os.path.basename(input_path)}')

    try:
        orig_w, orig_h = img.size

        # 计算目标尺寸
        new_w, new_h = _calc_size(orig_w, orig_h, width, height, percentage, max_dimension)

        if new_w != orig_w or new_h != orig_h:
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        if progress_callback:
            progress_callback(50)

        # 保存（BUG-001 修复：_get_save_kwargs 可能返回新 img 以处理透明通道）
        output_ext = Path(output_path).suffix.lower()
        save_kwargs, img = _get_save_kwargs(output_ext, quality, img)
        img.save(temp_path, **save_kwargs)

    finally:
        img.close()

    finalize_file(temp_path, output_path)
    if progress_callback:
        progress_callback(100)
    return output_path


def _calc_size(orig_w, orig_h, width, height, percentage, max_dimension):
    """计算目标尺寸。"""
    if percentage > 0:
        return max(1, int(orig_w * percentage / 100)), max(1, int(orig_h * percentage / 100))

    if max_dimension > 0:
        if max(orig_w, orig_h) <= max_dimension:
            return orig_w, orig_h
        ratio = max_dimension / max(orig_w, orig_h)
        return max(1, int(orig_w * ratio)), max(1, int(orig_h * ratio))

    if width > 0 and height > 0:
        return width, height

    if width > 0:
        ratio = width / orig_w
        return width, max(1, int(orig_h * ratio))

    if height > 0:
        ratio = height / orig_h
        return max(1, int(orig_w * ratio)), height

    return orig_w, orig_h


def _get_save_kwargs(ext, quality, img):
    """根据格式返回保存参数。返回 (kwargs, img) 二元组，JPEG 时可能替换 img 以处理透明通道。"""
    kwargs = {}
    if ext in ('.jpg', '.jpeg'):
        kwargs['quality'] = quality
        kwargs['optimize'] = True
        # BUG-001 修复：P/LA/RGBA 模式保存 JPEG 需要转 RGB，必须传回新 img
        if img.mode in ('RGBA', 'LA', 'P'):
            from PIL import Image as _Img
            bg = _Img.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1])
            img = bg
    elif ext == '.webp':
        kwargs['quality'] = quality
    elif ext == '.png':
        kwargs['optimize'] = True
    elif ext in ('.tiff', '.tif'):
        kwargs['compression'] = 'tiff_lzw'
    return kwargs, img
