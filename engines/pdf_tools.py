"""
engines.pdf_tools — PDF 合并/拆分工具

基于 PyPDF2 实现，纯 Python，无需外部依赖。
"""


__all__ = ['merge_pdfs', 'split_pdf', 'get_pdf_info']

import os
from pathlib import Path
from typing import Optional

from utils import ensure_output_dir
from engines._common import _check_disk_space


def merge_pdfs(
    input_paths: list[str],
    output_path: str,
) -> str:
    """
    合并多个 PDF 文件。

    Args:
        input_paths: 输入 PDF 路径列表（按顺序合并）
        output_path: 输出 PDF 路径

    Returns:
        输出文件路径
    """
    from pypdf import PdfMerger

    _check_disk_space(output_path)
    ensure_output_dir(output_path)

    merger = PdfMerger()
    try:
        for p in input_paths:
            if not os.path.isfile(p):
                raise FileNotFoundError(f'文件不存在: {p}')
            merger.append(p)
        merger.write(output_path)
    finally:
        merger.close()

    return output_path


def split_pdf(
    input_path: str,
    output_dir: str,
    pages_per_file: int = 1,
    page_ranges: Optional[list[tuple[int, int]]] = None,
) -> list[str]:
    """
    拆分 PDF 文件。

    两种模式：
    1. 按页数拆分：每 N 页生成一个文件
    2. 按范围拆分：指定页码范围列表

    Args:
        input_path: 输入 PDF 路径
        output_dir: 输出目录
        pages_per_file: 每个文件的页数（模式 1）
        page_ranges: 页码范围列表，如 [(1,3), (4,6)]（模式 2，1-indexed）

    Returns:
        生成的文件路径列表
    """
    from pypdf import PdfReader, PdfWriter

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'文件不存在: {input_path}')

    os.makedirs(output_dir, exist_ok=True)
    stem = Path(input_path).stem
    suffix = '.pdf'

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)
    output_files = []

    if page_ranges:
        # 按范围拆分
        for i, (start, end) in enumerate(page_ranges):
            writer = PdfWriter()
            for p in range(start - 1, min(end, total_pages)):
                writer.add_page(reader.pages[p])
            out_path = os.path.join(output_dir, f'{stem}_p{start}-{end}{suffix}')
            with open(out_path, 'wb') as f:
                writer.write(f)
            output_files.append(out_path)
    else:
        # 按页数拆分
        part = 0
        for start in range(0, total_pages, pages_per_file):
            part += 1
            writer = PdfWriter()
            end = min(start + pages_per_file, total_pages)
            for p in range(start, end):
                writer.add_page(reader.pages[p])
            out_path = os.path.join(output_dir, f'{stem}_part{part}{suffix}')
            with open(out_path, 'wb') as f:
                writer.write(f)
            output_files.append(out_path)

    return output_files


def get_pdf_info(input_path: str) -> dict:
    """获取 PDF 基本信息。"""
    from pypdf import PdfReader

    reader = PdfReader(input_path)
    info = reader.metadata
    return {
        'pages': len(reader.pages),
        'title': info.title if info else '',
        'author': info.author if info else '',
        'file_size': os.path.getsize(input_path),
    }
