"""
constants.py — 全局常量定义

所有 magic number、版本号、默认参数统一在此管理。
只放**真正被多处引用**的常量，避免"定义了但没人用"的死代码。
"""

__all__ = [
    'VERSION',
    'MAX_FILES_PER_BATCH',
    'MAX_CANVAS_PIXELS',
    'WINDOW_MIN_WIDTH', 'WINDOW_MIN_HEIGHT',
    'WINDOW_DEFAULT_WIDTH', 'WINDOW_DEFAULT_HEIGHT',
    'SHUTDOWN_WAIT_MS',
    'FileStatus',
]

# 版本信息
VERSION = '1.1.0'

# 文件限制
MAX_FILES_PER_BATCH = 500
MAX_CANVAS_PIXELS = 4096 * 4096  # ~48MB (RGB)

# UI 参数（实际被 ui.py 使用的）
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 720
WINDOW_DEFAULT_WIDTH = 1060
WINDOW_DEFAULT_HEIGHT = 760
# 优雅退出等待时间（毫秒）
SHUTDOWN_WAIT_MS = 5000


class FileStatus:
    """文件转换状态（UI 层使用）"""
    WAITING = '等待中'
    CONVERTING = '转换中'
    SUCCESS = '成功'
    FAILED = '失败'
    CANCELLED = '已取消'
