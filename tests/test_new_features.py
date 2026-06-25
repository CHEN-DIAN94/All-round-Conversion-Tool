"""
tests/test_video_compress.py — 视频压缩引擎测试
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
            with pytest.raises(RuntimeError, match='poppler'):
                pdf_to_images('/tmp/test.pdf', '/tmp/out')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
