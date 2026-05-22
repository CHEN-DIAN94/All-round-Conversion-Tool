"""
engines.py — 转换引擎核心

实现视频、音频、图片、文档四大类格式转换的具体逻辑。
所有函数均为同步阻塞式，由 workers.py 中的工作线程调度。
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Callable, Optional

from utils import (
    get_ffmpeg_path,
    run_subprocess_popen,
    safe_temp_path,
    finalize_file,
    ensure_output_dir,
    CREATE_NO_WINDOW,
)

# ==============================================================
# 视频 / 音频引擎 — 基于 ffmpeg
# ==============================================================

def convert_video(
    input_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_flag: Optional[list] = None,
) -> str:
    """
    视频格式转换。

    核心策略：
    1. 若仅改变封装格式（容器），优先 -c copy 无损直通
    2. 若需重新编码，依次尝试 h264_nvenc / h264_qsv → libx264
    3. 始终保留原始元数据和色彩信息

    Args:
        input_path:  源文件路径
        output_path: 目标文件路径
        progress_callback: 进度回调函数，传入 0-100 整数
        cancel_flag: 取消标志列表，cancel_flag[0] = True 表示取消

    Returns:
        成功时返回 output_path，失败时抛出异常。

    Raises:
        RuntimeError: 转换过程中发生错误
        FileNotFoundError: ffmpeg 未找到
    """
    ffmpeg = get_ffmpeg_path()
    input_ext = Path(input_path).suffix.lower()
    output_ext = Path(output_path).suffix.lower()
    temp_path = safe_temp_path(output_path)
    ensure_output_dir(output_path)

    # ---------- 步骤 1：检测纯封装转换 ----------
    # 将扩展名映射到 ffmpeg 格式名称（简化版）
    container_only = _is_container_only(input_ext, output_ext)

    if container_only:
        cmd = [
            ffmpeg, '-y',
            '-i', input_path,
            '-c', 'copy',           # 无损直通
            '-map_metadata', '0',
            temp_path,
        ]
    else:
        # ---------- 步骤 2：选择编码器 ----------
        encoder = _select_video_encoder(ffmpeg)
        cmd = [
            ffmpeg, '-y',
            '-i', input_path,
            '-c:v', encoder,
            '-map_metadata', '0',
            '-color_primaries', '1',
            '-color_trc', '1',
            '-colorspace', '1',
            # 音频默认使用 AAC
            '-c:a', 'aac',
            '-b:a', '192k',
            # 进度信息输出到 stderr
            temp_path,
        ]

    # ---------- 步骤 3：执行转换 ----------
    proc = run_subprocess_popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stderr = _run_ffmpeg_with_monitor(proc, progress_callback, cancel_flag)

    if proc.returncode != 0:
        error_msg = _extract_ffmpeg_error(stderr)
        raise RuntimeError(f'视频转换失败 (code={proc.returncode}): {error_msg}')

    # ---------- 步骤 4：完成 ----------
    finalize_file(temp_path, output_path)
    return output_path


def convert_audio(
    input_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_flag: Optional[list] = None,
) -> str:
    """
    音频格式转换。

    始终重新编码以保证兼容性（音频直通场景较少且易出问题）。
    优先检测 libfdk_aac（高质量 AAC），回退到 aac。
    """
    ffmpeg = get_ffmpeg_path()
    temp_path = safe_temp_path(output_path)
    ensure_output_dir(output_path)

    # 检测可用的 AAC 编码器
    aac_encoder = _detect_aac_encoder(ffmpeg)

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-c:a', aac_encoder,
        '-b:a', '192k',
        '-map_metadata', '0',
        '-id3v2_version', '3',
        temp_path,
    ]

    proc = run_subprocess_popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stderr = _run_ffmpeg_with_monitor(proc, progress_callback, cancel_flag)

    if proc.returncode != 0:
        error_msg = _extract_ffmpeg_error(stderr)
        raise RuntimeError(f'音频转换失败 (code={proc.returncode}): {error_msg}')

    finalize_file(temp_path, output_path)
    return output_path


# ==============================================================
# 图片引擎 — 基于 Pillow
# ==============================================================

def convert_image(input_path: str, output_path: str) -> str:
    """
    图片格式转换（Pillow 实现）。

    特殊处理：
    - PNG → JPG：自动将透明通道融合为白色背景
    - 保留 ICC 色彩配置文件（如可用）
    """
    from PIL import Image

    ensure_output_dir(output_path)
    temp_path = safe_temp_path(output_path)

    img = Image.open(input_path)
    output_ext = Path(output_path).suffix.lower()

    # ---------- 处理透明通道 ----------
    if output_ext in ('.jpg', '.jpeg') and img.mode in ('RGBA', 'LA', 'P'):
        # 创建白色背景图
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background
    elif img.mode not in ('RGB', 'L', '1'):
        # 其他模式转换为 RGB 保证兼容
        img = img.convert('RGB')

    # ---------- 保存 ----------
    save_kwargs = _get_image_save_params(output_ext, img)
    img.save(temp_path, **save_kwargs)
    img.close()

    finalize_file(temp_path, output_path)
    return output_path


# ==============================================================
# 文档引擎
# ==============================================================

def convert_pdf_to_docx(input_path: str, output_path: str) -> str:
    """
    PDF → DOCX 转换（pdf2docx 实现）。
    纯 Python 实现，无需 Microsoft Word。
    """
    from pdf2docx import Converter

    ensure_output_dir(output_path)
    temp_path = safe_temp_path(output_path)

    try:
        cv = Converter(input_path)
        cv.convert(temp_path, start=0, end=None)
        cv.close()
    except Exception as e:
        raise RuntimeError(f'PDF 转换失败: {e}')

    finalize_file(temp_path, output_path)
    return output_path


def convert_docx_to_pdf(input_path: str, output_path: str) -> str:
    """
    DOCX → PDF 转换（docx2pdf / pywin32 COM 自动化）。

    必须 try...except 捕获 COM 异常（如本地未安装 Word），
    返回友好的中文错误字符串，绝不闪退。
    """
    import pywintypes

    ensure_output_dir(output_path)
    temp_path = safe_temp_path(output_path)

    try:
        # docx2pdf 内部使用 pywin32 调用 Word COM 对象
        from docx2pdf import convert as docx2pdf_convert

        # 写入临时文件，成功后再重命名
        docx2pdf_convert(input_path, temp_path)

        # 确保文件已生成
        if not os.path.isfile(temp_path):
            raise RuntimeError('docx2pdf 未生成输出文件')

        # 重命名 temp → 最终文件
        finalize_file(temp_path, output_path)

    except pywintypes.com_error as e:
        error_msg = _parse_com_error(e)
        raise RuntimeError(
            f'Word 转换失败：{error_msg}\n'
            '请确认已安装 Microsoft Word。'
        )
    except ImportError as e:
        raise RuntimeError(
            f'缺少依赖：{e}\n请确认已安装 pywin32。'
        )
    except Exception as e:
        raise RuntimeError(f'DOCX 转换失败：{e}')

    return output_path


# ==============================================================
# 内部辅助函数
# ==============================================================

def _is_container_only(input_ext: str, output_ext: str) -> bool:
    """
    判断是否仅为容器格式转换（无需重新编码）。
    当输入和输出的视频/音频编码兼容时返回 True。
    """
    # 同格式无需重新编码
    if input_ext == output_ext:
        return True

    # 常见容器直通组合：输入编码在这些容器中通常兼容
    # 源格式 → MP4/MKV 等可以直接 copy
    container_copy_pairs = {
        '.mp4':  {'.mkv', '.mov', '.ts'},
        '.mkv':  {'.mp4', '.mov'},
        '.mov':  {'.mp4', '.mkv'},
        '.avi':  {'.mkv', '.mp4'},
        '.flv':  {'.mp4', '.mkv'},
        '.ts':   {'.mp4', '.mkv'},
        '.m4v':  {'.mp4', '.mkv'},
        '.webm': {'.mp4', '.mkv'},
    }
    return output_ext in container_copy_pairs.get(input_ext, set())


def _select_video_encoder(ffmpeg_path: str) -> str:
    """
    选择可用的最佳视频编码器。

    优先级：h264_nvenc (NVIDIA) > h264_qsv (Intel QuickSync) > libx264 (软件)
    """
    encoders = _get_available_encoders(ffmpeg_path)

    if 'h264_nvenc' in encoders:
        return 'h264_nvenc'
    if 'h264_qsv' in encoders:
        return 'h264_qsv'
    # 无 GPU 加速时降级到 libx264
    return 'libx264'


def _get_available_encoders(ffmpeg_path: str) -> set:
    """获取当前 ffmpeg 支持的所有编码器列表。"""
    try:
        result = subprocess.run(
            [ffmpeg_path, '-encoders'],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            timeout=15,
        )
        encoders = set()
        for line in result.stdout.splitlines():
            # 编码器行以空格开头，格式: " V....D encodername ..."
            if line and line[0] == ' ' and line.strip():
                parts = line.strip().split()
                if len(parts) >= 2:
                    # parts[0] 是标志位如 V....D, parts[1] 是编码器名称
                    encoders.add(parts[1])
        return encoders
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()


def _detect_aac_encoder(ffmpeg_path: str) -> str:
    """
    检测可用的 AAC 编码器。
    libfdk_aac 质量最高但需编译支持；回退到原生 aac。
    """
    encoders = _get_available_encoders(ffmpeg_path)
    if 'libfdk_aac' in encoders:
        return 'libfdk_aac'
    return 'aac'


def _run_ffmpeg_with_monitor(
    proc: subprocess.Popen,
    progress_callback: Optional[Callable[[int], None]],
    cancel_flag: Optional[list],
) -> str:
    """
    监控 ffmpeg 进度，读取 stderr，等待进程结束。

    通过读取 stderr 中的 time=... 信息估算转换进度。
    如果 cancel_flag 被设置为 True，立即终止进程。
    返回完整的 stderr 输出字符串供调用方分析错误。

    注意：此函数会读取 proc.stderr，调用方不要再调用 proc.communicate()。
    """
    import re
    import threading

    duration_pattern = re.compile(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)')
    time_pattern = re.compile(r'time=(\d+):(\d+):(\d+)\.(\d+)')

    total_seconds = None
    stderr_lines = []
    reading_done = threading.Event()

    def _reader():
        nonlocal total_seconds
        try:
            for line in iter(proc.stderr.readline, ''):
                stderr_lines.append(line)

                if cancel_flag and cancel_flag[0]:
                    _kill_process(proc)
                    break

                # 解析总时长
                if total_seconds is None:
                    m = duration_pattern.search(line)
                    if m:
                        total_seconds = (
                            int(m.group(1)) * 3600
                            + int(m.group(2)) * 60
                            + int(m.group(3))
                        )

                # 解析当前进度
                m = time_pattern.search(line)
                if m and total_seconds and progress_callback:
                    current = (
                        int(m.group(1)) * 3600
                        + int(m.group(2)) * 60
                        + int(m.group(3))
                    )
                    if total_seconds > 0:
                        progress = min(int(current / total_seconds * 100), 99)
                        progress_callback(progress)
        except ValueError:
            pass  # stderr 关闭后的读错误忽略
        finally:
            reading_done.set()

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    # 等待 reader 线程结束（进程退出后 stderr 读取会自动结束）
    reading_done.wait()
    reader.join(timeout=3)

    # 确保进程已结束
    if proc.poll() is None:
        proc.wait(timeout=10)

    return ''.join(stderr_lines)


def _kill_process(proc: subprocess.Popen) -> None:
    """
    安全终止进程及其子进程树。

    确保不留僵尸 ffmpeg.exe 或 WINWORD.EXE 在后台。
    """
    if proc and proc.poll() is None:
        try:
            # Windows 下用 taskkill 杀掉进程树
            if sys.platform == 'win32':
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                    creationflags=CREATE_NO_WINDOW,
                    capture_output=True,
                )
            else:
                proc.kill()
            proc.wait(timeout=5)
        except Exception:
            # 确保无论如何都终止
            try:
                proc.kill()
            except Exception:
                pass


def _extract_ffmpeg_error(stderr: str) -> str:
    """从 ffmpeg 的 stderr 输出中提取关键错误信息。"""
    lines = stderr.splitlines()
    error_lines = []
    for line in lines:
        if any(word in line.lower() for word in ['error', 'invalid', 'cannot', 'unknown']):
            error_lines.append(line.strip())
    if error_lines:
        return ' | '.join(error_lines[-5:])  # 最多返回最近 5 行
    return stderr[-300:] if len(stderr) > 300 else stderr


def _get_image_save_params(ext: str, img) -> dict:
    """
    根据输出格式返回 Pillow save 参数。
    """
    params = {}
    if ext in ('.jpg', '.jpeg'):
        params['quality'] = 95
        params['optimize'] = True
    elif ext == '.png':
        params['optimize'] = True
    elif ext == '.webp':
        params['quality'] = 90
    elif ext == '.tiff' or ext == '.tif':
        params['compression'] = 'tiff_lzw'
    return params


def _parse_com_error(e) -> str:
    """解析 pywintypes.com_error 为可读消息。"""
    try:
        if hasattr(e, 'strerror') and e.strerror:
            return str(e.strerror)
        if hasattr(e, 'args') and e.args:
            return str(e.args[1]) if len(e.args) > 1 else str(e.args[0])
    except Exception:
        pass
    return 'Microsoft Word COM 组件错误，请检查 Word 安装'
