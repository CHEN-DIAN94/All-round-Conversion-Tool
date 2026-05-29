"""
main.py — 全能格式转换工具入口

确保在 Windows 上作为 GUI 应用启动时不带控制台窗口。
"""

import os
import sys
import traceback
from pathlib import Path

# 确保当前目录在 Python 路径中（PyInstaller 打包后也需要）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

_log_dir = Path(current_dir) / 'logs'
_log_dir.mkdir(exist_ok=True)
_crash_log_path = _log_dir / 'crash.log'
_launch_log_path = _log_dir / 'launch.log'
_dump_path = _log_dir / 'crash_dump.log'


def _append_launch_log(message: str) -> None:
    with _launch_log_path.open('a', encoding='utf-8') as f:
        f.write(message + '\n')


def _write_crash_log(exc_info) -> str:
    with _crash_log_path.open('a', encoding='utf-8') as f:
        f.write('=== crash ===\n')
        f.write(''.join(traceback.format_exception(*exc_info)))
        f.write('\n')
    return str(_crash_log_path)


def _enable_faulthandler() -> None:
    try:
        import atexit
        import faulthandler
        # L-03: faulthandler 使用独立文件，不与 crash dump 混用
        _faulthandler_path = _log_dir / 'crash_traceback.log'
        fh = _faulthandler_path.open('a', encoding='utf-8')
        faulthandler.enable(file=fh, all_threads=True)
        faulthandler.dump_traceback_later(120, repeat=True, file=fh)
        # L-04: 注册 atexit 关闭文件句柄
        atexit.register(fh.close)
        sys._crash_fh = fh  # keep alive
    except Exception:
        pass


def _enable_windows_crash_dump() -> None:
    try:
        import ctypes
        from ctypes import wintypes

        DBGHELP = ctypes.windll.DbgHelp
        KERNEL32 = ctypes.windll.kernel32

        # S-02: 去掉 MiniDumpWithFullMemory（隐私风险），仅保留必要信息
        MiniDumpWithHandleData = 0x00000004
        MiniDumpWithThreadInfo = 0x00001000
        MiniDumpWithUnloadedModules = 0x00000020
        dump_flags = (
            MiniDumpWithHandleData
            | MiniDumpWithThreadInfo
            | MiniDumpWithUnloadedModules
        )

        class EXCEPTION_POINTERS(ctypes.Structure):
            _fields_ = [('Unused', ctypes.c_void_p)]

        _UnhandledExceptionFilter = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
        _MiniDumpWriteDump = DBGHELP.MiniDumpWriteDump
        _MiniDumpWriteDump.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        _MiniDumpWriteDump.restype = wintypes.BOOL

        def _dump_exception(exc_ptr):
            try:
                pid = KERNEL32.GetCurrentProcessId()
                process = KERNEL32.GetCurrentProcess()
                h_file = KERNEL32.CreateFileW(
                    str(_dump_path),
                    0x40000000,
                    0,
                    None,
                    2,
                    0x80,
                    None,
                )
                if h_file and h_file != wintypes.HANDLE(-1).value:
                    _MiniDumpWriteDump(process, pid, h_file, dump_flags, None, None, None)
                    KERNEL32.CloseHandle(h_file)
            except Exception:
                pass
            return 1

        _handler = _UnhandledExceptionFilter(_dump_exception)
        KERNEL32.SetUnhandledExceptionFilter(_handler)
        sys._crash_handler = _handler
    except Exception:
        pass


if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

_append_launch_log('launcher start')
_enable_faulthandler()
_enable_windows_crash_dump()

if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        console_handle = kernel32.GetConsoleWindow()
        if console_handle:
            kernel32.ShowWindow(console_handle, 0)
    except Exception:
        pass


def main():
    """应用程序入口。"""
    try:
        _append_launch_log('import ui')
        from ui import run_app
        _append_launch_log('run_app enter')
        run_app()
        _append_launch_log('run_app exit')
    except Exception:
        _write_crash_log(sys.exc_info())
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception:
        _write_crash_log(sys.exc_info())
        raise
