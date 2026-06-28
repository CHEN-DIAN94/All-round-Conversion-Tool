"""
widgets.py — 自定义 PyQt6 Widget

从 ui.py 提取的可复用 widget 类，包括：
- DropableTableWidget: 拖拽文件表格
- StatusColorDelegate: 状态列彩色绘制
- ErrorDetailDialog: 错误详情对话框
- AdvancedSettingsPanel: 高级参数设置面板
- PreviewPanel: 文件预览面板（图片/视频封面）
"""


__all__ = ['DropableTableWidget', 'StatusColorDelegate', 'ErrorDetailDialog', 'AdvancedSettingsPanel', 'PreviewPanel', 'ToolPanel', 'HistoryDialog', 'PresetCombo']

import os
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QThread
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QFont, QPainter, QPixmap, QImage
from PyQt6.QtWidgets import (
    QTableWidget, QStyledItemDelegate, QStyle,
    QDialog, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QApplication, QLabel, QWidget,
    QGroupBox, QFormLayout, QSpinBox, QComboBox,
    QCheckBox, QSlider, QSizePolicy,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QStackedWidget,
)

from formats import STATUS_COLORS, _collect_files_from_paths
from utils import get_ffmpeg_path, CREATE_NO_WINDOW


# ==============================================================
# DropableTableWidget — 拖拽文件表格
# ==============================================================

class DropableTableWidget(QTableWidget):
    """支持拖拽文件放入的 QTableWidget。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self._parent_window = parent

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            raw_paths = []
            for url in event.mimeData().urls():
                raw_paths.append(url.toLocalFile())
            files = _collect_files_from_paths(raw_paths)
            if files and self._parent_window:
                self._parent_window.add_files_to_table(files)
            event.acceptProposedAction()


# ==============================================================
# StatusColorDelegate — 状态列彩色绘制
# ==============================================================

class StatusColorDelegate(QStyledItemDelegate):
    """
    为状态列绘制彩色文本（主题感知）。

    深色模式下使用高对比度颜色（WCAG AA ≥ 4.5:1），
    避免状态文字在深色背景上不可见。
    """

    # 深色模式下的状态颜色映射（对比度 ≥ 4.5:1 on #2a2a3e）
    _DARK_STATUS_COLORS = {
        '等待中':  '#94a3b8',
        '转换中':  '#38bdf8',
        '成功':    '#4ade80',
        '失败':    '#f87171',
        '已取消':  '#fbbf24',
    }

    @staticmethod
    def _is_dark_theme() -> bool:
        """检测当前是否为深色主题（通过 palette 背景色亮度判断）。"""
        from PyQt6.QtWidgets import QApplication
        bg = QApplication.palette().window().color()
        return (bg.red() * 299 + bg.green() * 587 + bg.blue() * 114) / 1000 < 128

    def paint(self, painter: QPainter, option, index) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ''

        # 根据主题选择颜色映射
        if self._is_dark_theme():
            color = self._DARK_STATUS_COLORS.get(text, '#a0a0c0')
            selected_bg = QColor('#3a3a5e')
        else:
            color = STATUS_COLORS.get(text, '#1F1F1F')
            selected_bg = QColor('#E5F1FB')

        painter.save()
        # 选中态背景
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, selected_bg)

        painter.setPen(QColor(color))
        font = painter.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        # 绘制圆角标签背景
        text_rect = option.rect.adjusted(6, 2, -6, -2)
        bg_color = QColor(color)
        bg_color.setAlpha(25)
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(text_rect, 4, 4)

        painter.setPen(QColor(color))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


# ==============================================================
# ErrorDetailDialog — 错误详情对话框
# ==============================================================

class ErrorDetailDialog(QDialog):
    """错误详情对话框，支持复制错误信息和文件路径。"""

    def __init__(self, file_path: str, error_msg: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.error_msg = error_msg
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle('转换失败详情')
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)

        # 文件路径
        path_label = QLabel(f'文件: {self.file_path}')
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_label)

        # 错误信息
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.error_msg)
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont('Consolas', 10))
        layout.addWidget(self.text_edit)

        # 按钮栏
        btn_layout = QHBoxLayout()

        btn_copy = QPushButton('复制错误信息')
        btn_copy.clicked.connect(self._copy_error)
        btn_layout.addWidget(btn_copy)

        btn_copy_path = QPushButton('复制文件路径')
        btn_copy_path.clicked.connect(self._copy_path)
        btn_layout.addWidget(btn_copy_path)

        btn_layout.addStretch()

        btn_close = QPushButton('关闭')
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _copy_error(self):
        QApplication.clipboard().setText(self.error_msg)

    def _copy_path(self):
        QApplication.clipboard().setText(self.file_path)


# ==============================================================
# AdvancedSettingsPanel — 高级参数设置面板
# ==============================================================

class AdvancedSettingsPanel(QDialog):
    """
    高级参数设置对话框（弹窗）。

    支持视频/音频/图片参数调整，提供快速预设。
    """

    # 默认值
    DEFAULTS = {
        'video_crf': 23,
        'video_preset': 'medium',
        'audio_bitrate': '192k',
        'audio_sample_rate': 44100,
        'image_quality': 95,
        'image_resize': 100,
    }

    # 预设
    PRESETS = {
        '高质量': {'video_crf': 18, 'video_preset': 'slow', 'audio_bitrate': '320k'},
        '均衡': {'video_crf': 23, 'video_preset': 'medium', 'audio_bitrate': '192k'},
        '小体积': {'video_crf': 28, 'video_preset': 'fast', 'audio_bitrate': '128k'},
    }

    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = self.DEFAULTS.copy()
        self.setWindowTitle('高级设置')
        self.setMinimumSize(500, 400)
        self.setModal(False)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 预设选择
        preset_group = QGroupBox('快速预设')
        preset_layout = QHBoxLayout(preset_group)
        preset_layout.setSpacing(8)

        for preset_name in self.PRESETS:
            btn = QPushButton(preset_name)
            btn.setMinimumHeight(36)
            btn.clicked.connect(lambda checked, name=preset_name: self._apply_preset(name))
            preset_layout.addWidget(btn)

        layout.addWidget(preset_group)

        # 视频参数
        video_group = QGroupBox('视频参数')
        video_layout = QFormLayout(video_group)
        video_layout.setSpacing(8)

        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 51)
        self.crf_spin.setValue(self._settings['video_crf'])
        self.crf_spin.setMinimumHeight(36)
        self.crf_spin.setToolTip('CRF 值越低，质量越高，文件越大（推荐: 18-28）')
        video_layout.addRow('CRF 质量:', self.crf_spin)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            'ultrafast', 'superfast', 'veryfast', 'faster',
            'fast', 'medium', 'slow', 'slower', 'veryslow',
        ])
        self.preset_combo.setMinimumHeight(36)
        self.preset_combo.setCurrentText(self._settings['video_preset'])
        self.preset_combo.setToolTip('编码速度，越慢质量越高')
        video_layout.addRow('编码预设:', self.preset_combo)

        layout.addWidget(video_group)

        # 音频参数
        audio_group = QGroupBox('音频参数')
        audio_layout = QFormLayout(audio_group)
        audio_layout.setSpacing(8)

        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(['96k', '128k', '160k', '192k', '256k', '320k'])
        self.bitrate_combo.setMinimumHeight(36)
        self.bitrate_combo.setCurrentText(self._settings['audio_bitrate'])
        audio_layout.addRow('比特率:', self.bitrate_combo)

        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(['22050', '44100', '48000', '96000'])
        self.sample_rate_combo.setMinimumHeight(36)
        self.sample_rate_combo.setCurrentText(str(self._settings['audio_sample_rate']))
        audio_layout.addRow('采样率:', self.sample_rate_combo)

        layout.addWidget(audio_group)

        # 图片参数
        image_group = QGroupBox('图片参数')
        image_layout = QFormLayout(image_group)
        image_layout.setSpacing(8)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(self._settings['image_quality'])
        self.quality_spin.setMinimumHeight(36)
        image_layout.addRow('质量:', self.quality_spin)

        self.resize_spin = QSpinBox()
        self.resize_spin.setRange(1, 1000)
        self.resize_spin.setValue(self._settings['image_resize'])
        self.resize_spin.setMinimumHeight(36)
        self.resize_spin.setSuffix('%')
        image_layout.addRow('缩放:', self.resize_spin)

        layout.addWidget(image_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_reset = QPushButton('恢复默认')
        btn_reset.setMinimumHeight(36)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_apply = QPushButton('应用')
        btn_apply.setMinimumHeight(36)
        btn_apply.clicked.connect(self._emit_settings)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

    def _apply_preset(self, name: str):
        """应用预设。"""
        preset = self.PRESETS[name]
        self._settings.update(preset)
        self._update_ui()

    def _reset_defaults(self):
        """恢复默认。"""
        self._settings = self.DEFAULTS.copy()
        self._update_ui()

    def _update_ui(self):
        """更新 UI 控件。"""
        self.crf_spin.setValue(self._settings['video_crf'])
        self.preset_combo.setCurrentText(self._settings['video_preset'])
        self.bitrate_combo.setCurrentText(self._settings['audio_bitrate'])
        self.sample_rate_combo.setCurrentText(str(self._settings['audio_sample_rate']))
        self.quality_spin.setValue(self._settings['image_quality'])
        self.resize_spin.setValue(self._settings['image_resize'])

    def _emit_settings(self):
        """发射设置变更信号。"""
        self._settings['video_crf'] = self.crf_spin.value()
        self._settings['video_preset'] = self.preset_combo.currentText()
        self._settings['audio_bitrate'] = self.bitrate_combo.currentText()
        self._settings['audio_sample_rate'] = int(self.sample_rate_combo.currentText())
        self._settings['image_quality'] = self.quality_spin.value()
        self._settings['image_resize'] = self.resize_spin.value()

        self.settings_changed.emit(self._settings)

    def get_settings(self) -> dict:
        """获取当前设置。"""
        return self._settings.copy()

    def set_settings(self, settings: dict):
        """外部设置参数。"""
        self._settings.update(settings)
        self._update_ui()


# ==============================================================
# PreviewPanel — 文件预览面板
# ==============================================================

# 图片和视频扩展名
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif', '.webp', '.ico', '.heic', '.heif'}
_VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.3gp', '.ogv', '.m2ts', '.vob'}


def _safe_load_pixmap(file_path: str) -> QPixmap:
    """
    安全加载 QPixmap。

    直接 QPixmap(path) 在文件损坏或正被写入时可能段错误。
    改为先用 QImage 加载（更安全），再转 QPixmap。
    """
    if not file_path or not os.path.isfile(file_path):
        return QPixmap()
    try:
        if os.path.getsize(file_path) == 0:
            return QPixmap()
        img = QImage(file_path)
        if img.isNull():
            return QPixmap()
        return QPixmap.fromImage(img)
    except Exception:
        return QPixmap()


class _ThumbnailExtractor(QThread):
    """后台提取视频第一帧，避免阻塞主线程。"""
    finished_ok = pyqtSignal(str, QPixmap)  # (request_path, pixmap)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self._file_path = file_path

    def run(self) -> None:
        pixmap = self._extract(self._file_path)
        # 发射前检查 pixmap 是否有效
        if not pixmap.isNull():
            self.finished_ok.emit(self._file_path, pixmap)

    @staticmethod
    def _extract(file_path: str) -> QPixmap:
        """用 ffmpeg 提取视频第一帧。"""
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            return QPixmap()
        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            cmd = [
                ffmpeg, '-y',
                '-i', file_path,
                '-vframes', '1',
                '-q:v', '2',
                tmp_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if result.returncode == 0 and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                return _safe_load_pixmap(tmp_path)
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return QPixmap()


class PreviewPanel(QWidget):
    """
    文件预览面板。

    选中文件时自动显示预览：
    - 图片：直接显示
    - 视频：提取第一帧显示
    - 其他：显示文件类型图标
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = ''
        self._thumbnail_cache: dict[str, QPixmap] = {}  # path -> QPixmap 缓存
        self._preview_label_style = ''
        self._empty_icon_text = '🖼'
        self._generic_icon_font_size = 48
        self._empty_icon_font_size = 32
        self._pending_video_path = ''
        self._thumbnail_thread: _ThumbnailExtractor | None = None
        self._init_ui()

    def _init_ui(self):
        self.setObjectName('PreviewPanel')
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 预览标签
        self._preview_label = QLabel()
        self._preview_label.setObjectName('PreviewLabel')
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(100)
        self._preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview_label.setText(self._empty_icon_text)
        layout.addWidget(self._preview_label)

        # 文件信息标签
        self._info_label = QLabel('选中文件以预览')
        self._info_label.setObjectName('PreviewInfo')
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info_label)

        # 默认状态
        self._show_empty()

    def _show_empty(self):
        """显示空状态。"""
        self._preview_label.setPixmap(QPixmap())
        self._preview_label.setText(self._empty_icon_text)
        self._preview_label.setProperty('previewState', 'empty')
        self._refresh_preview_label_style()
        self._info_label.setText('选中文件以预览')

    def _refresh_preview_label_style(self):
        """根据当前状态刷新预览标签样式。"""
        state = self._preview_label.property('previewState') or 'default'
        if state == 'empty':
            self._preview_label_style = f'font-size: {self._empty_icon_font_size}pt;'
        elif state == 'icon':
            self._preview_label_style = f'font-size: {self._generic_icon_font_size}pt;'
        else:
            self._preview_label_style = ''
        self._preview_label.setStyleSheet(self._preview_label_style)
        self._preview_label.style().unpolish(self._preview_label)
        self._preview_label.style().polish(self._preview_label)
        self._preview_label.update()

    def preview_file(self, file_path: str) -> None:
        """预览指定文件。"""
        if not file_path or not os.path.isfile(file_path):
            self._show_empty()
            return

        if file_path == self._current_path:
            return  # 已经在预览这个文件
        self._current_path = file_path

        ext = Path(file_path).suffix.lower()
        file_size = os.path.getsize(file_path)
        size_str = self._format_size(file_size)
        file_name = os.path.basename(file_path)

        if ext in _IMAGE_EXTS:
            self._show_image(file_path, file_name, size_str)
        elif ext in _VIDEO_EXTS:
            self._show_video_thumbnail(file_path, file_name, size_str)
        else:
            self._show_generic(file_name, size_str, ext)

    def _show_image(self, file_path: str, name: str, size: str):
        """显示图片预览。使用 _safe_load_pixmap 避免段错误。"""
        pixmap = _safe_load_pixmap(file_path)
        if pixmap.isNull():
            self._show_generic(name, size, Path(file_path).suffix)
            return

        # 缩放到预览区域
        scaled = pixmap.scaled(
            self._preview_label.width() - 16,
            160,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)
        self._preview_label.setText('')
        self._preview_label.setProperty('previewState', 'image')
        self._refresh_preview_label_style()
        self._info_label.setText(f'{name}  |  {size}  |  {pixmap.width()}×{pixmap.height()}')

    def _show_video_thumbnail(self, file_path: str, name: str, size: str):
        """显示视频封面（ffmpeg 后台提取第一帧，不阻塞 UI 线程）。"""
        # 检查缓存
        if file_path in self._thumbnail_cache:
            pixmap = self._thumbnail_cache[file_path]
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self._preview_label.width() - 16, 160,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._preview_label.setPixmap(scaled)
                self._preview_label.setText('')
                self._preview_label.setProperty('previewState', 'image')
                self._refresh_preview_label_style()
                self._info_label.setText(f'🎬 {name}  |  {size}')
                return

        # 取消上一个未完成的后台提取
        self._stop_thumbnail_thread()

        # 显示占位状态
        self._pending_video_path = file_path
        self._preview_label.setPixmap(QPixmap())
        self._preview_label.setText('🎬')
        self._preview_label.setProperty('previewState', 'icon')
        self._refresh_preview_label_style()
        self._info_label.setText(f'🎬 {name}  |  {size}  |  正在提取封面...')

        # 启动后台线程提取封面
        self._thumbnail_thread = _ThumbnailExtractor(file_path, self)
        self._thumbnail_thread.finished_ok.connect(self._on_thumbnail_ready)
        self._thumbnail_thread.start()

    def _on_thumbnail_ready(self, request_path: str, pixmap: QPixmap) -> None:
        """后台线程提取封面完成的回调（在主线程执行）。"""
        # 如果用户已切换到其他文件，忽略结果
        if request_path != self._current_path:
            return
        if pixmap.isNull():
            return

        self._thumbnail_cache[request_path] = pixmap
        scaled = pixmap.scaled(
            self._preview_label.width() - 16, 160,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)
        self._preview_label.setText('')
        self._preview_label.setProperty('previewState', 'image')
        self._refresh_preview_label_style()

        # 恢复 info_label（不含"正在提取封面..."）
        name = os.path.basename(request_path)
        try:
            size = self._format_size(os.path.getsize(request_path))
        except OSError:
            size = '?'
        self._info_label.setText(f'🎬 {name}  |  {size}')

    def _stop_thumbnail_thread(self) -> None:
        """停止正在运行的后台缩略图提取线程。"""
        if self._thumbnail_thread is not None:
            try:
                if self._thumbnail_thread.isRunning():
                    self._thumbnail_thread.quit()
                    self._thumbnail_thread.wait(2000)
            except Exception:
                pass
            try:
                self._thumbnail_thread.finished_ok.disconnect()
            except TypeError:
                pass
            self._thumbnail_thread = None

    def _show_generic(self, name: str, size: str, ext: str):
        """显示通用文件信息。"""
        icons = {
            '.mp4': '🎬', '.avi': '🎬', '.mkv': '🎬', '.mov': '🎬',
            '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵', '.aac': '🎵',
            '.pdf': '📄', '.docx': '📄', '.doc': '📄',
            '.xlsx': '📊', '.xls': '📊',
            '.zip': '📦', '.rar': '📦',
        }
        icon = icons.get(ext, '📎')
        self._preview_label.setPixmap(QPixmap())
        self._preview_label.setText(icon)
        self._preview_label.setProperty('previewState', 'icon')
        self._refresh_preview_label_style()
        self._info_label.setText(f'{icon} {name}  |  {size}')

    def clear(self):
        """清空预览。"""
        self._stop_thumbnail_thread()
        self._current_path = ''
        self._pending_video_path = ''
        self._show_empty()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小。"""
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size_bytes < 1024:
                return f'{size_bytes:.1f} {unit}'
            size_bytes /= 1024
        return f'{size_bytes:.1f} TB'


# ==============================================================
# HistoryDialog — 转换历史对话框（含 FFmpeg 命令复制）
# ==============================================================

class HistoryDialog(QDialog):
    """转换历史记录对话框。支持搜索、清空、导出、复制 FFmpeg 命令。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('转换历史')
        self.setMinimumSize(800, 500)
        self._all_records: list[dict] = []
        self._init_ui()
        self._load_history()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 搜索栏
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search_input = QComboBox()
        self._search_input.setEditable(True)
        self._search_input.setMinimumHeight(36)
        self._search_input.setPlaceholderText('搜索文件名...')
        self._search_input.currentTextChanged.connect(self._on_search)
        search_row.addWidget(self._search_input, 1)

        btn_clear = QPushButton('清空历史')
        btn_clear.setObjectName('DangerButton')
        btn_clear.setMinimumHeight(36)
        btn_clear.clicked.connect(self._on_clear)
        search_row.addWidget(btn_clear)

        btn_export = QPushButton('导出 MD')
        btn_export.setObjectName('SecondaryButton')
        btn_export.setMinimumHeight(36)
        btn_export.clicked.connect(self._on_export)
        search_row.addWidget(btn_export)

        btn_copy_cmd = QPushButton('📋 复制 FFmpeg 命令')
        btn_copy_cmd.setObjectName('SecondaryButton')
        btn_copy_cmd.setMinimumHeight(36)
        btn_copy_cmd.clicked.connect(self._on_copy_ffmpeg_cmd)
        search_row.addWidget(btn_copy_cmd)

        layout.addLayout(search_row)

        # 历史列表
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ['时间', '类型', '文件名', '状态', '耗时', '路径'])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

        # 底部信息
        self._info_label = QLabel('')
        self._info_label.setObjectName('SectionHint')
        layout.addWidget(self._info_label)

    def _load_history(self, records=None):
        """加载历史记录到表格。"""
        from history import HistoryManager
        hm = HistoryManager()
        if records is None:
            self._all_records = [record for record in hm.get_recent(200) if isinstance(record, dict)]
            safe_records = self._all_records
        else:
            safe_records = [record for record in records if isinstance(record, dict)]

        self._records = safe_records  # 缓存用于复制命令
        self._table.setRowCount(len(safe_records))
        for i, r in enumerate(safe_records):
            ts = r.get('timestamp', '')[:19].replace('T', ' ')
            self._table.setItem(i, 0, QTableWidgetItem(ts))
            self._table.setItem(i, 1, QTableWidgetItem(r.get('type', '')))

            inp = r.get('input', '')
            name_item = QTableWidgetItem(os.path.basename(inp))
            name_item.setToolTip(inp)
            self._table.setItem(i, 2, name_item)

            status = '✅ 成功' if r.get('success') else '❌ 失败'
            status_item = QTableWidgetItem(status)
            if r.get('error'):
                status_item.setToolTip(r['error'])
            self._table.setItem(i, 3, status_item)

            # 耗时
            dur = r.get('duration_ms', 0)
            if dur > 0:
                if dur >= 1000:
                    dur_text = f'{dur / 1000:.1f}s'
                else:
                    dur_text = f'{dur}ms'
            else:
                dur_text = ''
            self._table.setItem(i, 4, QTableWidgetItem(dur_text))

            out_item = QTableWidgetItem(r.get('output', ''))
            out_item.setToolTip(r.get('output', ''))
            self._table.setItem(i, 5, out_item)

        self._info_label.setText(f'共 {len(safe_records)} 条记录  |  总计 {hm.count} 条')

    def _on_search(self, text):
        """搜索。"""
        keyword = text.strip().lower()
        if not keyword:
            self._load_history(self._all_records)
            return
        results = [
            record for record in self._all_records
            if keyword in record.get('input', '').lower()
            or keyword in record.get('output', '').lower()
            or keyword in record.get('type', '').lower()
            or keyword in record.get('error', '').lower()
            or keyword in record.get('ffmpeg_cmd', '').lower()
        ]
        self._load_history(results)

    def _on_clear(self):
        """清空历史。"""
        reply = QMessageBox.question(
            self, '确认清空',
            '确定要清空所有转换历史吗？此操作不可撤销。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from history import HistoryManager
            hm = HistoryManager()
            hm.clear()
            self._all_records = []
            self._load_history(self._all_records)

    def _on_export(self):
        """导出为 Markdown。"""
        from history import HistoryManager
        from datetime import datetime
        hm = HistoryManager()
        if hm.count == 0:
            QMessageBox.information(self, '提示', '没有历史记录。')
            return
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path, _ = QFileDialog.getSaveFileName(
            self, '导出历史', f'转换历史_{ts}.md',
            'Markdown (*.md);;所有文件 (*..*)',
        )
        if path:
            result = hm.export_markdown(path)
            QMessageBox.information(self, '导出成功', f'已导出到:\n{result}')

    def _on_copy_ffmpeg_cmd(self):
        """复制选中记录的 FFmpeg 命令到剪贴板。"""
        selected = self._table.selectedItems()
        if not selected:
            QMessageBox.information(self, '提示', '请先选择一条历史记录。')
            return
        row = selected[0].row()
        if row < len(self._records):
            cmd = self._records[row].get('ffmpeg_cmd', '')
            if cmd:
                QApplication.clipboard().setText(cmd)
                QMessageBox.information(
                    self, '已复制',
                    'FFmpeg 命令已复制到剪贴板。\n\n'
                    '可以在终端中修改参数后直接运行。')
            else:
                QMessageBox.information(
                    self, '提示',
                    '该记录没有保存 FFmpeg 命令。\n'
                    '（仅 v1.2.0 之后的转换记录包含命令日志）')


# ==============================================================
# PresetCombo — 预设选择组件
# ==============================================================

class PresetCombo(QWidget):
    """预设选择下拉框，集成 PresetManager。"""

    preset_applied = pyqtSignal(dict)  # 预设应用信号

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._combo = QComboBox()
        self._combo.setMinimumHeight(36)
        self._combo.setPlaceholderText('选择预设...')
        layout.addWidget(self._combo, 1)

        self._btn_save = QPushButton('💾')
        self._btn_save.setFixedSize(36, 36)
        self._btn_save.setToolTip('保存当前设置为预设')
        layout.addWidget(self._btn_save)

        self._btn_delete = QPushButton('🗑')
        self._btn_delete.setFixedSize(36, 36)
        self._btn_delete.setToolTip('删除选中预设')
        layout.addWidget(self._btn_delete)

        self.setMinimumHeight(36)

        self._combo.currentIndexChanged.connect(self._on_selected)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_delete.clicked.connect(self._on_delete)

        self._pm = None
        self._load_presets()

    def set_manager(self, pm) -> None:
        """设置外部 PresetManager 实例并刷新列表。"""
        self._pm = pm
        self._refresh_combo()

    def _load_presets(self):
        """加载预设列表（内部初始化用）。"""
        if self._pm is None:
            from presets import PresetManager
            self._pm = PresetManager()
        self._refresh_combo()

    def _refresh_combo(self):
        """刷新下拉框内容。"""
        if self._pm is None:
            return
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem('（无预设）', None)
        for name, params in self._pm.list_presets().items():
            desc = params.get('description', '')
            self._combo.addItem(f'{name} — {desc}', name)
        self._combo.blockSignals(False)

    def _on_selected(self, idx):
        """预设被选中。"""
        name = self._combo.currentData()
        if name:
            params = self._pm.get_preset(name)
            if params:
                params = params.copy()
                params.pop('description', None)
                self.preset_applied.emit(params)

    def _on_save(self):
        """保存当前设置为新预设。"""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, '保存预设', '预设名称:')
        if ok and name.strip():
            # 发送保存请求信号（包含 __save_request__ 标记）
            self.preset_applied.emit({'__save_request__': name.strip()})

    def _on_delete(self):
        """删除选中预设。"""
        if self._pm is None:
            return
        name = self._combo.currentData()
        if not name:
            return
        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除预设 "{name}" 吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._pm.delete_preset(name):
                self._pm.save()
                self._refresh_combo()
            else:
                QMessageBox.warning(self, '提示', '内置预设不可删除。')


# ==============================================================
# ToolPanel — 工具面板
# ==============================================================

# ──────────────────────────────────────────────
# 工具定义（按子类别分组）
# ──────────────────────────────────────────────
# 格式: (key, 显示名称, 子类别, 文件过滤器key, 输出扩展名)
# 子类别: 'video' / 'image' / 'document'
# 文件过滤器key: 'video' / 'image' / 'document' / 'audio_video' / 'pdf' / 'all'

TOOL_CATEGORIES = [
    ('video', '🎬 视频工具'),
    ('image', '🖼 图片工具'),
    ('document', '📄 文档工具'),
]
TOOL_CAT_KEYS = [c[0] for c in TOOL_CATEGORIES]

TOOLS = [
    # ── 视频工具 ──
    ('export_cmd',       '导出 FFmpeg 命令',  'video',    'video',        None),
    ('embed_subtitle',   '嵌入字幕',          'video',    'video',        '.mp4'),
    ('extract_subtitle', '提取字幕',          'video',    'video',        '.srt'),
    ('extract_audio',    '提取音频',          'video',    'video',        '.mp3'),
    ('merge_media',      '合并音视频',        'video',    'audio_video',  '.mp4'),
    ('crop_video',       '画面裁剪',          'video',    'video',        '.mp4'),
    ('trim_media',       '截取片段',          'video',    'audio_video',  None),
    ('compress_video',   '视频压缩',          'video',    'video',        None),
    ('video_to_gif',     '视频转 GIF',        'video',    'video',        '.gif'),
    ('media_info',       '媒体信息',          'video',    'all',          None),
    # ── 图片工具 ──
    ('compress_image',   '图片压缩',          'image',    'image',        None),
    ('resize_image',     '图片缩放',          'image',    'image',        None),
    ('add_watermark',    '添加水印',          'image',    'image',        None),
    # ── 文档工具 ──
    ('merge_pdfs',       '合并 PDF',          'document', 'pdf',          '.pdf'),
    ('split_pdf',        '拆分 PDF',          'document', 'pdf',          None),
    ('pdf_to_images',    'PDF 转图片',        'document', 'pdf',          None),
    ('images_to_pdf',    '图片转 PDF',        'document', 'image',        '.pdf'),
]

TOOL_KEYS = [t[0] for t in TOOLS]
TOOL_BY_KEY = {t[0]: t for t in TOOLS}

_FILE_FILTERS = {
    'video':       '视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.webm *.flv *.ts *.m4v);;所有文件 (*.*)',
    'audio_video': '音视频文件 (*.mp4 *.avi *.mkv *.mov *.mp3 *.wav *.flac *.aac *.ogg *.wma *.m4a);;所有文件 (*.*)',
    'image':       '图片文件 (*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp *.ico *.heic);;所有文件 (*.*)',
    'document':    '文档文件 (*.pdf *.docx);;所有文件 (*.*)',
    'pdf':         'PDF 文件 (*.pdf);;所有文件 (*.*)',
    'all':         '所有文件 (*.*)',
}


class ToolPanel(QWidget):
    """工具面板：按子类别选择工具，动态显示参数。"""

    tool_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_tool = None
        self._page_map = {}
        self._subtitle_path = ''
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 子类别 + 工具选择
        row = QHBoxLayout()
        row.setSpacing(12)

        # 与设置卡片中其它行的 70px 标签列对齐
        cat_lbl = QLabel('工具选择')
        cat_lbl.setObjectName('FieldLabel')
        cat_lbl.setFixedWidth(70)
        row.addWidget(cat_lbl)

        self._cat_combo = QComboBox()
        self._cat_combo.setMinimumHeight(36)
        for cat_key, cat_name in TOOL_CATEGORIES:
            self._cat_combo.addItem(cat_name, cat_key)
        self._cat_combo.currentIndexChanged.connect(self._on_cat_changed)
        row.addWidget(self._cat_combo)

        self._tool_combo = QComboBox()
        self._tool_combo.setMinimumHeight(36)
        self._tool_combo.setMinimumWidth(200)
        self._tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        row.addWidget(self._tool_combo, 1)

        layout.addLayout(row)

        # 参数栈
        self._params_stack = QStackedWidget()
        layout.addWidget(self._params_stack)

        # 构建所有工具的参数页
        self._build_all_pages()

        # 初始化第一个子类别
        self._on_cat_changed(0)

    def _build_all_pages(self):
        """为每个工具创建参数页面。"""
        for tool_key, tool_name, cat, filt, ext in TOOLS:
            page = self._build_tool_page(tool_key)
            idx = self._params_stack.addWidget(page)
            self._page_map[tool_key] = idx

    def _build_tool_page(self, tool_key: str) -> QWidget:
        """构建单个工具的参数页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        if tool_key == 'export_cmd':
            hint = QLabel('点击"执行"后，将在日志中输出对应的 FFmpeg 命令（不实际执行）。')
            hint.setObjectName('SectionHint')
            layout.addWidget(hint)

        elif tool_key == 'embed_subtitle':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('字幕文件')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._sub_path_label = QLabel('未选择')
            self._sub_path_label.setObjectName('SectionHint')
            row.addWidget(self._sub_path_label, 1)
            btn_browse = QPushButton('浏览')
            btn_browse.setObjectName('SecondaryButton')
            btn_browse.setFixedWidth(60)
            btn_browse.clicked.connect(self._browse_subtitle)
            row.addWidget(btn_browse)
            layout.addLayout(row)

            row2 = QHBoxLayout()
            row2.setSpacing(12)
            lbl2 = QLabel('语言')
            lbl2.setObjectName('FieldLabel')
            lbl2.setFixedWidth(70)
            row2.addWidget(lbl2)
            self._lang_combo = QComboBox()
            self._lang_combo.setMinimumHeight(36)
            langs = [('chi', '中文'), ('eng', '英文'), ('jpn', '日语'),
                     ('kor', '韩语'), ('fre', '法语'), ('ger', '德语'),
                     ('spa', '西班牙语'), ('por', '葡萄牙语')]
            for i, (code, name) in enumerate(langs):
                self._lang_combo.addItem(name)
                self._lang_combo.setItemData(i, code)
            row2.addWidget(self._lang_combo)
            row2.addStretch()
            layout.addLayout(row2)

        elif tool_key == 'extract_subtitle':
            hint = QLabel('从视频中提取字幕流，输出为 .srt 文件。')
            hint.setObjectName('SectionHint')
            layout.addWidget(hint)

        elif tool_key == 'extract_audio':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('音频格式')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._extract_audio_fmt = QComboBox()
            self._extract_audio_fmt.setMinimumHeight(36)
            self._extract_audio_fmt.addItems(['MP3', 'WAV', 'FLAC', 'AAC', 'OGG', 'OPUS'])
            self._extract_audio_fmt.setItemData(0, 'mp3')
            self._extract_audio_fmt.setItemData(1, 'wav')
            self._extract_audio_fmt.setItemData(2, 'flac')
            self._extract_audio_fmt.setItemData(3, 'aac')
            self._extract_audio_fmt.setItemData(4, 'ogg')
            self._extract_audio_fmt.setItemData(5, 'opus')
            row.addWidget(self._extract_audio_fmt)
            row.addStretch()
            layout.addLayout(row)

        elif tool_key == 'merge_media':
            hint = QLabel('添加多个同格式文件，按添加顺序合并为一个文件。')
            hint.setObjectName('SectionHint')
            layout.addWidget(hint)

        elif tool_key == 'crop_video':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('裁剪尺寸')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._crop_w = QSpinBox()
            self._crop_w.setRange(2, 7680)
            self._crop_w.setValue(1920)
            self._crop_w.setPrefix('宽 ')
            self._crop_w.setMinimumHeight(36)
            row.addWidget(self._crop_w)
            self._crop_h = QSpinBox()
            self._crop_h.setRange(2, 4320)
            self._crop_h.setValue(1080)
            self._crop_h.setPrefix('高 ')
            self._crop_h.setMinimumHeight(36)
            row.addWidget(self._crop_h)
            self._crop_x = QSpinBox()
            self._crop_x.setRange(0, 7680)
            self._crop_x.setValue(0)
            self._crop_x.setPrefix('X ')
            self._crop_x.setMinimumHeight(36)
            row.addWidget(self._crop_x)
            self._crop_y = QSpinBox()
            self._crop_y.setRange(0, 4320)
            self._crop_y.setValue(0)
            self._crop_y.setPrefix('Y ')
            self._crop_y.setMinimumHeight(36)
            row.addWidget(self._crop_y)
            row.addStretch()
            layout.addLayout(row)

        elif tool_key == 'trim_media':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('时间段')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._trim_start = QComboBox()
            self._trim_start.setEditable(True)
            self._trim_start.setMinimumHeight(36)
            self._trim_start.setMinimumWidth(120)
            self._trim_start.setCurrentText('00:00:00')
            row.addWidget(QLabel('从'))
            row.addWidget(self._trim_start)
            self._trim_end = QComboBox()
            self._trim_end.setEditable(True)
            self._trim_end.setMinimumHeight(36)
            self._trim_end.setMinimumWidth(120)
            self._trim_end.setCurrentText('00:01:00')
            row.addWidget(QLabel('到'))
            row.addWidget(self._trim_end)
            hint = QLabel('(格式: HH:MM:SS 或秒数)')
            hint.setObjectName('SectionHint')
            row.addWidget(hint)
            row.addStretch()
            layout.addLayout(row)

        elif tool_key == 'compress_video':
            layout.setContentsMargins(0, 0, 0, 0)
            row1 = QHBoxLayout()
            row1.setSpacing(12)
            lbl1 = QLabel('CRF 质量')
            lbl1.setObjectName('FieldLabel')
            lbl1.setFixedWidth(70)
            row1.addWidget(lbl1)
            self._compress_crf = QSpinBox()
            self._compress_crf.setRange(0, 51)
            self._compress_crf.setValue(28)
            self._compress_crf.setToolTip('0=无损 23=默认 28=高压缩 51=最差')
            self._compress_crf.setMinimumHeight(36)
            row1.addWidget(self._compress_crf)
            lbl1b = QLabel('缩放宽度')
            lbl1b.setObjectName('FieldLabel')
            row1.addWidget(lbl1b)
            self._compress_scale = QSpinBox()
            self._compress_scale.setRange(0, 7680)
            self._compress_scale.setValue(0)
            self._compress_scale.setSpecialValueText('不缩放')
            self._compress_scale.setMinimumHeight(36)
            row1.addWidget(self._compress_scale)
            row1.addStretch()
            layout.addLayout(row1)

            row2 = QHBoxLayout()
            row2.setSpacing(12)
            lbl2 = QLabel('目标大小')
            lbl2.setObjectName('FieldLabel')
            lbl2.setFixedWidth(70)
            row2.addWidget(lbl2)
            self._compress_target_mb = QSpinBox()
            self._compress_target_mb.setRange(0, 99999)
            self._compress_target_mb.setValue(0)
            self._compress_target_mb.setSuffix(' MB')
            self._compress_target_mb.setSpecialValueText('不限制')
            self._compress_target_mb.setMinimumHeight(36)
            self._compress_target_mb.setToolTip('0=用CRF模式，>0=按目标大小自动计算码率')
            row2.addWidget(self._compress_target_mb)
            row2.addStretch()
            layout.addLayout(row2)

        elif tool_key == 'video_to_gif':
            layout.setContentsMargins(0, 0, 0, 0)
            row1 = QHBoxLayout()
            row1.setSpacing(12)
            lbl1 = QLabel('帧率')
            lbl1.setObjectName('FieldLabel')
            lbl1.setFixedWidth(70)
            row1.addWidget(lbl1)
            self._gif_fps = QSpinBox()
            self._gif_fps.setRange(1, 30)
            self._gif_fps.setValue(12)
            self._gif_fps.setMinimumHeight(36)
            self._gif_fps.setToolTip('推荐 10-15，社交媒体用 12')
            row1.addWidget(self._gif_fps)
            lbl2 = QLabel('宽度')
            lbl2.setObjectName('FieldLabel')
            row1.addWidget(lbl2)
            self._gif_width = QSpinBox()
            self._gif_width.setRange(32, 1920)
            self._gif_width.setValue(480)
            self._gif_width.setSuffix(' px')
            self._gif_width.setMinimumHeight(36)
            row1.addWidget(self._gif_width)
            row1.addStretch()
            layout.addLayout(row1)

            row2 = QHBoxLayout()
            row2.setSpacing(12)
            lbl3 = QLabel('颜色数')
            lbl3.setObjectName('FieldLabel')
            lbl3.setFixedWidth(70)
            row2.addWidget(lbl3)
            self._gif_colors = QSpinBox()
            self._gif_colors.setRange(2, 256)
            self._gif_colors.setValue(256)
            self._gif_colors.setMinimumHeight(36)
            self._gif_colors.setToolTip('256=最高质量，64=小体积')
            row2.addWidget(self._gif_colors)
            row2.addStretch()
            layout.addLayout(row2)

        elif tool_key == 'media_info':
            hint = QLabel('选择文件后点击"执行"，将弹窗显示媒体详细信息。')
            hint.setObjectName('SectionHint')
            layout.addWidget(hint)

        elif tool_key == 'compress_image':
            layout.setContentsMargins(0, 0, 0, 0)
            row1 = QHBoxLayout()
            row1.setSpacing(12)
            lbl = QLabel('压缩质量')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row1.addWidget(lbl)
            self._img_quality = QSpinBox()
            self._img_quality.setRange(1, 100)
            self._img_quality.setValue(80)
            self._img_quality.setMinimumHeight(36)
            row1.addWidget(self._img_quality)
            row1.addStretch()
            layout.addLayout(row1)

            row2 = QHBoxLayout()
            row2.setSpacing(12)
            lbl2 = QLabel('目标大小')
            lbl2.setObjectName('FieldLabel')
            lbl2.setFixedWidth(70)
            row2.addWidget(lbl2)
            self._img_target_kb = QSpinBox()
            self._img_target_kb.setRange(0, 999999)
            self._img_target_kb.setValue(0)
            self._img_target_kb.setSuffix(' KB')
            self._img_target_kb.setSpecialValueText('不限制')
            self._img_target_kb.setMinimumHeight(36)
            self._img_target_kb.setToolTip('0=用质量模式，>0=按目标大小二分法迭代')
            row2.addWidget(self._img_target_kb)
            row2.addStretch()
            layout.addLayout(row2)

        elif tool_key == 'resize_image':
            layout.setContentsMargins(0, 0, 0, 0)
            row1 = QHBoxLayout()
            row1.setSpacing(12)
            lbl = QLabel('缩放模式')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row1.addWidget(lbl)
            self._resize_mode = QComboBox()
            self._resize_mode.setMinimumHeight(36)
            self._resize_mode.addItems(['按百分比', '按最大边长', '指定宽高'])
            self._resize_mode.currentIndexChanged.connect(self._on_resize_mode_changed)
            row1.addWidget(self._resize_mode)
            row1.addStretch()
            layout.addLayout(row1)

            # 百分比
            self._resize_pct_row = QHBoxLayout()
            self._resize_pct_row.setSpacing(12)
            spacer = QLabel('')
            spacer.setFixedWidth(70)
            self._resize_pct_row.addWidget(spacer)
            self._resize_pct = QSpinBox()
            self._resize_pct.setRange(1, 1000)
            self._resize_pct.setValue(50)
            self._resize_pct.setSuffix('%')
            self._resize_pct.setMinimumHeight(36)
            self._resize_pct_row.addWidget(self._resize_pct)
            self._resize_pct_row.addStretch()
            layout.addLayout(self._resize_pct_row)

            # 最大边长
            self._resize_max_row = QHBoxLayout()
            self._resize_max_row.setSpacing(12)
            spacer2 = QLabel('')
            spacer2.setFixedWidth(70)
            self._resize_max_row.addWidget(spacer2)
            self._resize_max_dim = QSpinBox()
            self._resize_max_dim.setRange(1, 16384)
            self._resize_max_dim.setValue(1920)
            self._resize_max_dim.setSuffix(' px')
            self._resize_max_dim.setMinimumHeight(36)
            self._resize_max_row.addWidget(self._resize_max_dim)
            self._resize_max_row.addStretch()
            layout.addLayout(self._resize_max_row)

            # 指定宽高
            self._resize_wh_row = QHBoxLayout()
            self._resize_wh_row.setSpacing(12)
            spacer3 = QLabel('')
            spacer3.setFixedWidth(70)
            self._resize_wh_row.addWidget(spacer3)
            self._resize_w = QSpinBox()
            self._resize_w.setRange(1, 16384)
            self._resize_w.setValue(800)
            self._resize_w.setPrefix('宽 ')
            self._resize_w.setMinimumHeight(36)
            self._resize_wh_row.addWidget(self._resize_w)
            self._resize_h = QSpinBox()
            self._resize_h.setRange(1, 16384)
            self._resize_h.setValue(600)
            self._resize_h.setPrefix('高 ')
            self._resize_h.setMinimumHeight(36)
            self._resize_wh_row.addWidget(self._resize_h)
            self._resize_wh_row.addStretch()
            layout.addLayout(self._resize_wh_row)

            # 初始显示
            self._on_resize_mode_changed(0)

        elif tool_key == 'add_watermark':
            layout.setContentsMargins(0, 0, 0, 0)
            # 文字水印
            row1 = QHBoxLayout()
            row1.setSpacing(12)
            lbl = QLabel('水印文字')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row1.addWidget(lbl)
            self._wm_text = QComboBox()
            self._wm_text.setEditable(True)
            self._wm_text.setMinimumHeight(36)
            self._wm_text.setMinimumWidth(250)
            self._wm_text.addItems(['© 版权所有', 'CONFIDENTIAL', 'DRAFT', 'Sample'])
            self._wm_text.setCurrentText('© 版权所有')
            row1.addWidget(self._wm_text)
            row1.addStretch()
            layout.addLayout(row1)

            row2 = QHBoxLayout()
            row2.setSpacing(12)
            lbl2 = QLabel('位置')
            lbl2.setObjectName('FieldLabel')
            lbl2.setFixedWidth(70)
            row2.addWidget(lbl2)
            self._wm_position = QComboBox()
            self._wm_position.setMinimumHeight(36)
            self._wm_position.addItems(['右下角', '左下角', '右上角', '左上角', '居中'])
            self._wm_position.setItemData(0, 'bottom-right')
            self._wm_position.setItemData(1, 'bottom-left')
            self._wm_position.setItemData(2, 'top-right')
            self._wm_position.setItemData(3, 'top-left')
            self._wm_position.setItemData(4, 'center')
            row2.addWidget(self._wm_position)
            lbl3 = QLabel('透明度')
            lbl3.setObjectName('FieldLabel')
            row2.addWidget(lbl3)
            self._wm_opacity = QSpinBox()
            self._wm_opacity.setRange(10, 100)
            self._wm_opacity.setValue(50)
            self._wm_opacity.setSuffix('%')
            self._wm_opacity.setMinimumHeight(36)
            row2.addWidget(self._wm_opacity)
            lbl4 = QLabel('字号')
            lbl4.setObjectName('FieldLabel')
            row2.addWidget(lbl4)
            self._wm_font_size = QSpinBox()
            self._wm_font_size.setRange(8, 200)
            self._wm_font_size.setValue(24)
            self._wm_font_size.setMinimumHeight(36)
            row2.addWidget(self._wm_font_size)
            row2.addStretch()
            layout.addLayout(row2)

        elif tool_key == 'merge_pdfs':
            hint = QLabel('添加多个 PDF 文件，按添加顺序合并为一个。')
            hint.setObjectName('SectionHint')
            layout.addWidget(hint)

        elif tool_key == 'split_pdf':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('每文件页数')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._split_pages = QSpinBox()
            self._split_pages.setRange(1, 9999)
            self._split_pages.setValue(1)
            self._split_pages.setMinimumHeight(36)
            self._split_pages.setToolTip('每个输出文件包含的页数')
            row.addWidget(self._split_pages)
            row.addStretch()
            layout.addLayout(row)

        elif tool_key == 'pdf_to_images':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('输出格式')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._pdf2img_fmt = QComboBox()
            self._pdf2img_fmt.setMinimumHeight(36)
            self._pdf2img_fmt.addItems(['PNG', 'JPEG'])
            self._pdf2img_fmt.setItemData(0, 'png')
            self._pdf2img_fmt.setItemData(1, 'jpg')
            row.addWidget(self._pdf2img_fmt)
            lbl2 = QLabel('DPI')
            lbl2.setObjectName('FieldLabel')
            row.addWidget(lbl2)
            self._pdf2img_dpi = QSpinBox()
            self._pdf2img_dpi.setRange(72, 600)
            self._pdf2img_dpi.setValue(200)
            self._pdf2img_dpi.setMinimumHeight(36)
            row.addWidget(self._pdf2img_dpi)
            row.addStretch()
            layout.addLayout(row)

        elif tool_key == 'images_to_pdf':
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel('页面大小')
            lbl.setObjectName('FieldLabel')
            lbl.setFixedWidth(70)
            row.addWidget(lbl)
            self._img2pdf_size = QComboBox()
            self._img2pdf_size.setMinimumHeight(36)
            self._img2pdf_size.addItems(['自动（图片原始尺寸）', 'A4 页面'])
            self._img2pdf_size.setItemData(0, 'auto')
            self._img2pdf_size.setItemData(1, 'a4')
            row.addWidget(self._img2pdf_size)
            row.addStretch()
            layout.addLayout(row)

        else:
            hint = QLabel(f'工具: {tool_key}')
            hint.setObjectName('SectionHint')
            layout.addWidget(hint)

        return page

    def _on_resize_mode_changed(self, idx: int):
        """切换缩放模式时显示/隐藏对应参数行。"""
        if not hasattr(self, '_resize_pct_row'):
            return
        for i in range(self._resize_pct_row.count()):
            w = self._resize_pct_row.itemAt(i).widget()
            if w:
                w.setVisible(idx == 0)
        for i in range(self._resize_max_row.count()):
            w = self._resize_max_row.itemAt(i).widget()
            if w:
                w.setVisible(idx == 1)
        for i in range(self._resize_wh_row.count()):
            w = self._resize_wh_row.itemAt(i).widget()
            if w:
                w.setVisible(idx == 2)

    def _on_cat_changed(self, idx: int):
        """子类别切换 → 更新工具下拉框。"""
        if idx < 0 or idx >= len(TOOL_CAT_KEYS):
            return
        cat_key = TOOL_CAT_KEYS[idx]
        self._tool_combo.blockSignals(True)
        self._tool_combo.clear()
        for tool_key, tool_name, cat, filt, ext in TOOLS:
            if cat == cat_key:
                self._tool_combo.addItem(tool_name, tool_key)
        self._tool_combo.blockSignals(False)
        if self._tool_combo.count() > 0:
            self._on_tool_changed(0)

    def _on_tool_changed(self, idx: int):
        """工具切换。"""
        key = self._tool_combo.currentData()
        if key and key in self._page_map:
            self._params_stack.setCurrentIndex(self._page_map[key])
            self._current_tool = key
            self.tool_changed.emit(key)

    def _browse_subtitle(self):
        """选择字幕文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, '选择字幕文件', '',
            '字幕文件 (*.srt *.ass *.ssa);;所有文件 (*.*)',
        )
        if path:
            self._subtitle_path = path
            self._sub_path_label.setText(os.path.basename(path))

    def get_tool_key(self) -> str:
        """获取当前工具 key。"""
        return self._current_tool

    def get_tool_params(self) -> dict:
        """获取当前工具参数。"""
        tool = self._current_tool
        params = {}
        if tool == 'embed_subtitle':
            params['subtitle_path'] = self._subtitle_path
            params['language'] = self._lang_combo.currentData()
        elif tool == 'extract_audio':
            params['format'] = self._extract_audio_fmt.currentData()
        elif tool == 'crop_video':
            params['width'] = self._crop_w.value()
            params['height'] = self._crop_h.value()
            params['x'] = self._crop_x.value()
            params['y'] = self._crop_y.value()
        elif tool == 'trim_media':
            params['start_time'] = self._trim_start.currentText().strip()
            params['end_time'] = self._trim_end.currentText().strip()
        elif tool == 'compress_video':
            params['crf'] = self._compress_crf.value()
            params['scale_width'] = self._compress_scale.value()
            params['target_size_mb'] = self._compress_target_mb.value()
        elif tool == 'video_to_gif':
            params['fps'] = self._gif_fps.value()
            params['width'] = self._gif_width.value()
            params['colors'] = self._gif_colors.value()
        elif tool == 'media_info':
            pass
        elif tool == 'compress_image':
            params['quality'] = self._img_quality.value()
            params['target_size_kb'] = self._img_target_kb.value()
        elif tool == 'resize_image':
            mode = self._resize_mode.currentIndex()
            if mode == 0:
                params['percentage'] = self._resize_pct.value()
            elif mode == 1:
                params['max_dimension'] = self._resize_max_dim.value()
            else:
                params['width'] = self._resize_w.value()
                params['height'] = self._resize_h.value()
        elif tool == 'add_watermark':
            params['text'] = self._wm_text.currentText().strip()
            params['position'] = self._wm_position.currentData()
            params['opacity'] = self._wm_opacity.value() / 100.0
            params['font_size'] = self._wm_font_size.value()
        elif tool == 'split_pdf':
            params['pages_per_file'] = self._split_pages.value()
        elif tool == 'pdf_to_images':
            params['fmt'] = self._pdf2img_fmt.currentData()
            params['dpi'] = self._pdf2img_dpi.value()
        elif tool == 'images_to_pdf':
            params['page_size'] = self._img2pdf_size.currentData()
        return params

    def get_file_filter(self) -> str:
        """获取当前工具的文件过滤器。"""
        for tool_key, _, _, filt, _ in TOOLS:
            if tool_key == self._current_tool:
                return _FILE_FILTERS.get(filt, _FILE_FILTERS['all'])
        return _FILE_FILTERS['all']
