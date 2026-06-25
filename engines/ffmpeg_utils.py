"""
engines.ffmpeg_utils — FFmpeg 高级工具

- export_ffmpeg_cmd: 导出 ffmpeg 命令（不执行）
- embed_subtitle: 嵌入字幕到视频
- extract_subtitle: 从视频提取字幕
- merge_media: 合并多个音视频文件
- crop_video: 裁剪视频画面
"""

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional
import threading

from utils import (
    get_ffmpeg_path, get_ffprobe_path, finalize_file,
    run_subprocess, run_subprocess_popen, kill_process_tree,
    CREATE_NO_WINDOW,
)
from engines._common import _prepare_output, _check_disk_space
from engines.ffmpeg_core import (
    FFmpegMonitor, _select_video_codecs, _select_audio_codec,
    _get_available_encoders, _is_container_only,
)

__all__ = [
    'export_ffmpeg_cmd', 'embed_subtitle', 'extract_subtitle',
    'merge_media', 'crop_video',
]


def export_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    conv_type: str = 'video',
    params: dict = None,
) -> str:
    """
    生成 ffmpeg 命令字符串（不执行）。

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        conv_type: 转换类型 (video/audio)
        params: 高级设置参数

    Returns:
        ffmpeg 命令字符串
    """
    ffmpeg = get_ffmpeg_path()
    params = params or {}
    input_ext = Path(input_path).suffix.lower()
    output_ext = Path(output_path).suffix.lower()

    if conv_type == 'audio':
        encoder, extra_args = _select_audio_codec(ffmpeg, output_ext, params)
        cmd = [ffmpeg, '-y', '-i', input_path, '-vn', '-c:a', encoder] + extra_args + ['-map_metadata', '0', output_path]
    else:
        container_only = _is_container_only(input_ext, output_ext, input_path)
        if container_only:
            cmd = [ffmpeg, '-y', '-i', input_path, '-c', 'copy', '-map_metadata', '0', output_path]
        else:
            v_args, a_args = _select_video_codecs(ffmpeg, output_ext, params)
            cmd = [ffmpeg, '-y', '-i', input_path] + v_args + a_args + ['-map_metadata', '0', output_path]

    return ' '.join(cmd)


def embed_subtitle(
    input_path: str,
    output_path: str,
    subtitle_path: str,
    language: str = 'chi',
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    嵌入字幕到视频。

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        subtitle_path: 字幕文件路径 (.srt/.ass/.ssa)
        language: 字幕语言代码 (chi/eng/jpn 等)
        progress_callback: 进度回调
        cancel_event: 取消事件
        proc_ref: 进程引用

    Returns:
        输出文件路径
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')
    if not os.path.isfile(subtitle_path):
        raise FileNotFoundError(f'字幕文件不存在: {subtitle_path}')

    ffmpeg = get_ffmpeg_path()
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))

    # 判断是否纯封装转换（视频不重编码）
    sub_ext = Path(subtitle_path).suffix.lower()
    if sub_ext in ('.srt', '.ass', '.ssa'):
        # 软字幕：视频不重编码
        cmd = [
            ffmpeg, '-y',
            '-i', input_path,
            '-i', subtitle_path,
            '-c', 'copy',
            '-c:s', 'mov_text' if Path(output_path).suffix.lower() in ('.mp4', '.m4v') else 'srt',
            '-map', '0', '-map', '1',
            '-metadata:s:s:0', f'language={language}',
            temp_path,
        ]
    else:
        raise ValueError(f'不支持的字幕格式: {sub_ext}（支持 .srt/.ass/.ssa）')

    return _run_ffmpeg_utils(cmd, temp_path, output_path, '字幕嵌入', proc_ref, progress_callback, cancel_event)


def extract_subtitle(
    input_path: str,
    output_path: str,
    stream_index: int = 0,
) -> str:
    """
    从视频提取字幕。

    Args:
        input_path: 输入视频路径
        output_path: 输出字幕路径 (.srt)
        stream_index: 字幕流索引（默认第一个）

    Returns:
        输出文件路径
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')

    ffmpeg = get_ffmpeg_path()
    ensure_output_dir = __import__('utils', fromlist=['ensure_output_dir']).ensure_output_dir
    ensure_output_dir(output_path)

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-map', f'0:s:{stream_index}',
        '-c:s', 'srt',
        output_path,
    ]

    result = run_subprocess(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f'字幕提取失败: {result.stderr[-200:]}')

    if not os.path.isfile(output_path):
        raise RuntimeError('字幕提取失败：未生成输出文件（视频可能不含字幕流）')

    return output_path


def merge_media(
    input_paths: list[str],
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    合并多个音视频文件（concat 协议）。

    要求所有输入文件格式/编码一致。
    如果格式不一致，会先转码再合并。

    Args:
        input_paths: 输入文件路径列表（按顺序合并）
        output_path: 输出文件路径
        progress_callback: 进度回调
        cancel_event: 取消事件
        proc_ref: 进程引用

    Returns:
        输出文件路径
    """
    if len(input_paths) < 2:
        raise ValueError('至少需要 2 个文件才能合并')

    for p in input_paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(f'文件不存在: {p}')

    ffmpeg = get_ffmpeg_path()
    temp_path = _prepare_output(output_path, min_free_mb=200)

    # 创建 concat 文件列表
    concat_file = temp_path.replace('.~tmp', '.~concat')
    try:
        with open(concat_file, 'w', encoding='utf-8') as f:
            for p in input_paths:
                # concat 协议需要转义单引号
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            ffmpeg, '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',
            '-map_metadata', '0',
            temp_path,
        ]

        return _run_ffmpeg_utils(cmd, temp_path, output_path, '合并', proc_ref, progress_callback, cancel_event)

    finally:
        try:
            if os.path.exists(concat_file):
                os.remove(concat_file)
        except OSError:
            pass


def crop_video(
    input_path: str,
    output_path: str,
    width: int,
    height: int,
    x: int = 0,
    y: int = 0,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    裁剪视频画面。

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        width: 裁剪后宽度
        height: 裁剪后高度
        x: 裁剪起始 X 坐标（默认 0）
        y: 裁剪起始 Y 坐标（默认 0）
        progress_callback: 进度回调
        cancel_event: 取消事件
        proc_ref: 进程引用

    Returns:
        输出文件路径
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'输入文件不存在: {input_path}')
    if width <= 0 or height <= 0:
        raise ValueError(f'裁剪尺寸必须为正数: {width}x{height}')

    ffmpeg = get_ffmpeg_path()
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))

    encoders = _get_available_encoders(ffmpeg)
    from engines.ffmpeg_core import _select_h264_encoder
    venc = _select_h264_encoder(encoders)

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-vf', f'crop={width}:{height}:{x}:{y}',
        '-c:v', venc,
        '-c:a', 'copy',
        '-map_metadata', '0',
        temp_path,
    ]

    if venc == 'libx264':
        cmd.insert(cmd.index('-c:a'), '-pix_fmt')
        cmd.insert(cmd.index('-c:a'), 'yuv420p')

    return _run_ffmpeg_utils(cmd, temp_path, output_path, '画面裁剪', proc_ref, progress_callback, cancel_event)


def _run_ffmpeg_utils(cmd, temp_path, output_path, error_prefix, proc_ref, progress_callback, cancel_event):
    """执行 ffmpeg 命令的公共逻辑。"""
    _check_disk_space(output_path)
    proc = run_subprocess_popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc_ref is not None:
        proc_ref.append(proc)

    monitor = FFmpegMonitor(proc, progress_callback, cancel_event)
    stderr = monitor.run()

    if proc.returncode != 0:
        from engines.ffmpeg_core import _extract_ffmpeg_error
        error_msg = _extract_ffmpeg_error(stderr)
        raise RuntimeError(f'{error_prefix}失败 (code={proc.returncode}): {error_msg}')

    if not os.path.isfile(temp_path):
        raise RuntimeError(f'{error_prefix}失败：未生成输出文件')

    finalize_file(temp_path, output_path)
    return output_path


def ensure_output_dir(path: str):
    """确保输出目录存在。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
