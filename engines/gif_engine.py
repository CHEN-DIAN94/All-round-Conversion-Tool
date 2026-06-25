"""
engines.gif_engine — 视频转 GIF 优化引擎

专门针对 GIF 的优化参数：帧率、尺寸、颜色数、循环次数。
比通用 ffmpeg 转换质量更高、文件更小。
"""


__all__ = ['convert_video_to_gif']

import os
from typing import Callable, Optional
import threading

from utils import get_ffmpeg_path
from engines._common import _prepare_output
from engines.ffmpeg_core import _run_ffmpeg_convert


def convert_video_to_gif(
    input_path: str,
    output_path: str,
    fps: int = 12,
    width: int = 480,
    colors: int = 256,
    loop: int = 0,
    start_time: str = '',
    end_time: str = '',
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    视频转 GIF（高质量两步法）。

    两步法：先生成调色板，再用调色板生成 GIF。
    比单步转换颜色更准确、文件更小。

    Args:
        input_path: 输入视频路径
        output_path: 输出 GIF 路径
        fps: 帧率（默认 12，社交媒体推荐 10-15）
        width: 输出宽度（高度自动等比缩放，-2 保证偶数）
        colors: 颜色数（1-256，默认 256）
        loop: 循环次数（0=无限循环）
        start_time: 起始时间（如 "00:00:05"）
        end_time: 结束时间（如 "00:00:10"）
        progress_callback: 进度回调
        cancel_event: 取消事件
        proc_ref: 进程引用列表

    Returns:
        输出文件路径
    """
    ffmpeg = get_ffmpeg_path()
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))
    palette_path = temp_path.replace('.~tmp.gif', '.~palette.png')

    # 构建 vf 滤镜
    vf_parts = [f'fps={fps}', f'scale={width}:-2:flags=lanczos']
    if colors < 256:
        vf_parts.append(f'palettegen=max_colors={colors}')
    else:
        vf_parts.append('palettegen')

    try:
        # Step 1: 生成调色板
        cmd_palette = [ffmpeg, '-y', '-i', input_path]
        if start_time:
            cmd_palette = ['-ss', start_time] + cmd_palette[1:]
        if end_time:
            cmd_palette += ['-to', end_time]
        cmd_palette += ['-vf', ','.join(vf_parts), palette_path]

        from utils import run_subprocess
        result = run_subprocess(cmd_palette, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f'调色板生成失败: {result.stderr[-200:]}')

        # Step 2: 用调色板生成 GIF
        vf_gif = f'fps={fps},scale={width}:-2:flags=lanczos'
        if colors < 256:
            vf_gif += f'[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3'
        else:
            vf_gif += '[x];[x][1:v]paletteuse=dither=sierra2_4a'

        cmd_gif = [ffmpeg, '-y', '-i', input_path, '-i', palette_path]
        if start_time:
            cmd_gif = ['-ss', start_time] + cmd_gif[1:]
        if end_time:
            cmd_gif += ['-to', end_time]
        cmd_gif += [
            '-lavfi', vf_gif,
            '-loop', str(loop),
            temp_path,
        ]

        return _run_ffmpeg_convert(
            cmd_gif, temp_path, output_path,
            proc_ref=proc_ref,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            error_prefix='GIF',
        )

    finally:
        # 清理调色板临时文件
        try:
            if os.path.exists(palette_path):
                os.remove(palette_path)
        except OSError:
            pass
