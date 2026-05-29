"""
widgets.py — 自定义 PyQt6 Widget

从 ui.py 提取的可复用 widget 类，包括：
- DropableTableWidget: 拖拽文件表格
- StatusColorDelegate: 状态列彩色绘制
- ErrorDetailDialog: 错误详情对话框
- AdvancedSettingsPanel: 高级参数设置面板
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QTableWidget, QStyledItemDelegate, QStyle,
    QDialog, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QApplication, QLabel, QWidget,
    QGroupBox, QFormLayout, QSpinBox, QComboBox,
    QCheckBox, QSlider,
)

from formats import STATUS_COLORS, _collect_files_from_paths


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
