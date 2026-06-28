"""
monitor.py — 运行时监控系统

集中捕获 Qt C++ 层的崩溃信号，记录到日志文件。
解决"窗口直接消失但 crash.log 为空"的问题（说明崩溃发生在 Qt C++ 层，
Python 的 try/except 无法捕获）。

功能：
1. 重定向 Qt 消息（qDebug/qWarning/qCritical/qFatal）到日志
2. 记录所有 QThread 的启动/退出/未捕获异常
3. 在关键操作点写入带时间戳的 trace 日志
4. faulthandler 短间隔轮询，捕获段错误位置
"""

from __future__ import annotations

import os
import sys
import faulthandler
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

_LOG_DIR = Path(__file__).resolve().parent / 'logs'
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 监控专用日志（与业务日志分开，便于排查崩溃）
_MONITOR_LOG = _LOG_DIR / 'monitor.log'
_trace_file = None


def _ts() -> str:
    """带毫秒的时间戳。"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def monitor_log(msg: str) -> None:
    """写入一条监控日志（同步、立即刷新）。"""
    try:
        line = f'[{_ts()}] [tid={threading.get_ident()}] {msg}\n'
        with _MONITOR_LOG.open('a', encoding='utf-8') as f:
            f.write(line)
            f.flush()
    except Exception:
        pass  # 日志失败不影响主流程


def trace(tag: str, **kwargs) -> None:
    """
    记录关键操作 trace。

    用法：
        from monitor import trace
        trace('convert.start', file=input_path, row=file_index)
        trace('convert.done', file=input_path, success=True)

    Args:
        tag: 操作标签，用点号分层（如 'worker.run.start'）
        **kwargs: 附加上下文（自动格式化为 key=value）
    """
    extras = ' '.join(f'{k}={v!r}' for k, v in kwargs.items())
    monitor_log(f'TRACE {tag} {extras}' if extras else f'TRACE {tag}')


# ==============================================================
# Qt 消息重定向
# ==============================================================

def install_qt_message_handler() -> None:
    """
    捕获 Qt 的所有消息（qDebug/qWarning/qCritical/qFatal）。

    Qt C++ 层崩溃前通常会先输出 qWarning 或 qCritical。
    """
    try:
        from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
    except ImportError:
        return

    def _handler(msg_type, context, message):
        try:
            level = {
                QtMsgType.QtDebugMsg: 'DEBUG',
                QtMsgType.QtInfoMsg: 'INFO',
                QtMsgType.QtWarningMsg: 'WARN',
                QtMsgType.QtCriticalMsg: 'CRITICAL',
                QtMsgType.QtFatalMsg: 'FATAL',
            }.get(msg_type, 'UNKNOWN')

            # Qt 警告及以上全部记录（含段错误前的最后一条）
            if msg_type >= QtMsgType.QtWarningMsg:
                # 尝试获取文件/行号
                file = ''
                line = 0
                try:
                    file = context.file or ''
                    line = context.line or 0
                except Exception:
                    pass
                loc = f' {file}:{line}' if file else ''
                monitor_log(f'QT.{level}{loc} | {message}')

                # FATAL 立即 dump 全线程堆栈
                if msg_type == QtMsgType.QtFatalMsg:
                    monitor_log('!!! Qt FATAL — dumping all threads !!!')
                    try:
                        if _trace_file:
                            faulthandler.dump_traceback(_trace_file, all_threads=True)
                            _trace_file.flush()
                    except Exception:
                        pass
        except Exception:
            pass  # 处理器自身不能崩

    qInstallMessageHandler(_handler)
    monitor_log('Qt message handler installed')


# ==============================================================
# faulthandler 配置
# ==============================================================

def setup_faulthandler(timeout_sec: int = 30) -> None:
    """
    配置 faulthandler：
    - 所有线程的段错误立即写到 monitor.log
    - 每 timeout_sec 秒 dump 一次（检测死锁/卡死）
    """
    global _trace_file
    try:
        _trace_file = _MONITOR_LOG.open('a', encoding='utf-8')
        faulthandler.enable(file=_trace_file, all_threads=True)
        # 短间隔轮询：30 秒一次，重复
        faulthandler.dump_traceback_later(timeout_sec, repeat=True, file=_trace_file)
        monitor_log(f'faulthandler enabled (timeout={timeout_sec}s)')
    except Exception as e:
        monitor_log(f'faulthandler setup failed: {e}')


# ==============================================================
# 线程追踪
# ==============================================================

class TracedThread(threading.Thread):
    """
    带 trace 的线程包装。

    自动记录：
    - 线程启动
    - 未捕获异常（含完整堆栈）
    - 线程退出
    """

    def __init__(self, *args, name: str = '', **kwargs):
        super().__init__(*args, **kwargs)
        self._trace_name = name or self.name

    def run(self) -> None:
        trace('thread.run.start', name=self._trace_name, tid=threading.get_ident())
        try:
            super().run()
            trace('thread.run.done', name=self._trace_name)
        except SystemExit:
            trace('thread.run.exit', name=self._trace_name)
            raise
        except Exception:
            # 完整堆栈写到 monitor.log
            tb = traceback.format_exc()
            monitor_log(f'!!! Thread {self._trace_name} crashed !!!\n{tb}')
            trace('thread.run.crash', name=self._trace_name)
            raise


# ==============================================================
# QThread 安全监控
# ==============================================================

def patch_qthread() -> None:
    """
    给 QThread.run 打补丁，自动记录：
    - 启动
    - 退出
    - 未捕获异常（含堆栈）

    这样无需修改每个 worker 的代码即可监控所有 QThread。
    """
    try:
        from PyQt6.QtCore import QThread
    except ImportError:
        return

    _orig_run = QThread.run

    def _traced_run(self):
        cls_name = self.__class__.__name__
        tid = threading.get_ident()
        trace('QThread.run.start', cls=cls_name, tid=tid)
        try:
            _orig_run(self)
            trace('QThread.run.done', cls=cls_name)
        except Exception:
            tb = traceback.format_exc()
            monitor_log(f'!!! QThread {cls_name} crashed !!!\n{tb}')
            trace('QThread.run.crash', cls=cls_name)
            raise

    QThread.run = _traced_run
    monitor_log('QThread.run patched for tracing')


# ==============================================================
# widget 销毁追踪
# ==============================================================

def track_widget_destroy(name: str, obj) -> None:
    """
    跟踪 widget 销毁。

    用法：
        from monitor import track_widget_destroy
        track_widget_destroy('MainWindow', self)
    """
    try:
        import weakref
        ref = weakref.ref(obj, lambda r, n=name: trace('widget.destroyed', name=n))
        # 保存引用防止被 GC
        if not hasattr(track_widget_destroy, '_refs'):
            track_widget_destroy._refs = []
        track_widget_destroy._refs.append(ref)
    except Exception:
        pass


# ==============================================================
# 启动横幅
# ==============================================================

def banner(version: str = '') -> None:
    """写入启动横幅，便于在日志中定位运行边界。"""
    try:
        with _MONITOR_LOG.open('a', encoding='utf-8') as f:
            f.write('\n' + '=' * 70 + '\n')
            f.write(f'流光启动 @ {_ts()}\n')
            f.write(f'python={sys.version.split()[0]} platform={sys.platform}\n')
            f.write(f'exe={sys.executable}\n')
            f.write(f'cwd={os.getcwd()}\n')
            if version:
                f.write(f'version={version}\n')
            f.write(f'frozen={getattr(sys, "frozen", False)}\n')
            f.write('=' * 70 + '\n\n')
            f.flush()
    except Exception:
        pass


def start_monitoring(version: str = '') -> None:
    """一站式启动所有监控。在 main.py 入口调用。"""
    banner(version)
    setup_faulthandler(timeout_sec=30)
    install_qt_message_handler()
    patch_qthread()
    monitor_log('=== monitor started ===')
