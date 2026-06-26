"""
widgets.py — 自定义 PyQt6 Widget

从 ui.py 提取的可复用 widget 类，包括：
- DropableTableWidget: 拖拽文件表格
- StatusColorDelegate: 状态列彩色绘制
- ErrorDetailDialog: 错误详情对话框
- AdvancedSettingsPanel: 高级参数设置面板
- PreviewPanel: 文件预览面板（图片/视频封面）
"""


__all__ = ['DropableTableWidget', 'StatusColorDelegate', 'ErrorDetailDialog', 'AdvancedSettingsPanel', 'PreviewPanel', 'ToolPanel', 'HistoryDialog', 'PresetCombo', 'TOOLS', 'TOOL_KEYS', 'TOOL_BY_KEY', 'TOOL_CATEGORIES', 'TOOL_CAT_KEYS']

import os
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QTableWidget, QStyledItemDelegate, QStyle,
    QDialog, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QApplication, QLabel, QWidget,
    QGroupBox, QFormLayout, QSpinBox, QComboBox,
    QCheckBox, QSizePolicy, QStackedWidget, QHeaderView,
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
        self._thumbnail_cache_max = 50  # 最多缓存 50 个视频缩略图
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
            # 缓存淘汰：超过上限时删除最早的条目
            if len(self._thumbnail_cache) >= self._thumbnail_cache_max:
                oldest_key = next(iter(self._thumbnail_cache))
                del self._thumbnail_cache[oldest_key]
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
        self._thumbnail_cache.clear()  # 释放缩略图缓存内存
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
TOOL_BY_KEY = {t[0]: t for t in TOO

... [OUTPUT TRUNCATED - 4929 chars omitted out of 54929 total] ...

ItemData(3, 'kor')
            sub_row2.addWidget(self._lang_combo)
            sub_row2.addStretch()
            layout.addLayout(sub_row2)

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
        # 遍历所有行的 widgets
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
        from PyQt6.QtWidgets import QFileDialog
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
            pass  # 无参数
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


# ==============================================================
# HistoryDialog — 转换历史对话框
# ==============================================================

class HistoryDialog(QDialog):
    """转换历史记录对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('转换历史')
        self.setMinimumSize(750, 500)
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
        layout.addLayout(search_row)

        # 历史列表
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(['时间', '类型', '文件名', '状态', '路径'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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
            records = hm.get_recent(200)

        self._table.setRowCount(len(records))
        for i, r in enumerate(records):
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

            out_item = QTableWidgetItem(r.get('output', ''))
            out_item.setToolTip(r.get('output', ''))
            self._table.setItem(i, 4, out_item)

        self._info_label.setText(f'共 {len(records)} 条记录  |  总计 {hm.count} 条')

    def _on_search(self, text):
        """搜索。"""
        if not text.strip():
            self._load_history()
            return
        from history import HistoryManager
        hm = HistoryManager()
        results = hm.search(text.strip())
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
            self._load_history()

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
            'Markdown (*.md);;所有文件 (*.*)',
        )
        if path:
            result = hm.export_markdown(path)
            QMessageBox.information(self, '导出成功', f'已导出到:\n{result}')


# ==============================================================
# PresetCombo — 预设选择组件
# ==============================================================

class PresetCombo(QWidget):
    """预设选择下拉框，集成 PresetManager。"""

    preset_applied = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = None
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel('快速预设')
        label.setObjectName('FieldLabel')
        label.setFixedWidth(70)
        layout.addWidget(label)

        self._combo = QComboBox()
        self._combo.setMinimumHeight(36)
        self._combo.setMinimumWidth(250)
        self._combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._combo)

        btn_save = QPushButton('保存当前')
        btn_save.setObjectName('SecondaryButton')
        btn_save.setMinimumHeight(36)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save_preset)
        layout.addWidget(btn_save)

        btn_delete = QPushButton('删除')
        btn_delete.setObjectName('SecondaryButton')
        btn_delete.setMinimumHeight(36)
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.clicked.connect(self._on_delete_preset)
        layout.addWidget(btn_delete)

        layout.addStretch()

    def set_manager(self, manager):
        """设置 PresetManager 实例。"""
        self._manager = manager
        self._refresh()

    def _refresh(self):
        """刷新预设列表。"""
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem('（不使用预设）', None)
        if self._manager:
            for name, params in self._manager.list_presets().items():
                desc = params.get('description', '')
                display = f'{name}  —  {desc}' if desc else name
                self._combo.addItem(display, name)
        self._combo.blockSignals(False)

    def _on_changed(self, idx):
        """预设选择变化。"""
        name = self._combo.currentData()
        if name and self._manager:
            preset = self._manager.get_preset(name)
            if preset:
                preset.pop('description', None)
                self.preset_applied.emit(preset)

    def _on_save_preset(self):
        """保存当前高级设置为预设。"""
        if not self._manager:
            return
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, '保存预设', '预设名称:')
        if ok and name.strip():
            # 预设参数由外部注入，这里发信号让主窗口提供
            self._save_name = name.strip()
            # 通过特殊信号让主窗口提供当前设置
            self.preset_applied.emit({'__save_request__': self._save_name})

    def _on_delete_preset(self):
        """删除选中的用户预设。"""
        if not self._manager:
            return
        name = self._combo.currentData()
        if not name:
            return
        if self._manager.delete_preset(name):
            self._refresh()
        else:
            QMessageBox.warning(self, '提示', '内置预设不可删除。')