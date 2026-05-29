"""
tests.test_format_handlers — 格式处理器注册表测试

覆盖：
- IcoHandler 尺寸约束
- BmpHandler 大文件警告
- GifHandler 动画检测
- TiffHandler 压缩参数
- get_format_handler 注册表查询
"""

import pytest
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from engines.format_handlers import (
    get_format_handler,
    IcoHandler,
    BmpHandler,
    GifHandler,
    TiffHandler,
)


class TestIcoHandler:
    """ICO 格式处理器测试"""

    def test_large_image_resize(self):
        """大图应被缩放到 256×256"""
        handler = IcoHandler()
        img = Image.new('RGB', (4000, 3000), 'red')

        result = handler.prepare_output(img)

        assert result.width <= 256
        assert result.height <= 256

    def test_small_image_unchanged(self):
        """小图不应被缩放"""
        handler = IcoHandler()
        img = Image.new('RGB', (100, 100), 'red')

        result = handler.prepare_output(img)

        assert result.width == 100
        assert result.height == 100

    def test_validation_warning_for_large_image(self):
        """大图应产生警告"""
        handler = IcoHandler()
        img = Image.new('RGB', (4000, 3000), 'red')

        warnings = handler.validate_input(img)

        assert len(warnings) > 0
        assert '缩放' in warnings[0]

    def test_no_warning_for_small_image(self):
        """小图不应产生警告"""
        handler = IcoHandler()
        img = Image.new('RGB', (100, 100), 'red')

        warnings = handler.validate_input(img)

        assert len(warnings) == 0

    def test_rgba_conversion(self):
        """非 RGBA 模式应被转换"""
        handler = IcoHandler()
        img = Image.new('RGB', (100, 100), 'red')

        result = handler.prepare_output(img)

        assert result.mode == 'RGBA'

    def test_default_params(self):
        """默认参数应包含 format"""
        handler = IcoHandler()
        params = handler.get_default_params()

        assert 'format' in params
        assert params['format'] == 'ICO'


class TestBmpHandler:
    """BMP 格式处理器测试"""

    def test_large_image_warning(self):
        """超大图应产生警告"""
        handler = BmpHandler()
        # 10001x10001 > 1亿像素
        img = Image.new('RGB', (10001, 10001), 'red')

        warnings = handler.validate_input(img)

        assert len(warnings) > 0
        assert 'MB' in warnings[0]

    def test_small_image_no_warning(self):
        """小图不应产生警告"""
        handler = BmpHandler()
        img = Image.new('RGB', (100, 100), 'red')

        warnings = handler.validate_input(img)

        assert len(warnings) == 0

    def test_prepare_output_unchanged(self):
        """prepare_output 不修改图片"""
        handler = BmpHandler()
        img = Image.new('RGB', (100, 100), 'red')

        result = handler.prepare_output(img)

        assert result is img


class TestGifHandler:
    """GIF 格式处理器测试"""

    def test_static_gif_no_warning(self):
        """静态 GIF 不应产生警告"""
        handler = GifHandler()
        img = Image.new('RGB', (100, 100), 'red')

        warnings = handler.validate_input(img)

        assert len(warnings) == 0

    def test_default_params_static_image(self):
        """N-07: 非动画源图不应使用 save_all"""
        handler = GifHandler()
        img = Image.new('RGB', (100, 100), 'red')

        params = handler.get_default_params(img)

        assert 'save_all' not in params

    def test_default_params_no_image(self):
        """无 img 参数时不应使用 save_all"""
        handler = GifHandler()

        params = handler.get_default_params()

        assert 'save_all' not in params

    def test_prepare_output_rgba_to_p(self):
        """N-07: RGBA 图片应量化为 P 模式"""
        handler = GifHandler()
        img = Image.new('RGBA', (100, 100), (255, 0, 0, 128))

        result = handler.prepare_output(img)

        assert result.mode in ('P', 'L')

    def test_prepare_output_rgb_to_p(self):
        """N-07: RGB 图片应转换为 P 模式"""
        handler = GifHandler()
        img = Image.new('RGB', (100, 100), 'red')

        result = handler.prepare_output(img)

        assert result.mode in ('P', 'L')


class TestTiffHandler:
    """TIFF 格式处理器测试"""

    def test_default_params(self):
        """默认参数应包含 LZW 压缩"""
        handler = TiffHandler()
        params = handler.get_default_params()

        assert 'compression' in params
        assert params['compression'] == 'tiff_lzw'


class TestGetFormatHandler:
    """注册表查询测试"""

    def test_ico_handler(self):
        """获取 ICO 处理器"""
        handler = get_format_handler('.ico')
        assert isinstance(handler, IcoHandler)

    def test_bmp_handler(self):
        """获取 BMP 处理器"""
        handler = get_format_handler('.bmp')
        assert isinstance(handler, BmpHandler)

    def test_tiff_handler(self):
        """获取 TIFF 处理器"""
        handler = get_format_handler('.tiff')
        assert isinstance(handler, TiffHandler)

    def test_tif_handler(self):
        """获取 TIF 处理器（别名）"""
        handler = get_format_handler('.tif')
        assert isinstance(handler, TiffHandler)

    def test_unknown_returns_none(self):
        """未知格式返回 None"""
        handler = get_format_handler('.xyz')
        assert handler is None

    def test_png_returns_none(self):
        """PNG 无特殊处理器"""
        handler = get_format_handler('.png')
        assert handler is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
