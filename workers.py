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

from engines.gpu_scheduler import GpuScheduler
from execution_registry import execute_task
from task_models import TaskSpec
from utils import CREATE_NO_WINDOW, kill_process_tree
from monitor import trace, monitor_log


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
        trace('worker.run.start', row=self.file_index,
              input=self.input_path, output=self.output_path,
              conv=self.conv_type, tid=threading.get_ident())

        # 如果队列暂停了，等待恢复
        if self._orchestrator_pause:
            self._orchestrator_pause.wait()

        if self._semaphore:
            self._semaphore.acquire()

        self._transition_to(WorkerState.RUNNING)
        self.status_updated.emit(self.file_index, FileStatus.CONVERTING)
        self.progress_updated.emit(self.file_index, 0)
        trace('worker.state', row=self.file_index, state='RUNNING')

        status = FileStatus.FAILED  # 默认值，正常路径会覆盖

        try:
            result_path = self._do_convert()
            trace('worker.convert.done', row=self.file_index,
                  result=result_path, exists=os.path.isfile(result_path) if result_path else False,
                  cancelled=self._cancel_event.is_set())

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
            trace('worker.convert.error', row=self.file_index,
                  error=repr(e), cancelled=self._cancel_event.is_set())
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
            trace('worker.state', row=self.file_index, state='TERMINAL', status=status)
            if not self._finished_emitted:
                success = (status == FileStatus.SUCCESS)
                msg = self._get_status_message(status)
                trace('worker.emit.finished_one', row=self.file_index,
                      success=success, msg=msg)
                self.finished_one.emit(self.file_index, success, msg)
                self._finished_emitted = True

            if self._semaphore:
                self._semaphore.release()
            trace('worker.run.exit', row=self.file_index)

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
                trace('worker.cancel.skip', row=self.file_index, state=str(self._state))
                return  # 已取消或已结束，忽略
            if self._state == WorkerState.RUNNING:
                self._state = WorkerState.CANCELLING

        trace('worker.cancel', row=self.file_index)
        self._cancel_event.set()

        # 杀死子进程
        if self._proc_handle is not None:
            trace('worker.cancel.kill_proc', row=self.file_index)
            try:
                kill_process_tree(self._proc_handle)
            except Exception as e:
                trace('worker.cancel.kill_failed', row=self.file_index, error=repr(e))
                pass  # 进程可能已退出

    # ----------------------------------------------------------
    # 引擎派发
    # ----------------------------------------------------------

    def _do_convert(self) -> str:
        """根据类型派发到具体引擎。"""
        proc_ref = []  # 可变容器，引擎函数将 Popen 对象追加到此列表
        task = TaskSpec(
            key=self.conv_type,
            input_path=self.input_path,
            output_path=self.output_path,
            params=self._settings.copy(),
        )
        result = execute_task(
            task,
            progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
            cancel_event=self._cancel_event,
            proc_ref=proc_ref,
        )

        # 将引擎进程句柄同步到 worker，以便 cancel() 能杀死它
        if proc_ref:
            self._proc_handle = proc_ref[0]
        return result.output_path or ''


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
        等待所有工作线程退出，超时则保留运行态交由上层继续处理。

        避免使用 QThread.terminate() 硬杀线程，防止 Qt/Python 状态损坏。
        """
        for worker in self.workers:
            if worker.isRunning():
                worker.cancel()
                worker.wait(timeout_ms)

    def active_count(self) -> int:
        """当前正在运行的线程数。"""
        return sum(1 for w in self.workers if w.isRunning())
