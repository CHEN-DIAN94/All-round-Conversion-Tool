"""
execution_registry.py — 执行分发注册表

集中定义 task key 到具体执行器的映射，替代 workers.py 中的大型 if/elif。
"""

from __future__ import annotations

__all__ = [
    'TASK_PARAM_ALIASES',
    'TASK_REGISTRY',
    'execute_task',
]

from typing import Callable

from engines import (
    convert_audio,
    convert_docx_to_pdf,
    convert_excel_to_image,
    convert_image,
    convert_pdf_to_docx,
    convert_video,
)
from engines import add_watermark, compress_image, compress_video, convert_video_to_gif
from engines import extract_audio, resize_image, trim_media
from engines.ffmpeg_utils import crop_video, embed_subtitle, extract_subtitle, merge_media
from task_models import ExecutionResult, TaskSpec


TASK_PARAM_ALIASES: dict[str, dict[str, str]] = {
    'embed_subtitle': {'subtitle_path': 'subtitle_path', 'language': 'language'},
    'extract_audio': {'format': 'format'},
    'merge_media': {'merge_paths': 'merge_paths'},
    'crop_video': {'width': 'crop_w', 'height': 'crop_h', 'x': 'crop_x', 'y': 'crop_y'},
    'trim_media': {'start_time': 'start_time', 'end_time': 'end_time'},
    'compress_video': {'crf': 'crf', 'scale_width': 'scale_width', 'target_size_mb': 'target_size_mb'},
    'compress_image': {'quality': 'quality', 'target_size_kb': 'target_size_kb', 'max_dimension': 'max_dimension'},
    'resize_image': {'width': 'width', 'height': 'height', 'percentage': 'percentage', 'max_dimension': 'max_dimension', 'quality': 'image_quality'},
    'add_watermark': {'text': 'text', 'position': 'position', 'opacity': 'opacity', 'font_size': 'font_size'},
    'video_to_gif': {'fps': 'fps', 'width': 'width', 'colors': 'colors'},
}


def _mark_completed(result_path: str, progress_callback=None) -> ExecutionResult:
    if result_path and progress_callback is not None:
        progress_callback(100)
    return ExecutionResult(output_path=result_path, progress_complete=bool(result_path))


def _run_video(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = convert_video(
        task.input_path,
        task.output_path,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
        params=task.params,
    )
    return ExecutionResult(output_path=result)


def _run_audio(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = convert_audio(
        task.input_path,
        task.output_path,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
        params=task.params,
    )
    return ExecutionResult(output_path=result)


def _run_image(task: TaskSpec, **_) -> ExecutionResult:
    result = convert_image(task.input_path, task.output_path, params=task.params)
    return _mark_completed(result)


def _run_pdf_to_docx(task: TaskSpec, **_) -> ExecutionResult:
    return _mark_completed(convert_pdf_to_docx(task.input_path, task.output_path))


def _run_docx_to_pdf(task: TaskSpec, **_) -> ExecutionResult:
    return _mark_completed(convert_docx_to_pdf(task.input_path, task.output_path))


def _run_excel_to_image(task: TaskSpec, progress_callback=None, **_) -> ExecutionResult:
    result = convert_excel_to_image(
        task.input_path,
        task.output_path,
        progress_callback=progress_callback,
    )
    return ExecutionResult(output_path=result)


def _run_embed_subtitle(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = embed_subtitle(
        task.input_path,
        task.output_path,
        subtitle_path=task.params.get('subtitle_path', ''),
        language=task.params.get('language', 'chi'),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


def _run_extract_subtitle(task: TaskSpec, **_) -> ExecutionResult:
    return _mark_completed(extract_subtitle(task.input_path, task.output_path))


def _run_extract_audio(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = extract_audio(
        task.input_path,
        task.output_path,
        format=task.params.get('format', 'mp3'),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


def _run_merge_media(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    merge_paths = task.params.get('merge_paths', [])
    if len(merge_paths) < 2:
        raise ValueError(f'合并至少需要 2 个文件，当前只有 {len(merge_paths)} 个')
    result = merge_media(
        merge_paths,
        task.output_path,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


def _run_crop_video(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = crop_video(
        task.input_path,
        task.output_path,
        width=task.params.get('crop_w', 0),
        height=task.params.get('crop_h', 0),
        x=task.params.get('crop_x', 0),
        y=task.params.get('crop_y', 0),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


def _run_trim_media(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = trim_media(
        task.input_path,
        task.output_path,
        start_time=task.params.get('start_time', '00:00:00'),
        end_time=task.params.get('end_time', '00:01:00'),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


def _run_compress_video(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = compress_video(
        task.input_path,
        task.output_path,
        target_size_mb=task.params.get('target_size_mb', 0),
        crf=task.params.get('crf', 28),
        scale_width=task.params.get('scale_width', 0),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


def _run_compress_image(task: TaskSpec, **_) -> ExecutionResult:
    result = compress_image(
        task.input_path,
        task.output_path,
        target_size_kb=task.params.get('target_size_kb', 0),
        quality=task.params.get('quality', 80),
        max_dimension=task.params.get('max_dimension', 0),
    )
    return _mark_completed(result)


def _run_resize_image(task: TaskSpec, **_) -> ExecutionResult:
    result = resize_image(
        task.input_path,
        task.output_path,
        width=task.params.get('width', 0),
        height=task.params.get('height', 0),
        percentage=task.params.get('percentage', 0),
        max_dimension=task.params.get('max_dimension', 0),
        quality=task.params.get('image_quality', 95),
    )
    return _mark_completed(result)


def _run_add_watermark(task: TaskSpec, **_) -> ExecutionResult:
    result = add_watermark(
        task.input_path,
        task.output_path,
        text=task.params.get('text', ''),
        position=task.params.get('position', 'bottom-right'),
        opacity=task.params.get('opacity', 0.5),
        font_size=task.params.get('font_size', 24),
    )
    return _mark_completed(result)


def _run_video_to_gif(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    result = convert_video_to_gif(
        task.input_path,
        task.output_path,
        fps=task.params.get('fps', 12),
        width=task.params.get('width', 480),
        colors=task.params.get('colors', 256),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
    return ExecutionResult(output_path=result)


TASK_REGISTRY: dict[str, Callable[..., ExecutionResult]] = {
    'video': _run_video,
    'audio': _run_audio,
    'image': _run_image,
    'pdf_to_docx': _run_pdf_to_docx,
    'docx_to_pdf': _run_docx_to_pdf,
    'excel_to_image': _run_excel_to_image,
    'embed_subtitle': _run_embed_subtitle,
    'extract_subtitle': _run_extract_subtitle,
    'extract_audio': _run_extract_audio,
    'merge_media': _run_merge_media,
    'crop_video': _run_crop_video,
    'trim_media': _run_trim_media,
    'compress_video': _run_compress_video,
    'compress_image': _run_compress_image,
    'resize_image': _run_resize_image,
    'add_watermark': _run_add_watermark,
    'video_to_gif': _run_video_to_gif,
}


def execute_task(task: TaskSpec, progress_callback=None, cancel_event=None, proc_ref=None) -> ExecutionResult:
    """根据 task key 分发到具体执行器。"""
    runner = TASK_REGISTRY.get(task.key)
    if runner is None:
        raise ValueError(f'不支持的转换类型: {task.key}')
    return runner(
        task,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
        proc_ref=proc_ref,
    )
