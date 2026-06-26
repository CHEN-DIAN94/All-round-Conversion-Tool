"""
engines — 转换引擎包

所有转换函数的统一入口。每个子模块实现一类转换逻辑。
"""

from engines.ffmpeg_core import (
    convert_video,
    convert_audio,
    extract_audio,
    trim_media,
    get_media_info,
)
from engines.image_engine import convert_image
from engines.excel_engine import convert_excel_to_image
from engines.document_engine import convert_pdf_to_docx, convert_docx_to_pdf
from engines.gif_engine import convert_video_to_gif
from engines.compress_engine import compress_image
from engines.watermark_engine import add_watermark
from engines.pdf_tools import merge_pdfs, split_pdf, get_pdf_info
from engines.video_compress import compress_video
from engines.image_resize import resize_image
from engines.pdf_convert import pdf_to_images, images_to_pdf
from engines.ffmpeg_utils import (
    export_ffmpeg_cmd, embed_subtitle, extract_subtitle,
    merge_media, crop_video,
)
from engines.gpu_scheduler import GpuScheduler, GpuBackend, GpuInfo

__all__ = [
    # 核心转换
    'convert_video', 'convert_audio', 'convert_image',
    'convert_pdf_to_docx', 'convert_docx_to_pdf', 'convert_excel_to_image',
    # 媒体工具
    'extract_audio', 'trim_media', 'get_media_info',
    # GIF
    'convert_video_to_gif',
    # 图片工具
    'compress_image', 'add_watermark', 'resize_image',
    # PDF 工具
    'merge_pdfs', 'split_pdf', 'get_pdf_info', 'pdf_to_images', 'images_to_pdf',
    # 视频工具
    'compress_video',
    # FFmpeg 高级工具
    'export_ffmpeg_cmd', 'embed_subtitle', 'extract_subtitle',
    'merge_media', 'crop_video',
    # GPU 调度
    'GpuScheduler', 'GpuBackend', 'GpuInfo',
]
