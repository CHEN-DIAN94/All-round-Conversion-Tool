"""
workers.py — 并发调度与工作线程管理

基于 QThread + pyqtSignal 实现异步非阻塞转换。
支持进度回调、取消操作和僵尸进程绞杀。

状态机设计：
  IDLE → RUNNING → {COMPLETING, CANCELLING, ERROR} → TERMINAL
  终态必达：任何路径都保证发射 finished_one 信号。
"""


__all__ = ['WorkerState', 'ConversionWorker', 'BatchOrchestrator']

import os
import threading
from enum import Enum, auto
from threading import Lock
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal, QSemaphore

from engines import (
    convert_video,
    convert_audio,
    convert_image,
    convert_pdf_to_docx,
    convert_docx_to_pdf,
    convert_excel_to_image,
)
from engines.gpu_scheduler import GpuScheduler
from utils import CREATE_NO_WINDOW, kill_process_tree


# ==============================================================
# 状态枚举
# ==============================================================

from constants import FileStatus


class WorkerState(Enum):
    """Worker 线程内部状态机"""
    IDLE = auto()        # 初始态
    RUNNING = auto()     # 转换中
    CANCELLING = auto()  # 正在取消
    COMPLETING = auto()  # 完成中
    ERROR = auto()       # 出错
    TERMINAL = auto()    # 终态（信号已发射）


# 默认最大并发数：CPU 核心数，上限 8
_MAX_CONCURRENCY = min(os.cpu_count() or 4, 8)


# ==============================================================
# ConversionWorker — 单文件转换工作线程
# ==============================================================

class ConversionWorker(QThread):
    """
    单个文件转换的工作线程。

    状态机保证：
    - 任何路径最终都到达 TERMINAL 终态
    - 终态时发射 finished_one 信号（且仅发射一次）
    - cancel() 幂等，重复调用安全
    """

    status_updated = pyqtSignal(int, str)
    progress_updated = pyqtSignal(int, int)
    finished_one = pyqtSignal(int, bool, str)

    def __init__(
        self,
        file_index: int,
        input_path: str,
        output_path: str,
        conv_type: str,
        semaphore: Optional[QSemaphore] = None,
        settings: Optional[dict] = None,
        gpu_scheduler: Optional[GpuScheduler] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.file_index = file_index
        self.input_path = input_path
        self.output_path = output_path
        self.conv_type = conv_type
        self._settings = settings or {}  # N-09: 高级设置参数
        self._gpu_scheduler = gpu_scheduler

        # 状态机
        self._state = WorkerState.IDLE
        self._state_lock = Lock()
        self._cancel_event = threading.Event()
        self._finished_emitted = False

        # 进程管理
        self._proc_handle = None
        self._semaphore = semaphore
        self._orchestrator_pause: Optional[threading.Event] = None  # 暂停信号

        # 耗时与命令记录
        self._start_time: float = 0
        self._end_time: float = 0
        self._last_cmd: str = ''

    # ----------------------------------------------------------
    # 状态转换（原子）
    # ----------------------------------------------------------

    def _transition_to(self, new_state: WorkerState) -> WorkerState:
        """原子状态转换，返回旧状态。"""
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            return old_state

    # ----------------------------------------------------------
    # 线程主函数
    # ----------------------------------------------------------

    def run(self) -> None:
        """执行转换任务（在子线程中运行），保证终态必达。"""
        import time as _time
        self._start_time = _time.monotonic()

        # 如果队列暂停了，等待恢复
        if self._orchestrator_pause:
            self._orchestrator_pause.wait()

        if self._semaphore:
            self._semaphore.acquire()

        self._transition_to(WorkerState.RUNNING)
        self.status_updated.emit(self.file_index, FileStatus.CONVERTING)
        self.progress_updated.emit(self.file_index, 0)

        status = FileStatus.FAILED  # 默认值，正常路径会覆盖

        try:
            result_path = self._do_convert()

            if self._cancel_event.is_set():
                self._transition_to(WorkerState.CANCELLING)
                status = FileStatus.CANCELLED
            elif result_path and os.path.isfile(result_path):
                self._transition_to(WorkerState.COMPLETING)
                self.progress_updated.emit(self.file_index, 100)
                self.status_updated.emit(self.file_index, FileStatus.SUCCESS)
                status = FileStatus.SUCCESS
            else:
                raise RuntimeError('输出文件未生成')

        except Exception as e:
            self._transition_to(WorkerState.ERROR)
            if self._cancel_event.is_set():
                status = FileStatus.CANCELLED
            else:
                status = FileStatus.FAILED
                self.status_updated.emit(self.file_index, FileStatus.FAILED)

        finally:
            self._end_time = _time.monotonic()
            # 释放 GPU 编码会话
            if self._gpu_scheduler:
                self._gpu_scheduler.release_encoder()
            # 终态：必须发射信号（且仅一次）
            self._transition_to(WorkerState.TERMINAL)
            if not self._finished_emitted:
                success = (status == FileStatus.SUCCESS)
                msg = self._get_status_message(status)
                self.finished_one.emit(self.file_index, success, msg)
                self._finished_emitted = True

            if self._semaphore:
                self._semaphore.release()

    def _get_status_message(self, status: str) -> str:
        """根据状态返回用户友好的消息。"""
        if status == FileStatus.SUCCESS:
            return '转换完成'
        elif status == FileStatus.CANCELLED:
            return '用户取消了转换'
        elif status == FileStatus.FAILED:
            return '转换失败'
        return '未知状态'

    @property
    def duration_ms(self) -> int:
        """转换耗时（毫秒）。"""
        if self._start_time > 0 and self._end_time > self._start_time:
            return int((self._end_time - self._start_time) * 1000)
        return 0

    # ----------------------------------------------------------
    # 取消（幂等）
    # ----------------------------------------------------------

    def cancel(self) -> None:
        """
        请求取消转换（幂等）。

        已取消或已结束时调用不会产生副作用。
        """
        with self._state_lock:
            if self._state in (WorkerState.CANCELLING, WorkerState.TERMINAL):
                return  # 已取消或已结束，忽略
            if self._state == WorkerState.RUNNING:
                self._state = WorkerState.CANCELLING

        self._cancel_event.set()

        # 杀死子进程
        if self._proc_handle is not None:
            try:
                kill_process_tree(self._proc_handle)
            except Exception:
                pass  # 进程可能已退出

    # ----------------------------------------------------------
    # 引擎派发
    # ----------------------------------------------------------

    def _do_convert(self) -> str:
        """根据类型派发到具体引擎。"""
        conv_type = self.conv_type
        proc_ref = []  # 可变容器，引擎函数将 Popen 对象追加到此列表
        result_path = None

        if conv_type == 'video':
            result_path = convert_video(
                self.input_path,
                self.output_path,
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
                params=self._settings,  # N-09: 传递高级设置
            )
        elif conv_type == 'audio':
            result_path = convert_audio(
                self.input_path,
                self.output_path,
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
                params=self._settings,  # N-09: 传递高级设置
            )
        elif conv_type == 'image':
            result_path = convert_image(
                self.input_path,
                self.output_path,
                params=self._settings,  # N-09: 传递高级设置
            )
        elif conv_type == 'pdf_to_docx':
            result_path = convert_pdf_to_docx(self.input_path, self.output_path)
        elif conv_type == 'docx_to_pdf':
            result_path = convert_docx_to_pdf(self.input_path, self.output_path)
        elif conv_type == 'excel_to_image':
            result_path = convert_excel_to_image(
                self.input_path,
                self.output_path,
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
            )
        elif conv_type == 'embed_subtitle':
            from engines.ffmpeg_utils import embed_subtitle
            result_path = embed_subtitle(
                self.input_path,
                self.output_path,
                subtitle_path=self._settings.get('subtitle_path', ''),
                language=self._settings.get('language', 'chi'),
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        elif conv_type == 'extract_subtitle':
            from engines.ffmpeg_utils import extract_subtitle
            result_path = extract_subtitle(self.input_path, self.output_path)
        elif conv_type == 'extract_audio':
            from engines import extract_audio
            result_path = extract_audio(
                self.input_path,
                self.output_path,
                format=self._settings.get('format', 'mp3'),
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        elif conv_type == 'merge_media':
            from engines.ffmpeg_utils import merge_media
            merge_paths = self._settings.get('merge_paths', [])
            # [RISK-05 修复] 防御性校验：至少需要 2 个文件
            if len(merge_paths) < 2:
                raise ValueError(
                    f'合并至少需要 2 个文件，当前只有 {len(merge_paths)} 个'
                )
            result_path = merge_media(
                merge_paths,
                self.output_path,
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        elif conv_type == 'crop_video':
            from engines.ffmpeg_utils import crop_video
            # [RISK-06 修复] 默认值 0 表示动态探测源视频尺寸
            crop_w = self._settings.get('crop_w', 0)
            crop_h = self._settings.get('crop_h', 0)
            if crop_w <= 0 or crop_h <= 0:
                from engines.ffmpeg_utils import _probe_video_info
                info = _probe_video_info(self.input_path)
                if crop_w <= 0:
                    crop_w = info.get('width', 1920)
                if crop_h <= 0:
                    crop_h = info.get('height', 1080)
            result_path = crop_video(
                self.input_path,
                self.output_path,
                width=crop_w,
                height=crop_h,
                x=self._settings.get('crop_x', 0),
                y=self._settings.get('crop_y', 0),
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        elif conv_type == 'trim_media':
            from engines import trim_media
            result_path = trim_media(
                self.input_path,
                self.output_path,
                start_time=self._settings.get('start_time', '00:00:00'),
                end_time=self._settings.get('end_time', '00:01:00'),
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        elif conv_type == 'compress_video':
            from engines import compress_video
            result_path = compress_video(
                self.input_path,
                self.output_path,
                target_size_mb=self._settings.get('target_size_mb', 0),
                crf=self._settings.get('crf', 28),
                scale_width=self._settings.get('scale_width', 0),
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        elif conv_type == 'compress_image':
            from engines import compress_image
            result_path = compress_image(
                self.input_path,
                self.output_path,
                target_size_kb=self._settings.get('target_size_kb', 0),
                quality=self._settings.get('quality', 80),
            )
            if result_path:
                self.progress_updated.emit(self.file_index, 100)
        elif conv_type == 'resize_image':
            from engines import resize_image
            result_path = resize_image(
                self.input_path,
                self.output_path,
                width=self._settings.get('width', 0),
                height=self._settings.get('height', 0),
                percentage=self._settings.get('percentage', 0),
                max_dimension=self._settings.get('max_dimension', 0),
                quality=self._settings.get('image_quality', 95),
            )
            if result_path:
                self.progress_updated.emit(self.file_index, 100)
        elif conv_type == 'add_watermark':
            from engines import add_watermark
            result_path = add_watermark(
                self.input_path,
                self.output_path,
                text=self._settings.get('text', ''),
                position=self._settings.get('position', 'bottom-right'),
                opacity=self._settings.get('opacity', 0.5),
                font_size=self._settings.get('font_size', 24),
            )
            if result_path:
                self.progress_updated.emit(self.file_index, 100)
        elif conv_type == 'video_to_gif':
            from engines import convert_video_to_gif
            result_path = convert_video_to_gif(
                self.input_path,
                self.output_path,
                fps=self._settings.get('fps', 12),
                width=self._settings.get('width', 480),
                colors=self._settings.get('colors', 256),
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_event=self._cancel_event,
                proc_ref=proc_ref,
            )
        else:
            raise ValueError(f'不支持的转换类型: {conv_type}')

        # 将引擎进程句柄同步到 worker，以便 cancel() 能杀死它
        if proc_ref:
            self._proc_handle = proc_ref[0]
        return result_path


# ==============================================================
# BatchOrchestrator — 批量编排器
# ==============================================================

class BatchOrchestrator:
    """
    批量编排器（非 QThread，在主线程使用）。

    管理一组 ConversionWorker，通过信号量控制并发数。
    完成判定在 UI 层通过 self._completed_count 计数实现。
    """

    def __init__(self, max_concurrency: int = _MAX_CONCURRENCY, gpu_scheduler: Optional[GpuScheduler] = None):
        self.workers: list[ConversionWorker] = []
        self._semaphore = QSemaphore(max_concurrency)
        self._gpu_scheduler = gpu_scheduler or GpuScheduler()
        self._paused = threading.Event()
        self._paused.set()  # 初始为"未暂停"状态

    def add_worker(self, worker: ConversionWorker) -> None:
        """添加工作线程。"""
        worker._semaphore = self._semaphore
        worker._orchestrator_pause = self._paused
        if worker._gpu_scheduler is None:
            worker._gpu_scheduler = self._gpu_scheduler
        self.workers.append(worker)

    def clear(self) -> None:
        """清理已完成的工作线程。"""
        self.workers = [w for w in self.workers if w.isRunning()]

    def clear_all(self) -> None:
        """清空所有工作线程。"""
        self.workers.clear()

    def start_all(self) -> None:
        """启动所有待执行的工作线程。"""
        # 首次启动时探测 GPU
        if not self._gpu_scheduler._probed:
            self._gpu_scheduler.probe_gpu()
        for worker in self.workers:
            if not worker.isRunning():
                worker.start()

    def cancel_all(self) -> None:
        """取消所有正在执行的工作线程。"""
        for worker in self.workers:
            if worker.isRunning():
                worker.cancel()

    def pause_all(self) -> None:
        """暂停队列——当前正在执行的任务继续完成，新任务不再启动。"""
        self._paused.clear()

    def resume_all(self) -> None:
        """恢复队列。"""
        self._paused.set()

    @property
    def is_paused(self) -> bool:
        """队列是否处于暂停状态。"""
        return not self._paused.is_set()

    def wait_all(self, timeout_ms: int = 5000) -> None:
        """
        等待所有工作线程退出，超时则强杀。

        [STRESS-02 修复] terminate 后二次 wait，
        确保 semaphore 彻底释放，防止重试时死锁。
        """
        for worker in self.workers:
            if worker.isRunning():
                worker.cancel()                      # 先杀子进程树
                if not worker.wait(timeout_ms):      # 等待线程退出
                    worker.terminate()               # 超时 → 强制终止
                    worker.wait(2000)                # 二次 wait 确保退出

    def active_count(self) -> int:
        """当前正在运行的线程数。"""
        return sum(1 for w in self.workers if w.isRunning())
