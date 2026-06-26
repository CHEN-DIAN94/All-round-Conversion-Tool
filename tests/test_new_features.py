"""
tests/test_new_features.py — 新功能测试

覆盖：video_compress, image_resize, pdf_convert, ffmpeg_utils
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.video_compress import compress_video, _get_duration


class TestVideoCompressImports:
    def test_import(self):
        assert callable(compress_video)

    def test_get_duration_nonexistent(self):
        result = _get_duration('/nonexistent.mp4')
        assert result == 0

    def test_compress_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            compress_video('/nonexistent.mp4', '/tmp/out.mp4')


class TestImageResize:
    def test_resize_nonexistent_raises(self):
        from engines.image_resize import resize_image
        with pytest.raises(FileNotFoundError):
            resize_image('/nonexistent.jpg', '/tmp/out.jpg')

    def test_resize_percentage(self):
        from PIL import Image
        from engines.image_resize import resize_image
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            in_path = f.name
            Image.new('RGB', (400, 400), 'red').save(f)
        out_path = in_path.replace('.png', '_out.png')
        try:
            result = resize_image(in_path, out_path, percentage=50)
            assert os.path.isfile(result)
            img = Image.open(result)
            assert img.size == (200, 200)
            img.close()
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_resize_max_dimension(self):
        from PIL import Image
        from engines.image_resize import resize_image
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            in_path = f.name
            Image.new('RGB', (1000, 800), 'blue').save(f)
        out_path = in_path.replace('.png', '_out.png')
        try:
            result = resize_image(in_path, out_path, max_dimension=500)
            img = Image.open(result)
            assert max(img.size) <= 500
            img.close()
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestPdfConvert:
    def test_images_to_pdf(self):
        from PIL import Image
        from engines.pdf_convert import images_to_pdf
        import tempfile

        imgs = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                Image.new('RGB', (100, 100), (i*80, 0, 0)).save(f)
                imgs.append(f.name)

        out_path = tempfile.mktemp(suffix='.pdf')
        try:
            result = images_to_pdf(imgs, out_path)
            assert os.path.isfile(result)
            assert os.path.getsize(result) > 0
        finally:
            for p in imgs:
                os.unlink(p)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_images_to_pdf_a4(self):
        from PIL import Image
        from engines.pdf_convert import images_to_pdf
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            in_path = f.name
            Image.new('RGB', (3000, 2000), 'green').save(f)
        out_path = tempfile.mktemp(suffix='.pdf')
        try:
            result = images_to_pdf([in_path], out_path, page_size='a4')
            assert os.path.isfile(result)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_images_to_pdf_empty_list(self):
        from engines.pdf_convert import images_to_pdf
        with pytest.raises(ValueError):
            images_to_pdf([], '/tmp/out.pdf')

    def test_pdf_to_images_no_poppler(self):
        from engines.pdf_convert import pdf_to_images, _PDF2IMAGE_AVAILABLE
        if not _PDF2IMAGE_AVAILABLE:
            # 创建临时文件避免 FileNotFoundError 先于 RuntimeError
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                tmp = f.name
            try:
                with pytest.raises(RuntimeError, match='poppler'):
                    pdf_to_images(tmp, '/tmp/out')
            finally:
                os.unlink(tmp)


class TestToolPanel:
    """工具面板测试。"""

    def test_tool_keys(self):
        from widgets import TOOL_KEYS, TOOL_BY_KEY
        assert len(TOOL_KEYS) == 17
        # 原有 5 个
        assert 'export_cmd' in TOOL_KEYS
        assert 'embed_subtitle' in TOOL_KEYS
        assert 'extract_subtitle' in TOOL_KEYS
        assert 'merge_media' in TOOL_KEYS
        assert 'crop_video' in TOOL_KEYS
        # 新增视频工具
        assert 'extract_audio' in TOOL_KEYS
        assert 'trim_media' in TOOL_KEYS
        assert 'compress_video' in TOOL_KEYS
        assert 'video_to_gif' in TOOL_KEYS
        assert 'media_info' in TOOL_KEYS
        # 图片工具
        assert 'compress_image' in TOOL_KEYS
        assert 'resize_image' in TOOL_KEYS
        assert 'add_watermark' in TOOL_KEYS
        # 文档工具
        assert 'merge_pdfs' in TOOL_KEYS
        assert 'split_pdf' in TOOL_KEYS
        assert 'pdf_to_images' in TOOL_KEYS
        assert 'images_to_pdf' in TOOL_KEYS

    def test_tool_by_key(self):
        from widgets import TOOL_BY_KEY
        # TOOL_BY_KEY[key] = (key, display_name, cat, file_filter, output_ext)
        assert TOOL_BY_KEY['export_cmd'][1] == '导出 FFmpeg 命令'
        assert TOOL_BY_KEY['crop_video'][1] == '画面裁剪'

    def test_category_keys_has_tools(self):
        from formats import CATEGORY_KEYS
        assert 'tools' in CATEGORY_KEYS


class TestFFmpegUtilsImports:
    """ffmpeg_utils 引擎导入测试。"""

    def test_export_ffmpeg_cmd(self):
        from engines.ffmpeg_utils import export_ffmpeg_cmd
        assert callable(export_ffmpeg_cmd)

    def test_embed_subtitle(self):
        from engines.ffmpeg_utils import embed_subtitle
        assert callable(embed_subtitle)

    def test_extract_subtitle(self):
        from engines.ffmpeg_utils import extract_subtitle
        assert callable(extract_subtitle)

    def test_merge_media(self):
        from engines.ffmpeg_utils import merge_media
        assert callable(merge_media)

    def test_crop_video(self):
        from engines.ffmpeg_utils import crop_video
        assert callable(crop_video)

    def test_merge_media_needs_two_files(self):
        from engines.ffmpeg_utils import merge_media
        with pytest.raises(ValueError, match='至少需要 2 个文件'):
            merge_media(['/tmp/only_one.mp4'], '/tmp/out.mp4')

    def test_crop_video_invalid_size(self):
        from engines.ffmpeg_utils import crop_video
        # 文件不存在会先报 FileNotFoundError
        with pytest.raises(FileNotFoundError):
            crop_video('/tmp/in.mp4', '/tmp/out.mp4', width=0, height=100)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
