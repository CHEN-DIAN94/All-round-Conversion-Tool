"""
queue_manager.py — 转换队列管理系统

支持：
- 动态追加任务
- 暂停/恢复单个任务
- 拖拽排序
- 任务状态查询
"""

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Optional


@dataclass
class FileTask:
    """文件转换任务"""
    file_path: str
    output_path: str
    conv_type: str
    params: dict = field(default_factory=dict)
    status: str = 'pending'  # pending, active, completed, failed, cancelled
    error: Optional[str] = None
    progress: int = 0


class ConversionQueue:
    """
    转换队列，支持动态操作。

    线程安全，所有公共方法都通过锁保护。
    """

    def __init__(self, max_concurrency: int = 4):
        self._pending: deque[FileTask] = deque()
        self._active: dict[str, FileTask] = {}  # file_path -> task
        self._completed: list[FileTask] = []
        self._lock = Lock()
        self._max_concurrency = max_concurrency

    @property
    def pending_count(self) -> int:
        """待执行任务数。"""
        return len(self._pending)

    @property
    def active_count(self) -> int:
        """正在执行任务数。"""
        return len(self._active)

    @property
    def completed_count(self) -> int:
        """已完成任务数。"""
        return len(self._completed)

    @property
    def total_count(self) -> int:
        """总任务数。"""
        return self.pending_count + self.active_count + self.completed_count

    def enqueue(self, tasks: list[FileTask]) -> int:
        """
        追加任务到队列。

        Returns:
            实际追加的任务数（去重后）。
        """
        added = 0
        with self._lock:
            for task in tasks:
                # 去重：跳过已存在的任务
                if task.file_path in self._active:
                    continue
                if any(t.file_path == task.file_path for t in self._pending):
                    continue
                if any(t.file_path == task.file_path for t in self._completed):
                    continue
                self._pending.append(task)
                added += 1
        return added

    def dequeue(self) -> Optional[FileTask]:
        """
        取出下一个待执行任务。

        Returns:
            FileTask 或 None（无待执行任务或已达并发上限）。
        """
        with self._lock:
            if self._pending and len(self._active) < self._max_concurrency:
                task = self._pending.popleft()
                task.status = 'active'
                self._active[task.file_path] = task
                return task
            return None

    def complete(self, file_path: str, status: str, error: Optional[str] = None):
        """
        标记任务完成。

        Args:
            file_path: 文件路径
            status: 最终状态 ('completed', 'failed', 'cancelled')
            error: 错误信息（失败时）
        """
        with self._lock:
            task = self._active.pop(file_path, None)
            if task:
                task.status = status
                task.error = error
                task.progress = 100 if status == 'completed' else task.progress
                self._completed.append(task)

    def update_progress(self, file_path: str, progress: int):
        """更新任务进度。"""
        with self._lock:
            task = self._active.get(file_path)
            if task:
                task.progress = progress

    def reorder(self, from_idx: int, to_idx: int):
        """
        调整待执行队列顺序。

        Args:
            from_idx: 源索引
            to_idx: 目标索引
        """
        with self._lock:
            if 0 <= from_idx < len(self._pending) and 0 <= to_idx < len(self._pending):
                task = self._pending[from_idx]
                del self._pending[from_idx]
                self._pending.insert(to_idx, task)

    def pause_task(self, file_path: str) -> bool:
        """
        暂停任务（移回待执行队列头部）。

        Returns:
            是否成功暂停。
        """
        with self._lock:
            task = self._active.pop(file_path, None)
            if task:
                task.status = 'pending'
                task.progress = 0
                self._pending.appendleft(task)
                return True
            return False

    def remove_task(self, file_path: str) -> bool:
        """
        移除任务。

        Returns:
            是否成功移除。
        """
        with self._lock:
            # 从待执行队列移除
            original_len = len(self._pending)
            self._pending = deque(t for t in self._pending if t.file_path != file_path)
            if len(self._pending) < original_len:
                return True

            # 从活跃队列移除
            if file_path in self._active:
                del self._active[file_path]
                return True

            return False

    def clear_pending(self):
        """清空待执行队列。"""
        with self._lock:
            self._pending.clear()

    def clear_all(self):
        """清空所有队列（不包括正在执行的任务）。"""
        with self._lock:
            self._pending.clear()
            self._completed.clear()

    def get_pending_tasks(self) -> list[FileTask]:
        """获取待执行任务列表。"""
        with self._lock:
            return list(self._pending)

    def get_active_tasks(self) -> list[FileTask]:
        """获取正在执行任务列表。"""
        with self._lock:
            return list(self._active.values())

    def get_completed_tasks(self) -> list[FileTask]:
        """获取已完成任务列表。"""
        with self._lock:
            return list(self._completed)

    def get_all_tasks(self) -> list[FileTask]:
        """获取所有任务（用于 UI 显示）。"""
        with self._lock:
            return list(self._pending) + list(self._active.values()) + self._completed

    def get_task(self, file_path: str) -> Optional[FileTask]:
        """根据文件路径获取任务。"""
        with self._lock:
            # 先查活跃队列
            task = self._active.get(file_path)
            if task:
                return task

            # 再查待执行队列
            for task in self._pending:
                if task.file_path == file_path:
                    return task

            # 最后查已完成队列
            for task in self._completed:
                if task.file_path == file_path:
                    return task

            return None
