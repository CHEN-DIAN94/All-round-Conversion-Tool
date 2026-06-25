"""
engines.watermark_engine — 图片水印引擎

支持文字水印和图片水印，可批量应用。
"""


__all__ = ['add_watermark']

import os
from typing import Optional

from utils import finalize_file
from engines._common import _prepare_output


def add_watermark(
    input_path: str,
    output_path: str,
    text: str = '',
    watermark_image: str = '',
    position: str = 'bottom-right',
    opacity: float = 0.5,
    font_size: int = 24,
    margin: int = 10,
    progress_callback=None,
) -> str:
    """
    给图片添加水印。

    Args:
        input_path: 输入图片路径
        output_path: 输出路径
        text: 文字水印内容（与 watermark_image 二选一）
        watermark_image: 水印图片路径（与 text 二选一）
        position: 位置 (top-left, top-right, bottom-left, bottom-right, center)
        opacity: 水印透明度 (0.0-1.0)
        font_size: 文字水印字号
        margin: 边距（像素）

    Returns:
        输出文件路径
    """
    from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')

    temp_path = _prepare_output(output_path)

    if progress_callback:
        progress_callback(50)

    try:
        img = Image.open(input_path).convert('RGBA')
    except UnidentifiedImageError:
        raise RuntimeError(f'无法识别的图片: {os.path.basename(input_path)}')

    try:
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))

        if text:
            _draw_text_watermark(overlay, text, position, opacity, font_size, margin)
        elif watermark_image:
            _paste_image_watermark(overlay, watermark_image, position, opacity, margin)
        else:
            raise ValueError('必须提供 text 或 watermark_image')

        img = Image.alpha_composite(img, overlay)
        img = img.convert('RGB')
        img.save(temp_path, quality=95, optimize=True)

    finally:
        img.close()

    finalize_file(temp_path, output_path)
    if progress_callback:
        progress_callback(100)
    return output_path


def _draw_text_watermark(overlay, text, position, opacity, font_size, margin):
    """在 overlay 上绘制文字水印。"""
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(overlay)
    w, h = overlay.size

    # 尝试加载字体
    font = None
    for name in ['msyh.ttc', 'simsun.ttc', 'arial.ttf', 'DejaVuSans.ttf']:
        try:
            font = ImageFont.truetype(name, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    # 计算文字尺寸
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # 计算位置
    x, y = _calc_position(w, h, tw, th, position, margin)

    alpha = int(opacity * 255)
    draw.text((x, y), text, fill=(255, 255, 255, alpha), font=font)


def _paste_image_watermark(overlay, wm_path, position, opacity, margin):
    """在 overlay 上粘贴图片水印。"""
    from PIL import Image

    wm = Image.open(wm_path).convert('RGBA')
    w, h = overlay.size

    # 缩放水印到图片的 1/4
    max_wm = min(w, h) // 4
    if wm.width > max_wm or wm.height > max_wm:
        ratio = max_wm / max(wm.width, wm.height)
        wm = wm.resize((int(wm.width * ratio), int(wm.height * ratio)),
                       Image.Resampling.LANCZOS)

    # 调整透明度
    if opacity < 1.0:
        alpha = wm.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        wm.putalpha(alpha)

    x, y = _calc_position(w, h, wm.width, wm.height, position, margin)
    overlay.paste(wm, (x, y), wm)
    wm.close()


def _calc_position(canvas_w, canvas_h, obj_w, obj_h, position, margin):
    """计算水印位置。"""
    positions = {
        'top-left': (margin, margin),
        'top-right': (canvas_w - obj_w - margin, margin),
        'bottom-left': (margin, canvas_h - obj_h - margin),
        'bottom-right': (canvas_w - obj_w - margin, canvas_h - obj_h - margin),
        'center': ((canvas_w - obj_w) // 2, (canvas_h - obj_h) // 2),
    }
    return positions.get(position, positions['bottom-right'])
