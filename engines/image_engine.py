"""
engines.image_engine — Pillow 图片格式转换引擎

集成 format_handlers 注册表，自动处理各格式的特殊约束（如 ICO 尺寸限制）。
支持 HEIC/HEIF 格式（通过 pillow-heif）。
"""

# 注册 HEIC/HEIF 支持（必须在 Pillow 导入前）
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


__all__ = ['convert_image']

import os
from pathlib import Path

from logging_config import get_logger
logger = get_logger(__name__)

from utils import finalize_file
from engines._common import _prepare_output


def convert_image(input_path: str, output_path: str, params: dict = None, warnings_collector: list = None) -> str:
    """
    图片格式转换（Pillow 实现）。

    通过 format_handlers 注册表自动处理各格式的特殊约束：
    - ICO：限制 256×256，强制 RGBA
    - GIF：量化为 P 模式，动画检测
    - BMP：大文件警告
    - TIFF：LZW 压缩

    Args:
        params: 高级设置参数，如 image_quality, image_resize 等
        warnings_collector: 可选列表，收集格式警告供 UI 展示
    """
    from PIL import Image, UnidentifiedImageError
    from engines.format_handlers import get_format_handler

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')

    temp_path = _prepare_output(output_path, min_free_mb=100)

    img = None
    try:
        img = Image.open(input_path)
    except UnidentifiedImageError:
        raise RuntimeError(f'无法识别的图片格式，文件可能已损坏: {os.path.basename(input_path)}')
    except Exception as e:
        raise RuntimeError(f'打开图片失败: {e}')

    try:
        output_ext = Path(output_path).suffix.lower()

        # N-09: 从 params 获取图片参数
        params = params or {}
        image_quality = params.get('image_quality', 95)
        image_resize = params.get('image_resize', 100)

        # N-09: 缩放处理
        if image_resize != 100:
            new_width = int(img.width * image_resize / 100)
            new_height = int(img.height * image_resize / 100)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # 获取格式处理器
        handler = get_format_handler(output_ext)

        if handler:
            # 验证输入（产生警告）
            warnings = handler.validate_input(img)
            for w in warnings:
                if warnings_collector is not None:
                    warnings_collector.append(w)
                else:
                    logger.warning(w)

            # 预处理（如缩放、模式转换）
            img = handler.prepare_output(img)

            # N-07 修复：传入 img 以判断是否动画源图
            save_kwargs = handler.get_default_params(img)
        else:
            save_kwargs = {}

        # ---------- 通用处理：透明通道 ----------
        # N-06 修复：ICO/GIF 由 handler 专门处理，跳过通用逻辑
        if output_ext not in ('.ico', '.gif'):
            img = _handle_alpha_channel(img, output_ext)

        # ---------- 保存 ----------
        custom_params = _get_image_save_params(output_ext, img)
        # N-09: 应用用户设置的 quality 参数
        if output_ext in ('.jpg', '.jpeg', '.webp'):
            custom_params['quality'] = image_quality
        save_kwargs.update(custom_params)
        img.save(temp_path, **save_kwargs)

    finally:
        if img is not None:
            img.close()

    finalize_file(temp_path, output_path)
    return output_path


def _handle_alpha_channel(img, output_ext: str):
    """
    处理透明通道（就地修改 img）。

    N-06 修复：ICO/GIF 由 handler 专门处理，调用前已过滤。
    """
    from PIL import Image

    alpha_formats = {'.png', '.webp', '.tiff', '.tif'}
    if output_ext in ('.jpg', '.jpeg', '.bmp'):
        # 不支持透明的格式：融合到白色背景
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            elif img.mode == 'LA':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1])
            return background
        elif img.mode not in ('RGB', 'L', '1'):
            return img.convert('RGB')
    elif output_ext in alpha_formats:
        # 支持透明的格式：保留 alpha 通道
        if img.mode == 'P':
            return img.convert('RGBA')
        elif img.mode == 'LA':
            return img.convert('RGBA')
        elif img.mode not in ('RGBA', 'RGB', 'L', '1'):
            return img.convert('RGBA')
    else:
        if img.mode not in ('RGB', 'L', '1'):
            return img.convert('RGB')
    return img


def _get_image_save_params(ext: str, img) -> dict:
    """根据输出格式返回 Pillow save 参数。"""
    params = {}
    if ext in ('.jpg', '.jpeg'):
        params['quality'] = 95
        params['optimize'] = True
    elif ext == '.png':
        params['optimize'] = True
    elif ext == '.webp':
        params['quality'] = 90
    elif ext in ('.tiff', '.tif'):
        params['compression'] = 'tiff_lzw'
    return params
