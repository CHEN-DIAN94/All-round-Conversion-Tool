"""
engines.video_compress — 视频压缩引擎

不改变格式，通过调整 CRF/分辨率/编码参数减小文件大小。
支持目标文件大小模式。
"""

import os
import subprocess
from typing import Callable, Optional
import threading

from utils import get_ffmpeg_path, get_ffprobe_path, finalize_file, run_subprocess, run_subprocess_popen
from engines._common import _prepare_output, _check_disk_space
from engines.ffmpeg_core import FFmpegMonitor, _select_h264_encoder, _get_available_encoders

__all__ = ['compress_video']



def compress_video(
    input_path: str,
    output_path: str,
    target_size_mb: float = 0,
    crf: int = 28,
    scale_width: int = 0,
    preset: str = 'fast',
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    压缩视频文件。

    两种模式：
    1. 固定质量：用指定 CRF 值压缩
    2. 目标大小：根据目标大小自动计算 bitrate

    Args:
        input_path: 输入视频路径
        output_path: 输出路径
        target_size_mb: 目标文件大小（MB），0=固定质量模式
        crf: CRF 值（0-51，越大压缩越狠，默认 28）
        scale_width: 缩放宽度（0=不缩放，如 1280, 720）
        preset: 编码预设（ultrafast~veryslow，默认 fast）
        progress_callback: 进度回调
        cancel_event: 取消事件
        proc_ref: 进程引用

    Returns:
        输出文件路径
    """
    ffmpeg = get_ffmpeg_path()
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb), 100))

    if target_size_mb > 0:
        # 目标大小模式：计算 bitrate
        duration = _get_duration(input_path)
        if duration <= 0:
            raise RuntimeError('无法获取视频时长，使用固定质量模式')
        target_bitrate = int(target_size_mb * 8 * 1024 / duration)  # kbps
        cmd = _build_compress_cmd(
            ffmpeg, input_path, temp_path,
            bitrate=target_bitrate, scale_width=scale_width, preset=preset,
        )
    else:
        # 固定质量模式
        cmd = _build_compress_cmd(
            ffmpeg, input_path, temp_path,
            crf=crf, scale_width=scale_width, preset=preset,
        )

    return _run_compress(cmd, temp_path, output_path, proc_ref, progress_callback, cancel_event)


def _build_compress_cmd(
    ffmpeg: str, input_path: str, output_path: str,
    crf: int = 28, bitrate: int = 0, scale_width: int = 0, preset: str = 'fast',
) -> list:
    """构建压缩命令。"""
    encoders = _get_available_encoders(ffmpeg)
    venc = _select_h264_encoder(encoders)

    cmd = [ffmpeg, '-y', '-i', input_path]

    # 视频滤镜
    vf_parts = []
    if scale_width > 0:
        vf_parts.append(f'scale={scale_width}:-2')
    if vf_parts:
        cmd += ['-vf', ','.join(vf_parts)]

    # 编码参数
    if venc == 'libx264':
        if bitrate > 0:
            cmd += ['-c:v', venc, '-preset', preset, '-b:v', f'{bitrate}k',
                    '-maxrate', f'{int(bitrate*1.5)}k', '-bufsize', f'{bitrate*2}k']
        else:
            cmd += ['-c:v', venc, '-preset', preset, '-crf', str(crf)]
    else:
        # 硬件编码器
        if bitrate > 0:
            cmd += ['-c:v', venc, '-b:v', f'{bitrate}k']
        else:
            cmd += ['-c:v', venc, '-crf', str(crf)]

    cmd += ['-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path]
    return cmd


def _get_duration(input_path: str) -> float:
    """获取视频时长（秒）。"""
    ffprobe = get_ffprobe_path()
    try:
        result = run_subprocess(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', input_path],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0


def _run_compress(cmd, temp_path, output_path, proc_ref, progress_callback, cancel_event):
    """执行压缩命令。"""
    _check_disk_space(output_path)
    proc = run_subprocess_popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc_ref is not None:
        proc_ref.append(proc)

    monitor = FFmpegMonitor(proc, progress_callback, cancel_event)
    stderr = monitor.run()

    if proc.returncode != 0:
        raise RuntimeError(f'视频压缩失败: {stderr[-300:]}')

    if not os.path.isfile(temp_path):
        raise RuntimeError(f'压缩后未生成输出文件')

    # 显示压缩效果
    input_size = os.path.getsize(cmd[cmd.index('-i') + 1])
    finalize_file(temp_path, output_path)
    output_size = os.path.getsize(output_path)
    ratio = (1 - output_size / input_size) * 100 if input_size > 0 else 0

    return output_path
