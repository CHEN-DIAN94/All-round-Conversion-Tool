"""
engines.ffmpeg_core — FFmpeg 视频/音频转换引擎

包含：
- convert_video / convert_audio — 公共转换函数
- FFmpegMonitor — 进度监控类（替换原 _run_ffmpeg_with_monitor 闭包）
- 编码器选择逻辑
"""


__all__ = ['convert_video', 'convert_audio', 'extract_audio', 'trim_media', 'get_media_info']

import os
import re
import sys
import queue
import subprocess
import threading
import json
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from logging_config import get_logger
logger = get_logger(__name__)

from utils import (
    get_ffmpeg_path,
    get_ffprobe_path,
    kill_process_tree,
    run_subprocess,
    run_subprocess_popen,
    finalize_file,
    ensure_output_dir,
    safe_temp_path,
    CREATE_NO_WINDOW,
)

from engines._common import _check_disk_space, _prepare_output


# 缓存 ffmpeg 支持的编码器列表（进程生命周期内只需查询一次）
_encoder_cache: Optional[set] = None
_encoder_cache_lock = threading.Lock()


# ==============================================================
# 公共 API
# ==============================================================

def convert_video(
    input_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
    params: Optional[dict] = None,
) -> str:
    """
    视频格式转换。

    核心策略：
    1. 若仅改变封装格式（容器），优先 -c copy 无损直通
    2. 若需重新编码，依次尝试 h264_nvenc / h264_qsv → libx264
    3. 始终保留原始元数据和色彩信息

    Args:
        params: 高级设置参数，如 video_crf, video_preset, audio_bitrate 等
    """
    params = params or {}
    ffmpeg = get_ffmpeg_path()
    input_ext = Path(input_path).suffix.lower()
    output_ext = Path(output_path).suffix.lower()
    # FIX-11: 动态磁盘阈值 — 输入文件大小的 2 倍，至少 100MB
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))

    # ---------- 步骤 1：检测纯封装转换 ----------
    container_only = _is_container_only(input_ext, output_ext, input_path)

    if container_only:
        cmd = [
            ffmpeg, '-y',
            '-i', input_path,
            '-c', 'copy',           # 无损直通
            '-map_metadata', '0',
            temp_path,
        ]
    else:
        # ---------- 步骤 2：根据输出容器选择编码器（N-09: 应用高级设置） ----------
        v_args, a_args = _select_video_codecs(ffmpeg, output_ext, params)
        cmd = (
            [ffmpeg, '-y', '-i', input_path]
            + v_args
            + a_args
            + ['-map_metadata', '0', temp_path]
        )

    return _run_ffmpeg_convert(
        cmd, temp_path, output_path,
        proc_ref=proc_ref,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        error_prefix='视频',
    )


def convert_audio(
    input_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
    params: Optional[dict] = None,
) -> str:
    """
    音频格式转换。

    始终重新编码以保证兼容性。根据输出容器选择匹配的编码器。

    Args:
        params: 高级设置参数，如 audio_bitrate, audio_sample_rate 等
    """
    params = params or {}
    ffmpeg = get_ffmpeg_path()
    output_ext = Path(output_path).suffix.lower()
    # FIX-11: 动态磁盘阈值
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))

    encoder, extra_args = _select_audio_codec(ffmpeg, output_ext, params)

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-vn',                  # 丢弃视频流（音频转换不需要）
        '-c:a', encoder,
    ] + extra_args + [
        '-map_metadata', '0',
        temp_path,
    ]

    return _run_ffmpeg_convert(
        cmd, temp_path, output_path,
        proc_ref=proc_ref,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        error_prefix='音频',
    )


def extract_audio(
    input_path: str,
    output_path: str,
    format: str = 'mp3',
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    从视频文件中提取音频轨道。

    Args:
        input_path: 输入视频路径
        output_path: 输出音频路径（如 .mp3, .wav, .aac）
        format: 目标音频格式（默认 mp3），覆盖 output_path 的扩展名推断
        progress_callback: 进度回调（0-100）
        cancel_event: 取消事件
        proc_ref: 进程引用列表

    Returns:
        输出文件路径
    """
    ffmpeg = get_ffmpeg_path()
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))

    codec_map = {
        'mp3':  ['-c:a', 'libmp3lame', '-b:a', '192k'],
        'aac':  ['-c:a', 'aac', '-b:a', '192k'],
        'wav':  ['-c:a', 'pcm_s16le'],
        'flac': ['-c:a', 'flac', '-compression_level', '5'],
        'ogg':  ['-c:a', 'libvorbis', '-q:a', '5'],
        'opus': ['-c:a', 'libopus', '-b:a', '128k'],
    }
    a_args = codec_map.get(format, ['-c:a', 'aac', '-b:a', '192k'])

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-vn',
        '-map_metadata', '0',
    ] + a_args + [temp_path]

    return _run_ffmpeg_convert(
        cmd, temp_path, output_path,
        proc_ref=proc_ref,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        error_prefix='音频提取',
    )


def trim_media(
    input_path: str,
    output_path: str,
    start_time: str,
    end_time: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    proc_ref: Optional[list] = None,
) -> str:
    """
    裁剪视频/音频的指定时间段。

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        start_time: 起始时间（格式 'HH:MM:SS' 或秒数 '120'）
        end_time: 结束时间（格式 'HH:MM:SS' 或秒数 '300'）
        progress_callback: 进度回调
        cancel_event: 取消事件
        proc_ref: 进程引用列表

    Returns:
        输出文件路径
    """
    ffmpeg = get_ffmpeg_path()
    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    temp_path = _prepare_output(output_path, min_free_mb=max(int(input_size_mb * 2), 100))

    cmd = [
        ffmpeg, '-y',
        '-ss', str(start_time),
        '-to', str(end_time),
        '-i', input_path,
        '-c', 'copy',
        '-avoid_negative_ts', 'make_zero',
        temp_path,
    ]

    return _run_ffmpeg_convert(
        cmd, temp_path, output_path,
        proc_ref=proc_ref,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        error_prefix='裁剪',
    )


def get_media_info(input_path: str) -> dict:
    """
    通过 ffprobe 获取媒体文件的详细信息。

    Args:
        input_path: 输入文件路径

    Returns:
        dict 包含以下字段：
        - duration: 总时长（秒）
        - video_codec: 视频编码名称
        - audio_codec: 音频编码名称
        - width: 视频宽度（像素）
        - height: 视频高度（像素）
        - video_bitrate: 视频比特率（bps）
        - audio_bitrate: 音频比特率（bps）
        - file_size: 文件大小（字节）
        - format_name: 容器格式名称
        - frame_rate: 帧率
        - sample_rate: 音频采样率
    """
    ffprobe = get_ffprobe_path()
    result = {
        'duration': 0.0,
        'video_codec': '',
        'audio_codec': '',
        'width': 0,
        'height': 0,
        'video_bitrate': 0,
        'audio_bitrate': 0,
        'file_size': 0,
        'format_name': '',
        'frame_rate': '',
        'sample_rate': 0,
    }

    try:
        result['file_size'] = os.path.getsize(input_path)
    except OSError:
        pass

    try:
        probe = run_subprocess(
            [
                ffprobe,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                input_path,
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(probe.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError) as exc:
        logger.warning('ffprobe 探测失败: %s', exc)
        return result

    fmt = data.get('format', {})
    result['duration'] = float(fmt.get('duration', 0))
    result['format_name'] = fmt.get('format_name', '')

    for stream in data.get('streams', []):
        codec_type = stream.get('codec_type', '')
        if codec_type == 'video' and not result['video_codec']:
            result['video_codec'] = stream.get('codec_name', '')
            result['width'] = int(stream.get('width', 0))
            result['height'] = int(stream.get('height', 0))
            result['video_bitrate'] = int(stream.get('bit_rate', 0))
            result['frame_rate'] = stream.get('r_frame_rate', '')
        elif codec_type == 'audio' and not result['audio_codec']:
            result['audio_codec'] = stream.get('codec_name', '')
            result['audio_bitrate'] = int(stream.get('bit_rate', 0))
            result['sample_rate'] = int(stream.get('sample_rate', 0))

    return result


# ==============================================================
# FFmpegMonitor — 进度监控
# ==============================================================

class FFmpegMonitor:
    """
    监控 ffmpeg 进程：读取 stderr、报告进度、处理取消/超时。

    通过两个线程实现：
    - _read_stderr: 持续从 proc.stderr 读行放入队列
    - _process_lines: 从队列取行，解析 Duration/time，报告进度
    """

    MAX_STDERR_LINES = 2000
    _DURATION_RE = re.compile(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)')
    _TIME_RE = re.compile(r'time=(\d+):(\d+):(\d+)\.(\d+)')

    def __init__(
        self,
        proc: subprocess.Popen,
        progress_callback: Optional[Callable[[int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout_seconds: int = 3600,
    ):
        self._proc = proc
        self._progress_callback = progress_callback
        self._cancel_event = cancel_event
        self._timeout = timeout_seconds
        self._total_seconds: Optional[int] = None
        self._stderr_ring = deque(maxlen=self.MAX_STDERR_LINES)
        self._line_queue: queue.Queue = queue.Queue()
        self._reading_done = threading.Event()
        self._sentinel = object()

    def run(self) -> str:
        """启动监控线程，等待完成，返回 stderr 内容。"""
        # 必须先启动 _read_stderr，否则管道写满后 ffmpeg 会阻塞
        stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        stderr_thread.start()

        reader_thread = threading.Thread(target=self._process_lines, daemon=True)
        reader_thread.start()
        reader_thread.join(timeout=self._timeout)

        if reader_thread.is_alive():
            kill_process_tree(self._proc)
            reader_thread.join(timeout=5)
            self._stderr_ring.append(
                f'\n[错误] ffmpeg 超时（超过 {self._timeout} 秒），已强制终止。\n'
            )

        try:
            self._proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self._proc.kill()
            except Exception:
                pass

        # 等待 _process_lines 处理完队列中的剩余行
        if not self._reading_done.is_set():
            self._reading_done.wait(timeout=10)

        # 等待 _read_stderr 退出（进程结束后 readline 返回空，sentinel 入队）
        stderr_thread.join(timeout=5)

        return ''.join(self._stderr_ring)

    def _read_stderr(self) -> None:
        """线程 1：持续从 proc.stderr 读行放入队列。"""
        try:
            while True:
                line = self._proc.stderr.readline()
                if not line:
                    break
                self._line_queue.put(line)
        except (ValueError, OSError):
            pass
        finally:
            self._line_queue.put(self._sentinel)

    def _process_lines(self) -> None:
        """线程 2：从队列取行，解析进度，检查取消。"""
        try:
            while True:
                try:
                    line = self._line_queue.get(timeout=2)
                except queue.Empty:
                    if self._cancel_event and self._cancel_event.is_set():
                        kill_process_tree(self._proc)
                        break
                    continue

                if line is self._sentinel:
                    break

                self._stderr_ring.append(line)

                if self._cancel_event and self._cancel_event.is_set():
                    kill_process_tree(self._proc)
                    break

                self._parse_duration(line)
                self._parse_progress(line)
        except (ValueError, OSError):
            pass
        finally:
            self._reading_done.set()

    def _parse_duration(self, line: str) -> None:
        """从 stderr 行中解析总时长。"""
        if self._total_seconds is not None:
            return
        m = self._DURATION_RE.search(line)
        if m:
            self._total_seconds = (
                int(m.group(1)) * 3600
                + int(m.group(2)) * 60
                + int(m.group(3))
            )

    def _parse_progress(self, line: str) -> None:
        """从 stderr 行中解析当前进度并回调。"""
        m = self._TIME_RE.search(line)
        if m and self._total_seconds and self._progress_callback:
            current = (
                int(m.group(1)) * 3600
                + int(m.group(2)) * 60
                + int(m.group(3))
            )
            if self._total_seconds > 0:
                progress = min(int(current / self._total_seconds * 100), 99)
                self._progress_callback(progress)


# ==============================================================
# 内部辅助函数
# ==============================================================

def _run_ffmpeg_convert(
    cmd: list,
    temp_path: str,
    output_path: str,
    proc_ref: Optional[list] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    error_prefix: str = '',
) -> str:
    """执行 ffmpeg 转换命令的公共逻辑。"""
    _check_disk_space(output_path)
    proc = run_subprocess_popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc_ref is not None:
        proc_ref.append(proc)

    monitor = FFmpegMonitor(proc, progress_callback, cancel_event)
    stderr = monitor.run()

    if proc.returncode != 0:
        error_msg = _extract_ffmpeg_error(stderr)
        raise RuntimeError(f'{error_prefix}转换失败 (code={proc.returncode}): {error_msg}')

    if not os.path.isfile(temp_path):
        raise RuntimeError(
            f'ffmpeg 返回成功但未生成输出文件。'
            f'stderr 末尾: {stderr[-400:].strip()}'
        )
    finalize_file(temp_path, output_path)
    return output_path


def _is_container_only(input_ext: str, output_ext: str, input_path: str = '') -> bool:
    """
    判断是否仅为容器格式转换（无需重新编码）。

    使用 codec_compat 兼容性矩阵检查视频和音频编码，
    只有两者都兼容时才允许 -c copy 直通。
    """
    from engines.codec_compat import is_container_copy_possible

    if input_ext == output_ext:
        return True

    # 用 ffprobe 探测实际编码
    if not input_path:
        return False
    try:
        ffprobe_path = get_ffprobe_path()

        video_codec = _probe_codec(ffprobe_path, input_path, 'v:0')
        audio_codec = _probe_codec(ffprobe_path, input_path, 'a:0')

        if not video_codec:
            return False

        return is_container_copy_possible(video_codec, audio_codec, output_ext)
    except Exception:
        return False


def _probe_codec(ffprobe_path: str, input_path: str, stream_spec: str) -> str:
    """探测指定流的编码名。"""
    try:
        result = run_subprocess(
            [ffprobe_path,
                '-v', 'error',
                '-select_streams', stream_spec,
                '-show_entries', 'stream=codec_name',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                input_path,
            ],
            capture_output=True, text=True,
            timeout=15,
        )
        return result.stdout.strip().lower()
    except Exception:
        return ''


def _get_available_encoders(ffmpeg_path: str) -> set:
    """获取当前 ffmpeg 支持的所有编码器列表（带缓存）。"""
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache

    with _encoder_cache_lock:
        # 双重检查锁定
        if _encoder_cache is not None:
            return _encoder_cache

        try:
            result = run_subprocess(
                [ffmpeg_path, '-encoders'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            encoders = set()
            for line in result.stdout.splitlines():
                if line and line[0] == ' ' and line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        encoders.add(parts[1])
            _encoder_cache = encoders
            return encoders
        except (subprocess.SubprocessError, FileNotFoundError):
            # 不缓存失败结果，下次调用重试
            return set()


def _pick_encoder(encoders: set, preferred: str, fallback: str) -> str:
    """返回首选编码器（如可用），否则返回备选。"""
    return preferred if preferred in encoders else fallback


def _select_audio_codec(ffmpeg_path: str, output_ext: str, params: dict = None) -> tuple[str, list]:
    """
    根据输出扩展名选择音频编码器和必要的附加参数。
    返回 (encoder_name, extra_ffmpeg_args)。

    Args:
        params: 高级设置参数，如 audio_bitrate, audio_sample_rate 等
    """
    params = params or {}
    output_ext = output_ext.lower()
    encoders = _get_available_encoders(ffmpeg_path)

    # N-09: 从 params 获取音频参数，使用默认值作为兜底
    audio_bitrate = params.get('audio_bitrate', '192k')
    audio_sample_rate = params.get('audio_sample_rate', 44100)

    if output_ext == '.mp3':
        return _pick_encoder(encoders, 'libmp3lame', 'mp3'), ['-b:a', audio_bitrate, '-id3v2_version', '3']
    if output_ext == '.wav':
        return 'pcm_s16le', []
    if output_ext == '.flac':
        return 'flac', ['-compression_level', '5']
    if output_ext == '.ogg':
        return _pick_encoder(encoders, 'libvorbis', 'vorbis'), ['-q:a', '5']
    if output_ext == '.wma':
        return 'wmav2', ['-b:a', audio_bitrate]
    if output_ext in ('.aac', '.m4a'):
        return _pick_encoder(encoders, 'libfdk_aac', 'aac'), ['-b:a', audio_bitrate]
    if output_ext == '.opus':
        return 'libopus', ['-b:a', audio_bitrate]
    # 默认 fallback：让 ffmpeg 根据容器自选
    return 'aac', ['-b:a', audio_bitrate, '-ar', str(audio_sample_rate)]


def _select_video_codecs(ffmpeg_path: str, output_ext: str, params: dict = None) -> tuple[list, list]:
    """
    根据输出视频容器选择视频/音频编码器及参数。
    返回 (video_args, audio_args)。

    Args:
        params: 高级设置参数，如 video_crf, video_preset, audio_bitrate 等
    """
    params = params or {}
    output_ext = output_ext.lower()
    encoders = _get_available_encoders(ffmpeg_path)

    # N-09: 从 params 获取视频参数，使用默认值作为兜底
    video_crf = params.get('video_crf', 23)
    video_preset = params.get('video_preset', 'medium')
    audio_bitrate = params.get('audio_bitrate', '192k')
    audio_sample_rate = params.get('audio_sample_rate', 44100)

    if output_ext == '.gif':
        return (
            ['-vf', 'fps=12,scale=480:-2:flags=lanczos'],
            ['-an'],
        )

    if output_ext == '.webm':
        venc = _pick_encoder(encoders, 'libvpx-vp9', 'libvpx')
        aenc = _pick_encoder(encoders, 'libopus', 'libvorbis')
        return (
            ['-c:v', venc, '-b:v', '1M', '-deadline', 'good', '-cpu-used', '4'],
            ['-c:a', aenc, '-b:a', audio_bitrate],
        )

    if output_ext == '.wmv':
        return (
            ['-c:v', 'wmv2', '-b:v', '2M'],
            ['-c:a', 'wmav2', '-b:a', audio_bitrate],
        )

    if output_ext == '.flv':
        venc = _select_h264_encoder(encoders)
        return (
            ['-c:v', venc, '-preset', video_preset, '-crf', str(video_crf)] if venc == 'libx264'
            else ['-c:v', venc],
            ['-c:a', 'aac', '-b:a', audio_bitrate, '-ar', str(audio_sample_rate)],
        )

    if output_ext == '.avi':
        venc = 'mpeg4'
        aenc = _pick_encoder(encoders, 'libmp3lame', 'mp3')
        return (
            ['-c:v', venc, '-q:v', '5'],
            ['-c:a', aenc, '-b:a', audio_bitrate],
        )

    # 默认 mp4/mov/mkv/ts/m4v：H.264 + AAC
    venc = _select_h264_encoder(encoders)
    if venc == 'libx264':
        v_args = ['-c:v', 'libx264', '-preset', video_preset, '-crf', str(video_crf),
                  '-pix_fmt', 'yuv420p']
    else:
        v_args = ['-c:v', venc, '-pix_fmt', 'yuv420p']
    aenc = _pick_encoder(encoders, 'libfdk_aac', 'aac')
    return (v_args, ['-c:a', aenc, '-b:a', audio_bitrate, '-ar', str(audio_sample_rate)])


def _select_h264_encoder(encoders: set) -> str:
    """
    从可用编码器中挑一个 H.264 实现。

    libx264（软件编码）优先 — 它最稳定且不受并发限制：
    消费级 N 卡的 NVENC 只允许 2-3 路并发会话，
    批量转换时多 worker 同时调用 NVENC 会触发 OpenEncodeSessionEx 失败。
    """
    for enc in ('libx264', 'h264_nvenc', 'h264_qsv', 'h264_amf'):
        if enc in encoders:
            return enc
    return 'libx264'


def _extract_ffmpeg_error(stderr: str) -> str:
    """从 ffmpeg 的 stderr 输出中提取关键错误信息，返回用户友好的提示。"""
    # 精细化错误模式匹配（优先级从高到低）
    _ERROR_PATTERNS = [
        ('No such file or directory', '输入文件不存在或路径无效'),
        ('Invalid data found when processing input', '文件损坏或格式不支持'),
        ('Stream map matches no streams', '文件中无目标流（如无视频流或无音频流）'),
        ('Unknown encoder', '缺少所需编码器，请检查 ffmpeg 版本'),
        ('Permission denied', '文件被占用或无写入权限'),
        ('No space left on device', '磁盘空间不足'),
        ('does not contain any stream', '文件中无任何媒体流'),
        ('invalid data found', '文件格式无效或已损坏'),
        ('error while decoding', '解码错误，文件可能已损坏'),
    ]
    stderr_lower = stderr.lower()
    for pattern, friendly_msg in _ERROR_PATTERNS:
        if pattern.lower() in stderr_lower:
            return friendly_msg

    # 回退：提取包含关键词的行
    lines = stderr.splitlines()
    error_lines = []
    for line in lines:
        if any(word in line.lower() for word in ['error', 'invalid', 'cannot', 'unknown']):
            error_lines.append(line.strip())
    if error_lines:
        return ' | '.join(error_lines[-5:])
    return stderr[-300:] if len(stderr) > 300 else stderr
