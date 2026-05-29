"""
tests.test_queue_manager.py — 转换队列管理系统测试

覆盖：
- 入队/出队
- 去重
- 完成/失败/取消
- 进度更新
- 重排序
- 暂停/恢复
- 移除任务
"""

import pytest
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from queue_manager import ConversionQueue, FileTask


class TestEnqueueDequeue:
    """入队/出队测试"""

    def test_enqueue_single(self):
        """单个任务入队"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')

        added = queue.enqueue([task])

        assert added == 1
        assert queue.pending_count == 1

    def test_enqueue_multiple(self):
        """多个任务入队"""
        queue = ConversionQueue()
        tasks = [
            FileTask(f'input{i}.mp4', f'output{i}.mp4', 'video')
            for i in range(5)
        ]

        added = queue.enqueue(tasks)

        assert added == 5
        assert queue.pending_count == 5

    def test_enqueue_dedup(self):
        """重复任务入队应去重"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')

        queue.enqueue([task])
        added = queue.enqueue([task])

        assert added == 0
        assert queue.pending_count == 1

    def test_dequeue_basic(self):
        """基本出队"""
        queue = ConversionQueue(max_concurrency=4)
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])

        dequeued = queue.dequeue()

        assert dequeued is not None
        assert dequeued.file_path == 'input.mp4'
        assert dequeued.status == 'active'
        assert queue.pending_count == 0
        assert queue.active_count == 1

    def test_dequeue_empty(self):
        """空队列出队返回 None"""
        queue = ConversionQueue()

        dequeued = queue.dequeue()

        assert dequeued is None

    def test_dequeue_concurrency_limit(self):
        """达到并发上限时出队返回 None"""
        queue = ConversionQueue(max_concurrency=2)
        tasks = [
            FileTask(f'input{i}.mp4', f'output{i}.mp4', 'video')
            for i in range(5)
        ]
        queue.enqueue(tasks)

        # 出队 2 个（达到上限）
        queue.dequeue()
        queue.dequeue()

        # 第 3 个应返回 None
        dequeued = queue.dequeue()
        assert dequeued is None
        assert queue.pending_count == 3


class TestComplete:
    """完成测试"""

    def test_complete_success(self):
        """成功完成"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        queue.complete('input.mp4', 'completed')

        assert queue.active_count == 0
        assert queue.completed_count == 1
        assert queue.get_completed_tasks()[0].status == 'completed'
        assert queue.get_completed_tasks()[0].progress == 100

    def test_complete_failure(self):
        """失败完成"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        queue.complete('input.mp4', 'failed', error='转换失败')

        assert queue.active_count == 0
        assert queue.completed_count == 1
        assert queue.get_completed_tasks()[0].status == 'failed'
        assert queue.get_completed_tasks()[0].error == '转换失败'

    def test_complete_cancelled(self):
        """取消完成"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        queue.complete('input.mp4', 'cancelled')

        assert queue.active_count == 0
        assert queue.completed_count == 1
        assert queue.get_completed_tasks()[0].status == 'cancelled'


class TestProgress:
    """进度测试"""

    def test_update_progress(self):
        """更新进度"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        queue.update_progress('input.mp4', 50)

        assert queue.get_task('input.mp4').progress == 50

    def test_update_progress_nonexistent(self):
        """更新不存在的任务进度"""
        queue = ConversionQueue()

        # 不应抛出异常
        queue.update_progress('nonexistent.mp4', 50)


class TestReorder:
    """重排序测试"""

    def test_reorder_basic(self):
        """基本重排序"""
        queue = ConversionQueue()
        tasks = [
            FileTask(f'input{i}.mp4', f'output{i}.mp4', 'video')
            for i in range(5)
        ]
        queue.enqueue(tasks)

        queue.reorder(0, 4)

        pending = queue.get_pending_tasks()
        assert pending[0].file_path == 'input1.mp4'
        assert pending[4].file_path == 'input0.mp4'

    def test_reorder_invalid_index(self):
        """无效索引重排序"""
        queue = ConversionQueue()
        tasks = [
            FileTask(f'input{i}.mp4', f'output{i}.mp4', 'video')
            for i in range(3)
        ]
        queue.enqueue(tasks)

        # 不应抛出异常
        queue.reorder(-1, 0)
        queue.reorder(0, 10)


class TestPause:
    """暂停测试"""

    def test_pause_active_task(self):
        """暂停活跃任务"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        result = queue.pause_task('input.mp4')

        assert result is True
        assert queue.active_count == 0
        assert queue.pending_count == 1
        assert queue.get_pending_tasks()[0].status == 'pending'

    def test_pause_nonexistent_task(self):
        """暂停不存在的任务"""
        queue = ConversionQueue()

        result = queue.pause_task('nonexistent.mp4')

        assert result is False


class TestRemove:
    """移除测试"""

    def test_remove_pending_task(self):
        """移除待执行任务"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])

        result = queue.remove_task('input.mp4')

        assert result is True
        assert queue.pending_count == 0

    def test_remove_active_task(self):
        """移除活跃任务"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        result = queue.remove_task('input.mp4')

        assert result is True
        assert queue.active_count == 0

    def test_remove_nonexistent_task(self):
        """移除不存在的任务"""
        queue = ConversionQueue()

        result = queue.remove_task('nonexistent.mp4')

        assert result is False


class TestClear:
    """清空测试"""

    def test_clear_pending(self):
        """清空待执行队列"""
        queue = ConversionQueue()
        tasks = [
            FileTask(f'input{i}.mp4', f'output{i}.mp4', 'video')
            for i in range(5)
        ]
        queue.enqueue(tasks)

        queue.clear_pending()

        assert queue.pending_count == 0

    def test_clear_all(self):
        """清空所有队列"""
        queue = ConversionQueue()
        tasks = [
            FileTask(f'input{i}.mp4', f'output{i}.mp4', 'video')
            for i in range(5)
        ]
        queue.enqueue(tasks)
        queue.dequeue()  # input0 变成 active

        queue.clear_all()

        assert queue.pending_count == 0
        assert queue.completed_count == 0
        # 活跃任务不受影响
        assert queue.active_count == 1


class TestGetTask:
    """获取任务测试"""

    def test_get_pending_task(self):
        """获取待执行任务"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])

        result = queue.get_task('input.mp4')

        assert result is not None
        assert result.file_path == 'input.mp4'

    def test_get_active_task(self):
        """获取活跃任务"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()

        result = queue.get_task('input.mp4')

        assert result is not None
        assert result.status == 'active'

    def test_get_completed_task(self):
        """获取已完成任务"""
        queue = ConversionQueue()
        task = FileTask('input.mp4', 'output.mp4', 'video')
        queue.enqueue([task])
        queue.dequeue()
        queue.complete('input.mp4', 'completed')

        result = queue.get_task('input.mp4')

        assert result is not None
        assert result.status == 'completed'

    def test_get_nonexistent_task(self):
        """获取不存在的任务"""
        queue = ConversionQueue()

        result = queue.get_task('nonexistent.mp4')

        assert result is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
