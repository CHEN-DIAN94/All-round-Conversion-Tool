"""
main.py — 全能格式转换工具入口

确保在 Windows 上作为 GUI 应用启动时不带控制台窗口。
"""

import sys
import os

# 确保当前目录在 Python 路径中（PyInstaller 打包后也需要）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 在 Windows 上隐藏控制台（如果以 pythonw.exe 运行则自动隐藏）
if sys.platform == 'win32':
    try:
        import ctypes
        # 获取控制台窗口句柄并隐藏
        kernel32 = ctypes.windll.kernel32
        console_handle = kernel32.GetConsoleWindow()
        if console_handle:
            kernel32.ShowWindow(console_handle, 0)  # SW_HIDE = 0
    except Exception:
        pass

    # 在 QApplication 之前注册 AppUserModelID，
    # 让任务栏图标/名称不再继承 python.exe
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'AllInOneConverter.App'
        )
    except Exception:
        pass


def main():
    """应用程序入口。"""
    from ui import run_app
    run_app()


if __name__ == '__main__':
    main()
