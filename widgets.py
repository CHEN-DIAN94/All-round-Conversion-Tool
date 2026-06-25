"""
widgets.py — 自定义 PyQt6 Widget

从 ui.py 提取的可复用 widget 类，包括：
- DropableTableWidget: 拖拽文件表格
- StatusColorDelegate: 状态列彩色绘制
- ErrorDetailDialog: 错误详情对话框
- AdvancedSettingsPanel: 高级参数设置面板
- PreviewPanel: 文件预览面板（图片/视频封面）
"""


__all__ = ['DropableTableWidget', 'StatusColorDelegate', 'ErrorDetailDialog', 'AdvancedSettingsPanel', 'PreviewPanel']

import os
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QFont, QPainter, QPixmap, QImage
from PyQt6.QtWidgets import (
    QTableWidget, QStyledItemDelegate, QStyle,
    QDialog, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QApplication, QLabel, QWidget,
    QGroupBox, QFormLayout, QSpinBox, QComboBox,
    QCheckBox, QSlider, QSizePolicy,
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
    """为状态列绘制彩色文本。"""

    def paint(self, painter: QPainter, option, index) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ''
        color = STATUS_COLORS.get(text, '#1F1F1F')

        painter.save()
        # 选中态背景
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor('#E5F1FB'))

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

class AdvancedSettingsPanel(QWidget):
    """
    高级参数设置面板。

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
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 预设选择
        preset_group = QGroupBox('快速预设')
        preset_layout = QHBoxLayout(preset_group)

        for preset_name in self.PRESETS:
            btn = QPushButton(preset_name)
            btn.clicked.connect(lambda checked, name=preset_name: self._apply_preset(name))
            preset_layout.addWidget(btn)

        layout.addWidget(preset_group)

        # 视频参数
        video_group = QGroupBox('视频参数')
        video_layout = QFormLayout(video_group)

        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 51)
        self.crf_spin.setValue(self._settings['video_crf'])
        self.crf_spin.setToolTip('CRF 值越低，质量越高，文件越大（推荐: 18-28）')
        video_layout.addRow('CRF 质量:', self.crf_spin)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            'ultrafast', 'superfast', 'veryfast', 'faster',
            'fast', 'medium', 'slow', 'slower', 'veryslow',
        ])
        self.preset_combo.setCurrentText(self._settings['video_preset'])
        self.preset_combo.setToolTip('编码速度，越慢质量越高')
        video_layout.addRow('编码预设:', self.preset_combo)

        layout.addWidget(video_group)

        # 音频参数
        audio_group = QGroupBox('音频参数')
        audio_layout = QFormLayout(audio_group)

        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(['96k', '128k', '160k', '192k', '256k', '320k'])
        self.bitrate_combo.setCurrentText(self._settings['audio_bitrate'])
        audio_layout.addRow('比特率:', self.bitrate_combo)

        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(['22050', '44100', '48000', '96000'])
        self.sample_rate_combo.setCurrentText(str(self._settings['audio_sample_rate']))
        audio_layout.addRow('采样率:', self.sample_rate_combo)

        layout.addWidget(audio_group)

        # 图片参数
        image_group = QGroupBox('图片参数')
        image_layout = QFormLayout(image_group)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(self._settings['image_quality'])
        image_layout.addRow('质量:', self.quality_spin)

        self.resize_spin = QSpinBox()
        self.resize_spin.setRange(1, 1000)
        self.resize_spin.setValue(self._settings['image_resize'])
        self.resize_spin.setSuffix('%')
        image_layout.addRow('缩放:', self.resize_spin)

        layout.addWidget(image_group)

        # 操作按钮
        btn_layout = QHBoxLayout()

        btn_reset = QPushButton('恢复默认')
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_apply = QPushButton('应用')
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
        layout.addWidget(self._preview_label)

        # 文件信息标签
        self._info_label = QLabel('选中文件以预览')
        self._info_label.setObjectName('PreviewInfo')
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setStyleSheet('font-size: 9pt; color: #888;')
        layout.addWidget(self._info_label)

        # 默认状态
        self._show_empty()

    def _show_empty(self):
        """显示空状态。"""
        self._preview_label.setText('🖼')
        self._preview_label.setStyleSheet('font-size: 32pt; color: #ccc;')
        self._info_label.setText('选中文件以预览')

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
        """显示图片预览。"""
        pixmap = QPixmap(file_path)
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
        self._preview_label.setStyleSheet('')
        self._info_label.setText(f'{name}  |  {size}  |  {pixmap.width()}×{pixmap.height()}')

    def _show_video_thumbnail(self, file_path: str, name: str, size: str):
        """显示视频封面（ffmpeg 提取第一帧）。"""
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
                self._preview_label.setStyleSheet('')
                self._info_label.setText(f'🎬 {name}  |  {size}')
                return

        # 提取封面
        pixmap = self._extract_thumbnail(file_path)
        if pixmap and not pixmap.isNull():
            self._thumbnail_cache[file_path] = pixmap
            scaled = pixmap.scaled(
                self._preview_label.width() - 16, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview_label.setPixmap(scaled)
            self._preview_label.setStyleSheet('')
            self._info_label.setText(f'🎬 {name}  |  {size}')
        else:
            self._show_generic(name, size, '.mp4')
            self._info_label.setText(f'🎬 {name}  |  {size}  |  无法提取封面')

    def _extract_thumbnail(self, file_path: str) -> QPixmap:
        """用 ffmpeg 提取视频第一帧。"""
        ffmpeg = get_ffmpeg_path()
        # 检查 ffmpeg 是否可用
        if not ffmpeg or ffmpeg == 'ffmpeg':
            # 尝试系统 ffmpeg
            pass

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
            if result.returncode == 0 and os.path.isfile(tmp_path):
                pixmap = QPixmap(tmp_path)
                return pixmap
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return QPixmap()

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
        self._preview_label.setText(icon)
        self._preview_label.setStyleSheet(f'font-size: 48pt;')
        self._info_label.setText(f'{icon} {name}  |  {size}')

    def clear(self):
        """清空预览。"""
        self._current_path = ''
        self._show_empty()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小。"""
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size_bytes < 1024:
                return f'{size_bytes:.1f} {unit}'
            size_bytes /= 1024
        return f'{size_bytes:.1f} TB'
