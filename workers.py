"""
workers.py — 并发调度与工作线程管理

基于 QThread + pyqtSignal 实现异步非阻塞转换。
支持进度回调、取消操作和僵尸进程绞杀。
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from engines import (
    convert_video,
    convert_audio,
    convert_image,
    convert_pdf_to_docx,
    convert_docx_to_pdf,
)
from utils import CREATE_NO_WINDOW


# 文件状态枚举（界面层也使用）
class FileStatus:
    WAITING = '等待中'
    CONVERTING = '转换中'
    SUCCESS = '成功'
    FAILED = '失败'
    CANCELLED = '已取消'


class ConversionWorker(QThread):
    """
    单个文件转换的工作线程。

    通过 pyqtSignal 向主线程报告状态和进度：
    - status_updated: (file_index, status_str)
    - progress_updated: (file_index, percent_int)
    - finished_one: (file_index, success_bool, message_str)
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
        parent=None,
    ):
        super().__init__(parent)
        self.file_index = file_index
        self.input_path = input_path
        self.output_path = output_path
        self.conv_type = conv_type  # 'video', 'audio', 'image', 'pdf_to_docx', 'docx_to_pdf'
        self._cancel_flag = [False]  # 使用列表使内部修改对外可见
        self._proc_handle = None

    def run(self) -> None:
        """执行转换任务（在子线程中运行）。"""
        try:
            self.status_updated.emit(self.file_index, FileStatus.CONVERTING)
            self.progress_updated.emit(self.file_index, 0)

            # 根据转换类型选择引擎
            result_path = self._do_convert()

            # 检查是否被取消
            if self._cancel_flag[0]:
                self.status_updated.emit(self.file_index, FileStatus.CANCELLED)
                self.finished_one.emit(self.file_index, False, '用户取消了转换')
                return

            # 验证输出文件
            if result_path and os.path.isfile(result_path):
                self.progress_updated.emit(self.file_index, 100)
                self.status_updated.emit(self.file_index, FileStatus.SUCCESS)
                self.finished_one.emit(self.file_index, True, '转换完成')
            else:
                raise RuntimeError('输出文件未生成')

        except Exception as e:
            if self._cancel_flag[0]:
                self.status_updated.emit(self.file_index, FileStatus.CANCELLED)
                self.finished_one.emit(self.file_index, False, '用户取消了转换')
            else:
                self.status_updated.emit(self.file_index, FileStatus.FAILED)
                self.finished_one.emit(self.file_index, False, str(e))

    def cancel(self) -> None:
        """请求取消转换。"""
        self._cancel_flag[0] = True
        # 如果有正在运行的子进程，立即绞杀
        self.kill_process()

    def kill_process(self) -> None:
        """
        强行终止当前正在运行的底层进程（ffmpeg.exe / WINWORD.EXE）。
        支持从外部调用（如主窗口关闭时批量清理）。
        """
        if self._proc_handle is not None and self._proc_handle.poll() is None:
            try:
                if sys.platform == 'win32':
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(self._proc_handle.pid)],
                        creationflags=CREATE_NO_WINDOW,
                        capture_output=True,
                        timeout=5,
                    )
                else:
                    self._proc_handle.kill()
                self._proc_handle.wait(timeout=5)
            except Exception:
                pass

    # ---------- 内部实现 ----------

    def _do_convert(self) -> str:
        """根据类型派发到具体引擎。"""
        conv_type = self.conv_type

        if conv_type == 'video':
            return convert_video(
                self.input_path,
                self.output_path,
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_flag=self._cancel_flag,
            )
        elif conv_type == 'audio':
            return convert_audio(
                self.input_path,
                self.output_path,
                progress_callback=lambda p: self.progress_updated.emit(self.file_index, p),
                cancel_flag=self._cancel_flag,
            )
        elif conv_type == 'image':
            return convert_image(self.input_path, self.output_path)
        elif conv_type == 'pdf_to_docx':
            return convert_pdf_to_docx(self.input_path, self.output_path)
        elif conv_type == 'docx_to_pdf':
            return convert_docx_to_pdf(self.input_path, self.output_path)
        else:
            raise ValueError(f'不支持的转换类型: {conv_type}')


class BatchManager(QThread):
    """
    批量转换管理器。

    负责协调多个 ConversionWorker 的顺序执行或并发控制。
    目前实现为顺序执行（队列模式），后续可扩展为并发池。

    信号：
    - all_finished: 所有任务完成
    - batch_progress: (completed_count, total_count)
    """

    all_finished = pyqtSignal()
    batch_progress = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks: list[ConversionWorker] = []
        self._current_worker: Optional[ConversionWorker] = None
        self._cancelled = False

    def add_task(self, worker: ConversionWorker) -> None:
        """添加一个转换任务到队列。"""
        self.tasks.append(worker)

    def clear_tasks(self) -> None:
        """清空所有未启动的任务。"""
        self.tasks.clear()

    def run(self) -> None:
        """顺序执行所有任务（线程入口）。"""
        self._cancelled = False
        total = len(self.tasks)
        completed = 0

        for worker in self.tasks:
            if self._cancelled:
                break

            self._current_worker = worker

            # 将 worker 的信号转发（需要在创建线程的线程中连接）
            worker.finished_one.connect(
                lambda idx, success, msg: self._on_task_finished()
            )

            # 启动任务
            worker.start()
            worker.wait()  # 等待当前任务完成（顺序执行）

            if not self._cancelled:
                completed += 1
                self.batch_progress.emit(completed, total)

        self._current_worker = None
        self.all_finished.emit()

    def cancel_all(self) -> None:
        """取消所有任务（包括正在执行的）。"""
        self._cancelled = True
        if self._current_worker is not None:
            self._current_worker.cancel()
        # 也取消掉队列中未执行的任务
        for worker in self.tasks:
            if worker.isRunning():
                worker.cancel()

    def _on_task_finished(self) -> None:
        """单个任务完成回调。"""
        pass


class BatchOrchestrator:
    """
    批量编排器（非 QThread，在主线程使用）。

    管理一组 ConversionWorker，将它们加入线程池并发执行。
    这是推荐的使用方式——每个 worker 独立运行，互不阻塞。
    """

    def __init__(self):
        self.workers: list[ConversionWorker] = []
        self._active_count = 0

    def add_worker(self, worker: ConversionWorker) -> None:
        """添加一个工作线程。"""
        self.workers.append(worker)

    def clear(self) -> None:
        """清理所有已完成的工作线程引用。"""
        # 只移除已完成的
        self.workers = [w for w in self.workers if w.isRunning()]

    def clear_all(self) -> None:
        """清空所有工作线程（不终止）。"""
        self.workers.clear()
        self._active_count = 0

    def start_all(self) -> None:
        """启动所有待执行的工作线程。"""
        for worker in self.workers:
            if not worker.isRunning():
                worker.start()
                self._active_count += 1

    def cancel_all(self) -> None:
        """
        取消所有正在执行的工作线程。
        紧急绞杀所有底层进程。
        """
        for worker in self.workers:
            if worker.isRunning():
                worker.cancel()
        self._active_count = 0

    def active_count(self) -> int:
        """当前正在运行的线程数。"""
        return sum(1 for w in self.workers if w.isRunning())

    def all_finished(self) -> bool:
        """是否所有线程都已结束。"""
        return all(not w.isRunning() for w in self.workers)
