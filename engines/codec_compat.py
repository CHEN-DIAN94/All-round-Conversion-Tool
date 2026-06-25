"""
engines.codec_compat — 编解码器兼容性矩阵

集中管理容器格式与音视频编码的兼容性规则，
替代原 ffmpeg_core.py 中的硬编码判断。
"""


__all__ = ['ContainerSpec', 'is_container_copy_possible', 'get_incompatible_reason']

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ContainerSpec:
    """容器格式规范"""
    video_codecs: frozenset  # 支持的视频编码，空集=支持所有
    audio_codecs: frozenset  # 支持的音频编码，空集=支持所有


# 容器格式兼容性矩阵
CONTAINER_SPECS: Dict[str, ContainerSpec] = {
    '.mp4': ContainerSpec(
        video_codecs=frozenset({'h264', 'hevc', 'h265', 'vp9', 'av1', 'mpeg4'}),
        audio_codecs=frozenset({'aac', 'mp3', 'ac3', 'eac3', 'opus', 'vorbis', 'flac', 'alac'}),
    ),
    '.mkv': ContainerSpec(
        video_codecs=frozenset(),  # 空集=支持所有
        audio_codecs=frozenset(),
    ),
    '.avi': ContainerSpec(
        video_codecs=frozenset({'mpeg4', 'divx', 'h264', 'mpeg2video'}),
        audio_codecs=frozenset({'mp3', 'pcm_s16le', 'aac', 'ac3'}),
    ),
    '.mov': ContainerSpec(
        video_codecs=frozenset({'h264', 'hevc', 'h265', 'prores', 'mpeg4'}),
        audio_codecs=frozenset({'aac', 'alac', 'pcm_s16le', 'pcm_s24le', 'mp3'}),
    ),
    '.webm': ContainerSpec(
        video_codecs=frozenset({'vp8', 'vp9', 'av1'}),
        audio_codecs=frozenset({'opus', 'vorbis'}),
    ),
    '.flv': ContainerSpec(
        video_codecs=frozenset({'h264', 'flv1'}),
        audio_codecs=frozenset({'aac', 'mp3', 'nellymoser', 'speex'}),
    ),
    '.ts': ContainerSpec(
        video_codecs=frozenset({'h264', 'hevc', 'h265', 'mpeg2video'}),
        audio_codecs=frozenset({'aac', 'mp3', 'ac3', 'eac3'}),
    ),
    '.m4v': ContainerSpec(
        video_codecs=frozenset({'h264', 'hevc', 'h265', 'mpeg4'}),
        audio_codecs=frozenset({'aac', 'alac', 'mp3'}),
    ),
}


def is_container_copy_possible(
    video_codec: str,
    audio_codec: str,
    output_ext: str,
) -> bool:
    """
    判断是否可以仅转容器（不重编码）。

    Args:
        video_codec: 视频编码名（小写），如 'h264'
        audio_codec: 音频编码名（小写），如 'aac'
        output_ext:  输出容器扩展名（含点），如 '.mp4'

    Returns:
        True 表示视频和音频都兼容目标容器，可以 -c copy 直通。
    """
    spec = CONTAINER_SPECS.get(output_ext.lower())
    if spec is None:
        return False

    # 空集 = 支持所有编码
    video_ok = not spec.video_codecs or video_codec in spec.video_codecs
    audio_ok = not spec.audio_codecs or audio_codec in spec.audio_codecs

    return video_ok and audio_ok


def get_incompatible_reason(
    video_codec: str,
    audio_codec: str,
    output_ext: str,
) -> Optional[str]:
    """
    获取不兼容原因（用于用户提示）。

    Returns:
        不兼容原因字符串，兼容则返回 None。
    """
    spec = CONTAINER_SPECS.get(output_ext.lower())
    if spec is None:
        return f'不支持的容器格式: {output_ext}'

    if spec.video_codecs and video_codec not in spec.video_codecs:
        return f'视频编码 {video_codec} 不被 {output_ext} 宯器支持'

    if spec.audio_codecs and audio_codec not in spec.audio_codecs:
        return f'音频编码 {audio_codec} 不被 {output_ext} 容器支持，需重编码'

    return None
