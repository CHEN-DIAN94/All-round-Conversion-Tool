"""
themes — 主题注册表（含动画支持）

定义所有可用主题及其 QSS 文件路径。
支持动画主题：加载 QSS 后自动激活/停止动画效果。
"""

import importlib
from pathlib import Path
import logging

_logger = logging.getLogger(__name__)

THEMES_DIR = Path(__file__).resolve().parent

# 主题注册表：key → (显示名称, QSS 文件名, 描述, 动画模块名或 None)
THEMES = {
    'starfield': ('🌌 星空', 'starfield.qss', '深蓝紫渐变 · 星光粒子 · 蓝紫高光', None),
    'cyberpunk': ('🌃 赛博朋克', 'cyberpunk.qss', '纯黑底 · 青蓝/品红霓虹 · 锐利直角', None),
    'minimal':   ('⬜ 极简白', 'minimal.qss', '纯白底 · 蓝色主色 · macOS 风格', None),
    'cute':      ('💖 可爱', 'cute.qss', '粉紫渐变 · 圆润气泡 · 彩虹微光动画', 'cute_anim'),
    'warm':      ('🔥 温暖', 'warm.qss', '琥珀暖橙 · 柔和光晕 · 萤火虫动画', 'warm_anim'),
}

# 默认主题
DEFAULT_THEME = 'starfield'

# 当前活跃的动画实例（全局，方便 stop）
_current_animator = None


def get_theme_qss(theme_key: str) -> str:
    """读取主题 QSS 内容，失败返回空字符串。"""
    info = THEMES.get(theme_key)
    if not info:
        return ''
    qss_path = THEMES_DIR / info[1]
    try:
        return qss_path.read_text(encoding='utf-8')
    except (OSError, IOError):
        return ''


def get_theme_keys() -> list[str]:
    """返回所有主题 key 列表。"""
    return list(THEMES.keys())


def get_theme_display(theme_key: str) -> str:
    """返回主题显示名称。"""
    info = THEMES.get(theme_key)
    return info[0] if info else theme_key


def has_animation(theme_key: str) -> bool:
    """检查主题是否有动画模块。"""
    info = THEMES.get(theme_key)
    return info is not None and info[3] is not None


def activate_animation(theme_key: str, window) -> None:
    """
    激活主题动画。先停止旧动画，再启动新动画。

    Args:
        theme_key: 主题 key
        window: MainWindow 实例
    """
    global _current_animator

    # 停止旧动画
    stop_current_animation()

    info = THEMES.get(theme_key)
    if not info or not info[3]:
        return

    anim_module_name = info[3]
    try:
        # 动态导入动画模块
        module = importlib.import_module(f'themes.{anim_module_name}')
        animator = module.ThemeAnimator(window)
        animator.start()
        _current_animator = animator
    except (ImportError, AttributeError, Exception) as e:
        _logger.warning('动画加载失败 (%s): %s', anim_module_name, e)


def stop_current_animation() -> None:
    """停止当前活跃的动画。"""
    global _current_animator
    if _current_animator is not None:
        try:
            _current_animator.stop()
        except Exception:
            pass
        _current_animator = None
