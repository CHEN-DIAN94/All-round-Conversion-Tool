"""
engines.pdf_convert — PDF 与图片互转引擎

- pdf_to_images: PDF 每页导出为 PNG/JPG
- images_to_pdf: 多张图片合并为 PDF

注意：pdf_to_images 依赖 poppler（系统级工具）。
Windows 用户需下载 poppler 并加入 PATH：
https://github.com/osber/poppler-windows/releases
"""

import os
from pathlib import Path
from typing import Callable, Optional

from utils import ensure_output_dir
from engines._common import _check_disk_space

__all__ = ['pdf_to_images', 'images_to_pdf']


# 检查 poppler 可用性
_PDF2IMAGE_AVAILABLE = False
try:
    from pdf2image import convert_from_path
    # 检查 poppler 二进制是否在 PATH 中（仅 import pdf2image 不够）
    import subprocess as _sp
    try:
        _sp.run(['pdftoppm', '-h'], capture_output=True, timeout=5)
        _PDF2IMAGE_AVAILABLE = True
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass
except ImportError:
    pass


def pdf_to_images(
    input_path: str,
    output_dir: str,
    fmt: str = 'png',
    dpi: int = 200,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> list[str]:
    """
    PDF 每页导出为图片。

    Args:
        input_path: 输入 PDF 路径
        output_dir: 输出目录
        fmt: 输出格式 (png/jpg)
        dpi: 分辨率 (默认 200)
        progress_callback: 进度回调

    Returns:
        生成的图片路径列表
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')

    if not _PDF2IMAGE_AVAILABLE:
        raise RuntimeError(
            'PDF 转图片需要 poppler，请下载安装并加入 PATH：\n'
            'https://github.com/osber/poppler-windows/releases'
        )

    from pdf2image import convert_from_path

    os.makedirs(output_dir, exist_ok=True)
    stem = Path(input_path).stem

    images = convert_from_path(input_path, dpi=dpi, fmt=fmt)
    total = len(images)
    output_files = []

    for i, img in enumerate(images):
        out_path = os.path.join(output_dir, f'{stem}_page{i+1}.{fmt}')
        if fmt == 'jpg':
            img = img.convert('RGB')
            img.save(out_path, 'JPEG', quality=95)
        else:
            img.save(out_path, 'PNG')
        output_files.append(out_path)
        if progress_callback and total > 0:
            progress_callback(min(int((i + 1) / total * 100), 99))

    if progress_callback:
        progress_callback(100)

    return output_files


def images_to_pdf(
    input_paths: list[str],
    output_path: str,
    page_size: str = 'auto',
) -> str:
    """
    多张图片合并为 PDF。

    Args:
        input_paths: 输入图片路径列表（按顺序合并）
        output_path: 输出 PDF 路径
        page_size: 页面大小 ('auto'=图片原始尺寸, 'a4'=A4 页面)

    Returns:
        输出文件路径
    """
    from PIL import Image

    if not input_paths:
        raise ValueError('输入图片列表为空')

    _check_disk_space(output_path)
    ensure_output_dir(output_path)

    images = []
    first_image = None

    for p in input_paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(f'文件不存在: {p}')
        img = Image.open(p).convert('RGB')
        if first_image is None:
            first_image = img
        images.append(img)

    if page_size == 'a4':
        # A4 at 72 DPI: 595 x 842 points
        a4_w, a4_h = 595, 842
        resized = []
        originals = list(images)  # 保存原始引用以便后续关闭
        for img in images:
            # 等比缩放到 A4 范围内
            ratio = min(a4_w / img.width, a4_h / img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            # 居中放到 A4 画布
            a4_img = Image.new('RGB', (a4_w, a4_h), (255, 255, 255))
            offset_x = (a4_w - new_w) // 2
            offset_y = (a4_h - new_h) // 2
            a4_img.paste(img_resized, (offset_x, offset_y))
            resized.append(a4_img)
        # BUG-002 修复：关闭原始 img 避免泄漏（save 用的是 resized 列表）
        for img in originals:
            img.close()
        images = resized
        first_image = images[0]  # 更新 first_image 指向 resized

    first_image.save(output_path, 'PDF', save_all=True, append_images=images[1:])

    # 清理
    for img in images:
        img.close()

    return output_path
