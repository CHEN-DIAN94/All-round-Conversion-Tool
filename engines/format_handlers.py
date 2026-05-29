"""
engines.format_handlers — 格式特殊处理注册表

采用注册表模式，每种格式的特殊约束（如 ICO 尺寸限制）
封装为独立 Handler，新增格式只需注册，无需修改引擎代码。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from PIL import Image


class FormatHandler(ABC):
    """格式特殊处理基类"""

    @abstractmethod
    def validate_input(self, data: Any) -> List[str]:
        """验证输入，返回警告列表"""
        ...

    @abstractmethod
    def prepare_output(self, data: Any) -> Any:
        """预处理数据，返回处理后的对象"""
        ...

    def get_default_params(self, img: Image.Image = None) -> dict:
        """获取默认保存参数，可接收 img 以判断源图状态"""
        return {}


class IcoHandler(FormatHandler):
    """ICO 格式处理器 — 限制 256×256，强制 RGBA"""

    MAX_SIZE = 256

    def validate_input(self, img: Image.Image) -> List[str]:
        warnings = []
        if img.width > self.MAX_SIZE or img.height > self.MAX_SIZE:
            warnings.append(
                f'图片将从 {img.width}×{img.height} 缩放到 {self.MAX_SIZE}×{self.MAX_SIZE}'
            )
        return warnings

    def prepare_output(self, img: Image.Image) -> Image.Image:
        if img.width > self.MAX_SIZE or img.height > self.MAX_SIZE:
            img.thumbnail((self.MAX_SIZE, self.MAX_SIZE), Image.Resampling.LANCZOS)
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        return img

    def get_default_params(self) -> dict:
        return {'format': 'ICO'}


class BmpHandler(FormatHandler):
    """BMP 格式处理器 — 大文件警告"""

    MAX_PIXELS = 100_000_000  # 1 亿像素

    def validate_input(self, img: Image.Image) -> List[str]:
        warnings = []
        pixels = img.width * img.height
        if pixels > self.MAX_PIXELS:
            size_mb = pixels * 3 / 1024 / 1024  # RGB
            warnings.append(f'BMP 文件可能很大: ~{size_mb:.0f} MB')
        return warnings

    def prepare_output(self, img: Image.Image) -> Image.Image:
        return img


class GifHandler(FormatHandler):
    """GIF 格式处理器 — 动画帧检测 + 色深量化"""

    def validate_input(self, img: Image.Image) -> List[str]:
        warnings = []
        if hasattr(img, 'n_frames') and img.n_frames > 1:
            warnings.append(f'检测到动画 GIF，共 {img.n_frames} 帧')
        return warnings

    def prepare_output(self, img: Image.Image) -> Image.Image:
        # N-07 修复：GIF 只支持 8 位色深和 1-bit 透明
        if img.mode == 'RGBA':
            # RGBA 只能用 FASTOCTREE 量化（Pillow 限制）
            img = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        elif img.mode == 'RGB':
            img = img.convert('P')
        elif img.mode not in ('P', 'L'):
            img = img.convert('P')
        return img

    def get_default_params(self, img: Image.Image = None) -> dict:
        """
        N-07 修复：根据是否动画源图决定是否使用 save_all。

        只有动画源图（n_frames > 1）才使用 save_all，
        非动画源图让 Pillow 自动判断。
        """
        if img and hasattr(img, 'n_frames') and img.n_frames > 1:
            return {'save_all': True}
        return {}


class TiffHandler(FormatHandler):
    """TIFF 格式处理器 — LZW 压缩"""

    def validate_input(self, data: Any) -> List[str]:
        return []

    def prepare_output(self, img: Image.Image) -> Image.Image:
        return img

    def get_default_params(self) -> dict:
        return {'compression': 'tiff_lzw'}


# 注册表：扩展名 → Handler 实例
FORMAT_HANDLERS: Dict[str, FormatHandler] = {
    '.ico': IcoHandler(),
    '.bmp': BmpHandler(),
    '.gif': GifHandler(),
    '.tiff': TiffHandler(),
    '.tif': TiffHandler(),
}


def get_format_handler(ext: str) -> FormatHandler | None:
    """获取格式处理器，无特殊处理返回 None。"""
    return FORMAT_HANDLERS.get(ext.lower())
