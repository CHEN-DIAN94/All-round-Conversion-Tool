"""
tests.test_media_utils — 媒体工具函数测试

覆盖：
- get_media_info 参数验证（需 ffprobe）
- extract_audio / trim_media 参数签名验证
- 函数可导入性
- get_media_info 对不存在文件的优雅处理
"""

import os
import shutil
import sys
import threading

import pytest

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.ffmpeg_core import extract_audio, trim_media, get_media_info


class TestFunctionImports:
    """函数可导入性测试"""

    def test_extract_audio_importable(self):
        """extract_audio 应可从 engines 包导入"""
        from engines import extract_audio as ea
        assert callable(ea)

    def test_trim_media_importable(self):
        """trim_media 应可从 engines 包导入"""
        from engines import trim_media as tm
        assert callable(tm)

    def test_get_media_info_importable(self):
        """get_media_info 应可从 engines 包导入"""
        from engines import get_media_info as gmi
        assert callable(gmi)


class TestGetMediaInfo:
    """get_media_info 测试"""

    def test_nonexistent_file(self):
        """不存在的文件应返回带默认值的 dict，不抛异常"""
        result = get_media_info('Z:\\nonexistent\\fake_video.mp4')
        assert isinstance(result, dict)
        assert result['duration'] == 0.0
        assert result['video_codec'] == ''
        assert result['audio_codec'] == ''

    def test_result_structure(self):
        """返回字典应包含所有必要的键"""
        result = get_media_info('Z:\\nonexistent\\fake.mp4')
        expected_keys = {
            'duration', 'video_codec', 'audio_codec',
            'width', 'height', 'video_bitrate', 'audio_bitrate',
            'file_size', 'format_name', 'frame_rate', 'sample_rate',
        }
        assert expected_keys == set(result.keys())

    def test_invalid_file_format(self, tmp_path):
        """无效文件应返回默认值，不抛异常"""
        bad_file = tmp_path / 'bad.mp4'
        bad_file.write_bytes(b'not a real video file')
        result = get_media_info(str(bad_file))
        assert isinstance(result, dict)
        # ffprobe 应该失败，返回默认值
        assert result['video_codec'] == ''

    @pytest.mark.skipif(
        not os.path.isfile(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'bin', 'ffmpeg.exe'
        )) and not shutil.which('ffmpeg'),
        reason='ffmpeg not available'
    )
    def test_with_real_video(self, tmp_path):
        """使用 ffmpeg 生成的测试视频验证 get_media_info"""
        import subprocess
        ffmpeg = 'ffmpeg'
        # 尝试使用项目 bin 目录的 ffmpeg
        bin_ffmpeg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'bin', 'ffmpeg.exe'
        )
        if os.path.isfile(bin_ffmpeg):
            ffmpeg = bin_ffmpeg

        test_video = tmp_path / 'test.mp4'
        subprocess.run(
            [ffmpeg, '-y', '-f', 'lavfi', '-i',
             'testsrc=duration=1:size=320x240:rate=25',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
             '-c:v', 'libx264', '-c:a', 'aac', str(test_video)],
            capture_output=True, timeout=30,
        )

        if not test_video.exists():
            pytest.skip('ffmpeg could not create test video')

        result = get_media_info(str(test_video))
        assert result['duration'] > 0
        assert result['video_codec'] != ''
        assert result['width'] == 320
        assert result['height'] == 240
        assert result['file_size'] > 0


class TestExtractAudioSignature:
    """extract_audio 函数签名和参数测试"""

    def test_signature_has_format_param(self):
        """函数应接受 format 参数"""
        import inspect
        sig = inspect.signature(extract_audio)
        assert 'format' in sig.parameters

    def test_default_format_is_mp3(self):
        """format 默认值应为 mp3"""
        import inspect
        sig = inspect.signature(extract_audio)
        assert sig.parameters['format'].default == 'mp3'

    def test_supports_progress_callback(self):
        """函数应接受 progress_callback 参数"""
        import inspect
        sig = inspect.signature(extract_audio)
        assert 'progress_callback' in sig.parameters

    def test_supports_cancel_event(self):
        """函数应接受 cancel_event 参数"""
        import inspect
        sig = inspect.signature(extract_audio)
        assert 'cancel_event' in sig.parameters

    def test_nonexistent_file_raises(self):
        """不存在的文件应抛出异常"""
        with pytest.raises(Exception):
            extract_audio('Z:\\nonexistent\\fake.mp4', '/tmp/out.mp3')


class TestTrimMediaSignature:
    """trim_media 函数签名和参数测试"""

    def test_signature_has_time_params(self):
        """函数应接受 start_time 和 end_time 参数"""
        import inspect
        sig = inspect.signature(trim_media)
        assert 'start_time' in sig.parameters
        assert 'end_time' in sig.parameters

    def test_supports_progress_callback(self):
        """函数应接受 progress_callback 参数"""
        import inspect
        sig = inspect.signature(trim_media)
        assert 'progress_callback' in sig.parameters

    def test_supports_cancel_event(self):
        """函数应接受 cancel_event 参数"""
        import inspect
        sig = inspect.signature(trim_media)
        assert 'cancel_event' in sig.parameters

    def test_nonexistent_file_raises(self):
        """不存在的文件应抛出异常"""
        with pytest.raises(Exception):
            trim_media('Z:\\nonexistent\\fake.mp4', '/tmp/out.mp4', '0', '10')


class TestGetMediaInfoSignature:
    """get_media_info 函数签名测试"""

    def test_returns_dict(self):
        """函数应返回 dict"""
        result = get_media_info('Z:\\nonexistent\\fake.mp4')
        assert isinstance(result, dict)

    def test_takes_single_path_arg(self):
        """函数应只接受一个路径参数"""
        import inspect
        sig = inspect.signature(get_media_info)
        params = list(sig.parameters.keys())
        assert len(params) == 1
        assert params[0] == 'input_path'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
