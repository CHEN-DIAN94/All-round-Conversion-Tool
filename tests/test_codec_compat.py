"""
tests.test_codec_compat — 编解码器兼容性矩阵测试

覆盖：
- MP4/MKV/AVI/MOV/WEBM 容器的视频音频兼容性
- is_container_copy_possible 边界情况
- get_incompatible_reason 错误提示
"""

import pytest
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.codec_compat import is_container_copy_possible, get_incompatible_reason


class TestMp4Compatibility:
    """MP4 容器兼容性测试"""

    def test_h264_aac_compatible(self):
        """H.264 + AAC 可以直接复制到 MP4"""
        assert is_container_copy_possible('h264', 'aac', '.mp4') is True

    def test_h264_dts_incompatible(self):
        """H.264 + DTS 不能直接复制到 MP4"""
        assert is_container_copy_possible('h264', 'dts', '.mp4') is False

    def test_hevc_mp3_compatible(self):
        """HEVC + MP3 可以直接复制到 MP4"""
        assert is_container_copy_possible('hevc', 'mp3', '.mp4') is True

    def test_vp9_opus_compatible(self):
        """VP9 + Opus 可以直接复制到 MP4"""
        assert is_container_copy_possible('vp9', 'opus', '.mp4') is True

    def test_pcm_incompatible(self):
        """PCM 编码不能直接复制到 MP4"""
        assert is_container_copy_possible('h264', 'pcm_s16le', '.mp4') is False


class TestMkvCompatibility:
    """MKV 容器兼容性测试（MKV 支持所有编码）"""

    def test_h264_dts_compatible(self):
        """H.264 + DTS 可以直接复制到 MKV"""
        assert is_container_copy_possible('h264', 'dts', '.mkv') is True

    def test_hevc_truehd_compatible(self):
        """HEVC + TrueHD 可以直接复制到 MKV"""
        assert is_container_copy_possible('hevc', 'truehd', '.mkv') is True

    def test_any_codec_compatible(self):
        """MKV 支持任意编码组合"""
        assert is_container_copy_possible('mpeg4', 'pcm_s16le', '.mkv') is True


class TestAviCompatibility:
    """AVI 容器兼容性测试"""

    def test_mpeg4_mp3_compatible(self):
        """MPEG4 + MP3 可以直接复制到 AVI"""
        assert is_container_copy_possible('mpeg4', 'mp3', '.avi') is True

    def test_h264_aac_compatible(self):
        """H.264 + AAC 可以直接复制到 AVI"""
        assert is_container_copy_possible('h264', 'aac', '.avi') is True

    def test_hevc_incompatible(self):
        """HEVC 不能直接复制到 AVI"""
        assert is_container_copy_possible('hevc', 'mp3', '.avi') is False


class TestWebmCompatibility:
    """WEBM 容器兼容性测试"""

    def test_vp8_opus_compatible(self):
        """VP8 + Opus 可以直接复制到 WEBM"""
        assert is_container_copy_possible('vp8', 'opus', '.webm') is True

    def test_vp9_vorbis_compatible(self):
        """VP9 + Vorbis 可以直接复制到 WEBM"""
        assert is_container_copy_possible('vp9', 'vorbis', '.webm') is True

    def test_h264_incompatible(self):
        """H.264 不能直接复制到 WEBM"""
        assert is_container_copy_possible('h264', 'opus', '.webm') is False


class TestIncompatibleReason:
    """不兼容原因测试"""

    def test_video_incompatible_reason(self):
        """视频不兼容原因"""
        reason = get_incompatible_reason('h264', 'opus', '.webm')
        assert reason is not None
        assert 'h264' in reason
        assert '.webm' in reason

    def test_audio_incompatible_reason(self):
        """音频不兼容原因"""
        reason = get_incompatible_reason('h264', 'dts', '.mp4')
        assert reason is not None
        assert 'dts' in reason
        assert '.mp4' in reason

    def test_compatible_returns_none(self):
        """兼容时返回 None"""
        reason = get_incompatible_reason('h264', 'aac', '.mp4')
        assert reason is None

    def test_unknown_container(self):
        """未知容器返回错误信息"""
        reason = get_incompatible_reason('h264', 'aac', '.xyz')
        assert reason is not None
        assert '不支持' in reason


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
