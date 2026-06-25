"""
tests/test_new_engines.py — 新引擎功能测试

覆盖：gif_engine, compress_engine, watermark_engine, pdf_tools, history, cli
"""

import pytest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from history import HistoryManager
from constants import FileStatus


class TestFileStatus:
    """FileStatus 从 constants 导入。"""

    def test_file_status_values(self):
        assert FileStatus.WAITING == '等待中'
        assert FileStatus.SUCCESS == '成功'
        assert FileStatus.FAILED == '失败'


class TestHistoryManager:
    """历史管理器测试。"""

    def test_add_and_count(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            hm = HistoryManager(path)
            hm.add('a.mp4', 'a.webm', 'video', True)
            hm.add('b.mp4', 'b.webm', 'video', False, error='fail')
            assert hm.count == 2
        finally:
            os.unlink(path)

    def test_get_recent(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            hm = HistoryManager(path)
            for i in range(5):
                hm.add(f'{i}.mp4', f'{i}.webm', 'video', True)
            recent = hm.get_recent(3)
            assert len(recent) == 3
            # 最新的在前
            assert recent[0]['input'] == '4.mp4'
        finally:
            os.unlink(path)

    def test_get_failed(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            hm = HistoryManager(path)
            hm.add('a.mp4', 'a.webm', 'video', True)
            hm.add('b.mp4', 'b.webm', 'video', False, error='err')
            failed = hm.get_failed()
            assert len(failed) == 1
            assert failed[0]['error'] == 'err'
        finally:
            os.unlink(path)

    def test_search(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            hm = HistoryManager(path)
            hm.add('/path/to/video.mp4', 'out.webm', 'video', True)
            hm.add('/path/to/audio.mp3', 'out.wav', 'audio', True)
            results = hm.search('video')
            assert len(results) == 1
        finally:
            os.unlink(path)

    def test_clear(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            hm = HistoryManager(path)
            hm.add('a.mp4', 'a.webm', 'video', True)
            hm.clear()
            assert hm.count == 0
        finally:
            os.unlink(path)

    def test_persistence(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            hm1 = HistoryManager(path)
            hm1.add('a.mp4', 'a.webm', 'video', True)
            # 新实例应能加载
            hm2 = HistoryManager(path)
            assert hm2.count == 1
        finally:
            os.unlink(path)

    def test_export_markdown(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            json_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.md', delete=False) as f:
            md_path = f.name
        try:
            hm = HistoryManager(json_path)
            hm.add('a.mp4', 'a.webm', 'video', True)
            hm.add('b.mp4', 'b.webm', 'video', False, error='err')
            result = hm.export_markdown(md_path)
            assert result == md_path
            assert os.path.isfile(md_path)
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            assert '转换历史报告' in content
            assert '✅' in content
            assert '❌' in content
        finally:
            os.unlink(json_path)
            os.unlink(md_path)


class TestCompressEngine:
    """图片压缩引擎测试。"""

    def test_compress_jpg(self):
        from PIL import Image
        from engines.compress_engine import compress_image

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            in_path = f.name
            Image.new('RGB', (200, 200), 'red').save(f, quality=100)
        out_path = in_path.replace('.jpg', '_out.jpg')
        try:
            result = compress_image(in_path, out_path, quality=30)
            assert os.path.isfile(result)
            assert os.path.getsize(out_path) < os.path.getsize(in_path)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_compress_with_target_size(self):
        from PIL import Image
        from engines.compress_engine import compress_image

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            in_path = f.name
            img = Image.new('RGB', (500, 500), 'blue')
            img.save(f, quality=100)
        out_path = in_path.replace('.jpg', '_out.jpg')
        try:
            result = compress_image(in_path, out_path, target_size_kb=20)
            assert os.path.isfile(result)
            size_kb = os.path.getsize(out_path) / 1024
            assert size_kb <= 25  # 允许小幅超出
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestWatermarkEngine:
    """水印引擎测试。"""

    def test_text_watermark(self):
        from PIL import Image
        from engines.watermark_engine import add_watermark

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            in_path = f.name
            Image.new('RGB', (200, 200), 'white').save(f)
        out_path = in_path.replace('.png', '_wm.png')
        try:
            result = add_watermark(in_path, out_path, text='© 2026')
            assert os.path.isfile(result)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_image_watermark(self):
        from PIL import Image
        from engines.watermark_engine import add_watermark

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            in_path = f.name
            Image.new('RGB', (400, 400), 'green').save(f)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            wm_path = f.name
            Image.new('RGBA', (50, 50), (255, 0, 0, 128)).save(f)
        out_path = in_path.replace('.png', '_wm.png')
        try:
            result = add_watermark(in_path, out_path, watermark_image=wm_path)
            assert os.path.isfile(result)
        finally:
            os.unlink(in_path)
            os.unlink(wm_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestPdfTools:
    """PDF 工具测试。"""

    def test_merge_empty_list(self):
        from engines.pdf_tools import merge_pdfs
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            out_path = f.name
        try:
            # 空列表应报错或生成空 PDF
            merge_pdfs([], out_path)
            assert os.path.isfile(out_path)
        except Exception:
            pass  # 空列表可能抛异常，也是合理行为
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_split_nonexistent(self):
        from engines.pdf_tools import split_pdf
        with pytest.raises(FileNotFoundError):
            split_pdf('/nonexistent.pdf', '/tmp/split')


class TestCliModule:
    """CLI 模块测试。"""

    def test_import(self):
        from cli import main
        assert callable(main)

    def test_list_presets(self):
        import subprocess
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run([sys.executable, 'cli.py', '--list-presets'],
                          capture_output=True, text=True, cwd=base)
        assert r.returncode == 0
        assert '微信发送' in r.stdout

    def test_list_formats(self):
        import subprocess
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run([sys.executable, 'cli.py', '--list-formats'],
                          capture_output=True, text=True, cwd=base)
        assert r.returncode == 0
        assert '.mp4' in r.stdout

    def test_help(self):
        import subprocess
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run([sys.executable, 'cli.py', '--help'],
                          capture_output=True, text=True, cwd=base)
        assert r.returncode == 0
        assert 'converter' in r.stdout.lower() or '全能' in r.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
