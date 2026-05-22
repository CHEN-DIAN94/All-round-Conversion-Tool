"""
ui.py — 全能格式转换工具主界面

基于 PyQt6 构建的工业级桌面应用界面。
支持拖拽文件、批量转换、实时进度、取消操作。
"""

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import (
    QDragEnterEvent, QDropEvent,
    QCloseEvent, QIcon,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QStatusBar, QCheckBox,
    QGroupBox, QGridLayout, QFrame, QButtonGroup,
)

from workers import ConversionWorker, FileStatus, BatchOrchestrator
from utils import (
    get_resource_path,
    get_file_size_str,
    map_format_to_category,
    ensure_output_dir,
)


# 格式映射表：类别 → (显示名称, 格式列表)
FORMAT_CATEGORIES = [
    ('video',   '[视频]', [
        ('MP4 (.mp4)',  '.mp4',  '通用兼容格式'),
        ('AVI (.avi)',  '.avi',  '老式 Windows 视频'),
        ('MKV (.mkv)',  '.mkv',  '高清多轨封装'),
        ('MOV (.mov)',  '.mov',  '苹果 QuickTime 格式'),
        ('WMV (.wmv)',  '.wmv',  'Windows 媒体视频'),
        ('WEBM (.webm)', '.webm','网页流媒体格式'),
        ('FLV (.flv)',  '.flv',  'Flash 视频格式'),
        ('GIF (.gif)',  '.gif',  '动态图片/视频'),
    ]),
    ('audio',   '[音频]', [
        ('MP3 (.mp3)',  '.mp3',  '通用音乐格式'),
        ('WAV (.wav)',  '.wav',  '无损原始音频'),
        ('FLAC (.flac)','.flac', '开源无损压缩'),
        ('AAC (.aac)',  '.aac',  '高级音频编码'),
        ('OGG (.ogg)',  '.ogg',  '开源音频格式'),
        ('WMA (.wma)',  '.wma',  'Windows 媒体音频'),
        ('M4A (.m4a)',  '.m4a',  'AAC 封装格式'),
    ]),
    ('image',   '[图片]', [
        ('JPEG (.jpg)', '.jpg', '通用照片格式（有损）'),
        ('PNG (.png)',  '.png', '无损透明图片'),
        ('BMP (.bmp)',  '.bmp', '无压缩位图'),
        ('GIF (.gif)',  '.gif', '动态图片格式'),
        ('TIFF (.tiff)','.tiff','高精度印刷格式'),
        ('WEBP (.webp)','.webp','网页高效图片'),
        ('ICO (.ico)',  '.ico', 'Windows 图标格式'),
    ]),
    ('document', '[文档]', [
        ('PDF (.pdf)',  '.pdf', '便携式文档格式（由 DOCX 转入）'),
        ('DOCX (.docx)','.docx','Word 文档格式（由 PDF 转入）'),
    ]),
]

# 快速查找：类别 key → (显示名称, [(标签, 扩展名, 说明)])
FORMAT_BY_KEY = {k: (title, items) for k, title, items in FORMAT_CATEGORIES}

# 快速查找：扩展名 → 所属类别
EXT_TO_CATEGORY: dict[str, str] = {}
for cat_key, _, items in FORMAT_CATEGORIES:
    for _, ext, _ in items:
        EXT_TO_CATEGORY[ext] = cat_key

# 转换类型映射：(输入类别, 输出扩展名) → worker 使用的 conv_type
CONVERSION_MAP: dict[tuple[str, str], str] = {
    # 视频 → 视频
    ('video', '.mp4'): 'video',
    ('video', '.avi'): 'video',
    ('video', '.mkv'): 'video',
    ('video', '.mov'): 'video',
    ('video', '.wmv'): 'video',
    ('video', '.webm'): 'video',
    ('video', '.flv'): 'video',
    ('video', '.gif'): 'video',
    # 音频 → 音频
    ('audio', '.mp3'): 'audio',
    ('audio', '.wav'): 'audio',
    ('audio', '.flac'): 'audio',
    ('audio', '.aac'): 'audio',
    ('audio', '.ogg'): 'audio',
    ('audio', '.wma'): 'audio',
    ('audio', '.m4a'): 'audio',
    # 图片 → 图片
    ('image', '.jpg'): 'image',
    ('image', '.jpeg'): 'image',
    ('image', '.png'): 'image',
    ('image', '.bmp'): 'image',
    ('image', '.gif'): 'image',
    ('image', '.tiff'): 'image',
    ('image', '.tif'): 'image',
    ('image', '.webp'): 'image',
    ('image', '.ico'): 'image',
}


# 表格列索引
COL_FILE_NAME = 0
COL_FILE_SIZE = 1
COL_PROGRESS = 2
COL_STATUS = 3
COL_COUNT = 4


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
            files = []
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    files.append(file_path)
            if files and self._parent_window:
                self._parent_window.add_files_to_table(files)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    """
    主窗口。

    布局：
    ┌──────────────────────────────────────┐
    │  输出格式：[选择格式] [选择目录]       │
    ├──────────────────────────────────────┤
    │  文件列表 (QTableWidget)              │
    │  文件名 | 大小 | 进度 | 状态          │
    │  ...                                  │
    ├──────────────────────────────────────┤
    │  总体进度: [████████░░] 50%          │
    │  [添加文件] [清空列表] [全部开始] [取消] │
    └──────────────────────────────────────┘
    """

    def __init__(self):
        super().__init__()
        self._workers: list[ConversionWorker] = []
        self._orchestrator = BatchOrchestrator()
        self._output_dir: Optional[str] = None
        self._is_converting = False
        # 用户偏好持久化（输出目录/类别/格式/覆盖选项）
        # 跨平台：Windows 下存在 %APPDATA%\AllInOneConverter\AllInOneConverter.ini
        self._settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            'AllInOneConverter',
            'AllInOneConverter',
        )
        self._loading_settings = False  # 加载期间忽略变更事件

        self._init_ui()
        self._connect_signals()
        self._load_settings()

    def _init_ui(self) -> None:
        """初始化界面 — 扁平、留白、对象命名化（QSS 通过 objectName 命中）。"""
        self.setWindowTitle('全能格式转换工具')
        self.setMinimumSize(960, 640)
        self.setAcceptDrops(True)

        # 中央部件
        central = QWidget()
        central.setObjectName('CentralWidget')
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ---------- 顶部：标题区 ----------
        title_label = QLabel('全能格式转换工具')
        title_label.setObjectName('AppTitle')
        layout.addWidget(title_label)

        subtitle_label = QLabel('视频 · 音频 · 图片 · 文档 — 一站式批量转换')
        subtitle_label.setObjectName('AppSubtitle')
        layout.addWidget(subtitle_label)

        # ---------- 顶部：转换设置区（无边框 GroupBox） ----------
        settings_container = QWidget()
        settings_container.setObjectName('SettingsCard')
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 4, 0, 4)
        settings_layout.setSpacing(14)

        # —— 第一行：分段控制器（类别） ——
        cat_row = QHBoxLayout()
        cat_row.setSpacing(12)
        cat_label = QLabel('转换类型')
        cat_label.setObjectName('FieldLabel')
        cat_label.setFixedWidth(70)
        cat_row.addWidget(cat_label)

        # 分段控制器外壳
        seg_wrap = QWidget()
        seg_wrap.setObjectName('SegmentedControl')
        seg_layout = QHBoxLayout(seg_wrap)
        seg_layout.setContentsMargins(4, 4, 4, 4)
        seg_layout.setSpacing(2)

        self._category_group = QButtonGroup(self)
        self._category_btns = {}
        cat_names = [
            ('video', '视频'),
            ('audio', '音频'),
            ('image', '图片'),
            ('document', '文档'),
        ]
        for idx, (key, label) in enumerate(cat_names):
            btn = QPushButton(label)
            btn.setObjectName('SegmentButton')
            btn.setCheckable(True)
            btn.setMinimumWidth(86)
            btn.setMinimumHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if idx == 0:
                btn.setChecked(True)
            self._category_group.addButton(btn, idx)
            self._category_btns[key] = btn
            seg_layout.addWidget(btn)

        cat_row.addWidget(seg_wrap)
        cat_row.addStretch()
        settings_layout.addLayout(cat_row)

        # —— 第二行：输出格式 ——
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(12)
        fmt_label = QLabel('输出格式')
        fmt_label.setObjectName('FieldLabel')
        fmt_label.setFixedWidth(70)
        fmt_row.addWidget(fmt_label)

        self._format_combo = QComboBox()
        self._format_combo.setObjectName('FormatCombo')
        self._format_combo.setMinimumWidth(360)
        self._format_combo.setMinimumHeight(34)
        self._format_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._populate_format_combo('video')
        fmt_row.addWidget(self._format_combo)
        fmt_row.addStretch()
        settings_layout.addLayout(fmt_row)

        # —— 第三行：输出目录 ——
        dir_row = QHBoxLayout()
        dir_row.setSpacing(12)
        dir_label = QLabel('输出目录')
        dir_label.setObjectName('FieldLabel')
        dir_label.setFixedWidth(70)
        dir_row.addWidget(dir_label)

        self._output_dir_label = QLabel('与源文件同目录')
        self._output_dir_label.setObjectName('OutputPath')
        self._output_dir_label.setMinimumHeight(34)
        dir_row.addWidget(self._output_dir_label, 1)

        self._output_dir_btn = QPushButton('选择目录…')
        self._output_dir_btn.setObjectName('SecondaryButton')
        self._output_dir_btn.setMinimumHeight(34)
        self._output_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dir_row.addWidget(self._output_dir_btn)

        settings_layout.addLayout(dir_row)

        # —— 第四行：覆盖选项 ——
        opts_row = QHBoxLayout()
        opts_row.setSpacing(12)
        spacer_label = QLabel('')
        spacer_label.setFixedWidth(70)
        opts_row.addWidget(spacer_label)
        self._overwrite_check = QCheckBox('覆盖同名文件')
        opts_row.addWidget(self._overwrite_check)
        opts_row.addStretch()
        settings_layout.addLayout(opts_row)

        layout.addWidget(settings_container)

        # —— 分割线 ——
        sep = QFrame()
        sep.setObjectName('Divider')
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ---------- 中部：文件列表 ----------
        list_header = QHBoxLayout()
        list_header.setSpacing(8)
        list_title = QLabel('文件列表')
        list_title.setObjectName('SectionTitle')
        list_header.addWidget(list_title)
        list_hint = QLabel('支持拖拽添加 · 双击行查看详情')
        list_hint.setObjectName('SectionHint')
        list_header.addWidget(list_hint)
        list_header.addStretch()
        layout.addLayout(list_header)

        self._table = DropableTableWidget(self)
        self._table.setObjectName('FileTable')
        self._table.setColumnCount(COL_COUNT)
        self._table.setHorizontalHeaderLabels(['文件名', '大小', '进度', '状态'])
        self._table.horizontalHeader().setSectionResizeMode(COL_FILE_NAME, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(COL_FILE_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setFixedHeight(38)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setMinimumHeight(260)
        layout.addWidget(self._table, 1)

        # ---------- 底部：进度 ----------
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        progress_label_static = QLabel('总体进度')
        progress_label_static.setObjectName('FieldLabel')
        progress_label_static.setFixedWidth(70)
        progress_row.addWidget(progress_label_static)
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName('OverallProgress')
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        progress_row.addWidget(self._progress_bar, 1)
        self._progress_label = QLabel('0 / 0')
        self._progress_label.setObjectName('ProgressCount')
        self._progress_label.setMinimumWidth(60)
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self._progress_label)
        layout.addLayout(progress_row)

        # ---------- 底部：操作按钮 ----------
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._add_file_btn = QPushButton('添加文件')
        self._add_file_btn.setObjectName('SecondaryButton')
        self._clear_btn = QPushButton('清空列表')
        self._clear_btn.setObjectName('SecondaryButton')
        self._remove_selected_btn = QPushButton('移除选中')
        self._remove_selected_btn.setObjectName('SecondaryButton')

        for b in (self._add_file_btn, self._clear_btn, self._remove_selected_btn):
            b.setMinimumHeight(38)
            b.setCursor(Qt.CursorShape.PointingHandCursor)

        self._cancel_btn = QPushButton('取消')
        self._cancel_btn.setObjectName('SecondaryButton')
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setMinimumHeight(38)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._start_btn = QPushButton('全部开始')
        self._start_btn.setObjectName('PrimaryButton')
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumHeight(38)
        self._start_btn.setMinimumWidth(140)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_layout.addWidget(self._add_file_btn)
        btn_layout.addWidget(self._clear_btn)
        btn_layout.addWidget(self._remove_selected_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._start_btn)

        layout.addLayout(btn_layout)

        # ---------- 状态栏 ----------
        self._status_bar = QStatusBar()
        self._status_bar.setObjectName('AppStatusBar')
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage('就绪')

        self.resize(1040, 720)

    def _populate_format_combo(self, category_key: str = 'video') -> None:
        """根据选中类别填充输出格式下拉框（默认选中第一个格式）。"""
        self._format_combo.blockSignals(True)
        self._format_combo.clear()

        cat_info = FORMAT_BY_KEY.get(category_key)
        if not cat_info:
            self._format_combo.blockSignals(False)
            return

        title, items = cat_info
        for label, ext, desc in items:
            display = f'{label}  —  {desc}'
            self._format_combo.addItem(display, (ext, category_key))

        self._format_combo.setCurrentIndex(0)
        self._format_combo.blockSignals(False)

    def _connect_signals(self) -> None:
        """连接信号与槽。"""
        self._add_file_btn.clicked.connect(self._on_add_file)
        self._clear_btn.clicked.connect(self._on_clear)
        self._remove_selected_btn.clicked.connect(self._on_remove_selected)
        self._start_btn.clicked.connect(self._on_start_all)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._output_dir_btn.clicked.connect(self._on_select_output_dir)
        self._category_group.idClicked.connect(self._on_category_changed)
        # 关键：格式变更也要刷新开始按钮的可用性
        self._format_combo.currentIndexChanged.connect(self._update_start_button)
        # 偏好持久化：任何用户可见的设置变更都写盘
        self._format_combo.currentIndexChanged.connect(self._save_settings)
        self._overwrite_check.stateChanged.connect(self._save_settings)
        # 双击表格行 → 弹出该文件的详细错误/状态
        self._table.itemDoubleClicked.connect(self._on_table_double_clicked)

    # ---------- 拖拽支持 ----------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            files = []
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    files.append(file_path)
            if files:
                self.add_files_to_table(files)
            event.acceptProposedAction()

    # ---------- 文件列表管理 ----------

    def add_files_to_table(self, file_paths: list[str]) -> None:
        """将文件添加到表格。"""
        first_category = None
        for fp in file_paths:
            # 检查是否已在列表中
            if self._is_file_in_table(fp):
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)

            # 文件名
            name_item = QTableWidgetItem(os.path.basename(fp))
            name_item.setData(Qt.ItemDataRole.UserRole, fp)  # 存储完整路径
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, COL_FILE_NAME, name_item)

            # 大小
            size_item = QTableWidgetItem(get_file_size_str(fp))
            size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, COL_FILE_SIZE, size_item)

            # 进度（显示为文本）
            progress_item = QTableWidgetItem('0%')
            progress_item.setFlags(progress_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            progress_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_PROGRESS, progress_item)

            # 状态
            status_item = QTableWidgetItem(FileStatus.WAITING)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_STATUS, status_item)

            # 记录第一个文件的类别（用于自动跳转）
            if first_category is None:
                ext = Path(fp).suffix.lower().lstrip('.')
                first_category = map_format_to_category(ext)

        # 自动跳转到对应类别
        if first_category and first_category != 'unknown':
            self._switch_category(first_category)

        self._update_start_button()

    def _is_file_in_table(self, file_path: str) -> bool:
        """检查文件是否已在表格中。"""
        abs_path = os.path.abspath(file_path)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_FILE_NAME)
            if item and item.data(Qt.ItemDataRole.UserRole):
                if os.path.abspath(item.data(Qt.ItemDataRole.UserRole)) == abs_path:
                    return True
        return False

    def _switch_category(self, category_key: str) -> None:
        """切换到指定类别（更新按钮状态和格式下拉框）。"""
        if category_key in self._category_btns:
            btn = self._category_btns[category_key]
            if not btn.isChecked():
                btn.setChecked(True)
                self._populate_format_combo(category_key)
                self._update_start_button()

    def _on_category_changed(self, idx: int) -> None:
        """类别切换时更新格式下拉框。"""
        cat_keys = ['video', 'audio', 'image', 'document']
        if 0 <= idx < len(cat_keys):
            self._populate_format_combo(cat_keys[idx])
            self._update_start_button()
            self._save_settings()

    def _on_add_file(self) -> None:
        """点击「添加文件」按钮。"""
        files, _ = QFileDialog.getOpenFileNames(
            self, '选择要转换的文件',
            '',
            '所有支持的文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm '
            '*.mp3 *.wav *.flac *.aac *.ogg *.wma *.m4a '
            '*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp *.ico '
            '*.pdf *.docx *.txt *.rtf *.html);;所有文件 (*.*)',
        )
        if files:
            self.add_files_to_table(files)

    def _on_clear(self) -> None:
        """点击「清空列表」按钮。"""
        if self._is_converting:
            QMessageBox.warning(self, '警告', '转换进行中，请先取消。')
            return
        self._table.setRowCount(0)
        self._progress_bar.setValue(0)
        self._progress_label.setText('0 / 0')
        self._update_start_button()

    def _on_remove_selected(self) -> None:
        """点击「移除选中」按钮。"""
        if self._is_converting:
            QMessageBox.warning(self, '警告', '转换进行中，请先取消。')
            return
        selected_rows = set()
        for item in self._table.selectedItems():
            selected_rows.add(item.row())
        for row in sorted(selected_rows, reverse=True):
            self._table.removeRow(row)
        self._update_start_button()

    # ---------- 输出目录 ----------

    def _on_select_output_dir(self) -> None:
        """选择输出目录。"""
        # 上次目录作为起点
        start = self._output_dir or ''
        dir_path = QFileDialog.getExistingDirectory(self, '选择输出目录', start)
        if dir_path:
            self._output_dir = dir_path
            self._output_dir_label.setText(dir_path)
            self._output_dir_label.setStyleSheet('color: #000;')
            self._save_settings()

    # ---------- 转换控制 ----------

    def _on_start_all(self) -> None:
        """点击「全部开始」按钮。"""
        row_count = self._table.rowCount()
        if row_count == 0:
            return

        # 检查输出格式
        fmt_data = self._format_combo.currentData()
        if not fmt_data:
            QMessageBox.warning(self, '提示', '请先选择输出格式。')
            return
        output_ext, category_key = fmt_data

        # 重置所有行状态
        for row in range(row_count):
            self._table.item(row, COL_STATUS).setText(FileStatus.WAITING)
            self._table.item(row, COL_PROGRESS).setText('0%')

        # 为每个文件创建工作线程
        workers = []
        for row in range(row_count):
            input_path = self._table.item(row, COL_FILE_NAME).data(Qt.ItemDataRole.UserRole)
            if not input_path or not os.path.isfile(input_path):
                self._table.item(row, COL_STATUS).setText(FileStatus.FAILED)
                self._table.item(row, COL_PROGRESS).setText('—')
                continue

            output_path = self._generate_output_path(input_path, output_ext)
            conv_type = self._determine_conv_type(input_path, output_ext)

            if conv_type is None:
                self._table.item(row, COL_STATUS).setText(FileStatus.FAILED)
                self._table.item(row, COL_PROGRESS).setText('—')
                self._table.item(row, COL_FILE_NAME).setToolTip(
                    f'不支持的转换: {Path(input_path).suffix} → {output_ext}'
                )
                continue

            worker = ConversionWorker(row, input_path, output_path, conv_type)
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        if not workers:
            return

        self._workers = workers
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            self._orchestrator.add_worker(w)

        # 切换到转换模式
        self._is_converting = True
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._add_file_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)
        self._remove_selected_btn.setEnabled(False)
        self._format_combo.setEnabled(False)
        self._output_dir_btn.setEnabled(False)
        for btn in self._category_btns.values():
            btn.setEnabled(False)

        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在转换 {len(workers)} 个文件...')

        # 启动所有 worker
        self._orchestrator.start_all()

    def _on_cancel(self) -> None:
        """点击「取消」按钮。"""
        self._status_bar.showMessage('正在取消...')
        self._orchestrator.cancel_all()
        self._on_all_finished()

    def _on_status_updated(self, file_index: int, status: str) -> None:
        """更新表格中的状态列。"""
        if file_index < self._table.rowCount():
            self._table.item(file_index, COL_STATUS).setText(status)

    def _on_progress_updated(self, file_index: int, percent: int) -> None:
        """更新表格中的进度列。"""
        if file_index < self._table.rowCount():
            self._table.item(file_index, COL_PROGRESS).setText(f'{percent}%')

    def _on_task_finished(self, file_index: int, success: bool, message: str) -> None:
        """单个任务完成回调。"""
        # 把详细信息写到该行的 tooltip（双击行可查看）
        if 0 <= file_index < self._table.rowCount():
            status_item = self._table.item(file_index, COL_STATUS)
            name_item = self._table.item(file_index, COL_FILE_NAME)
            tip = message or ('转换完成' if success else '转换失败')
            if status_item:
                status_item.setToolTip(tip)
            if name_item:
                name_item.setToolTip(
                    f'{name_item.data(Qt.ItemDataRole.UserRole)}\n\n'
                    f'{"✗ 失败原因: " if not success else "✓ "}{tip}'
                )

        # 更新总体进度
        completed = sum(
            1 for w in self._workers
            if not w.isRunning()
        )
        total = len(self._workers)
        self._progress_label.setText(f'{completed} / {total}')
        if total > 0:
            self._progress_bar.setValue(int(completed / total * 100))

        # 更新状态栏
        self._status_bar.showMessage(f'已完成 {completed}/{total} 个文件')

        # 检查是否全部完成
        if self._orchestrator.all_finished():
            self._on_all_finished()

    def _on_all_finished(self) -> None:
        """所有任务完成。"""
        self._is_converting = False
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._add_file_btn.setEnabled(True)
        self._clear_btn.setEnabled(True)
        self._remove_selected_btn.setEnabled(True)
        self._format_combo.setEnabled(True)
        self._output_dir_btn.setEnabled(True)
        for btn in self._category_btns.values():
            btn.setEnabled(True)

        # 统计结果
        total = self._table.rowCount()
        success = sum(
            1 for row in range(total)
            if self._table.item(row, COL_STATUS).text() == FileStatus.SUCCESS
        )
        failed = sum(
            1 for row in range(total)
            if self._table.item(row, COL_STATUS).text() == FileStatus.FAILED
        )
        cancelled = sum(
            1 for row in range(total)
            if self._table.item(row, COL_STATUS).text() == FileStatus.CANCELLED
        )

        msg = f'转换完成：成功 {success}，失败 {failed}，取消 {cancelled}，共 {total} 个文件'
        self._status_bar.showMessage(msg)

        if failed > 0:
            QMessageBox.information(
                self, '转换完成',
                msg + '\n\n双击失败的文件行可查看具体错误原因。',
            )

        # 清理 worker 引用
        self._workers.clear()
        self._orchestrator.clear_all()

        self._update_start_button()

    # ---------- 辅助方法 ----------

    def _generate_output_path(self, input_path: str, output_ext: str) -> str:
        """根据输入路径和输出格式生成输出路径。"""
        input_stem = Path(input_path).stem
        if self._output_dir:
            output_path = os.path.join(self._output_dir, input_stem + output_ext)
        else:
            output_path = str(Path(input_path).with_suffix(output_ext))

        # 处理重名
        if not self._overwrite_check.isChecked():
            output_path = self._avoid_overwrite(output_path)

        ensure_output_dir(output_path)
        return output_path

    def _avoid_overwrite(self, file_path: str) -> str:
        """如果目标文件已存在，自动添加数字后缀。"""
        if not os.path.exists(file_path):
            return file_path

        p = Path(file_path)
        stem = p.stem
        suffix = p.suffix
        parent = p.parent

        counter = 1
        while True:
            new_path = str(parent / f'{stem} ({counter}){suffix}')
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def _determine_conv_type(self, input_path: str, output_ext: str) -> Optional[str]:
        """
        根据输入文件和输出格式确定转换类型。

        返回: 'video', 'audio', 'image', 'pdf_to_docx', 'docx_to_pdf' 或 None
        """
        input_ext = Path(input_path).suffix.lower()
        category = map_format_to_category(input_ext)

        if category == 'document':
            # 文档特殊处理
            if input_ext == '.pdf' and output_ext == '.docx':
                return 'pdf_to_docx'
            elif input_ext in ('.docx', '.doc') and output_ext == '.pdf':
                return 'docx_to_pdf'
            elif input_ext == '.pdf' and output_ext == '.pdf':
                return None  # 相同格式无意义
            elif input_ext == output_ext:
                return None
            # 其他文档格式用通用方式
            return None

        if category in ('video', 'audio', 'image'):
            # 同格式无意义
            if input_ext == output_ext:
                return None
            key = (category, output_ext)
            if key in CONVERSION_MAP:
                return CONVERSION_MAP[key]
            # 跨类别转换（如视频→GIF）仍然用 video
            return category

        return None

    def _update_start_button(self) -> None:
        """更新「全部开始」按钮状态。"""
        has_files = self._table.rowCount() > 0
        has_format = self._format_combo.currentData() is not None
        self._start_btn.setEnabled(has_files and has_format and not self._is_converting)

    # ---------- 持久化偏好 ----------

    def _load_settings(self) -> None:
        """启动时从配置文件恢复上次的输出目录/类别/格式/覆盖选项。"""
        self._loading_settings = True
        try:
            # 覆盖同名
            overwrite = self._settings.value('overwrite', False, type=bool)
            self._overwrite_check.setChecked(bool(overwrite))

            # 输出目录（只在还存在时恢复）
            saved_dir = self._settings.value('output_dir', '', type=str)
            if saved_dir and os.path.isdir(saved_dir):
                self._output_dir = saved_dir
                self._output_dir_label.setText(saved_dir)
                self._output_dir_label.setStyleSheet('color: #000;')

            # 类别
            cat_keys = ['video', 'audio', 'image', 'document']
            saved_cat = self._settings.value('category', 'video', type=str)
            if saved_cat not in cat_keys:
                saved_cat = 'video'
            if saved_cat in self._category_btns:
                self._category_btns[saved_cat].setChecked(True)
                self._populate_format_combo(saved_cat)

            # 上次输出格式
            saved_ext = self._settings.value('output_ext', '', type=str)
            if saved_ext:
                for i in range(self._format_combo.count()):
                    data = self._format_combo.itemData(i)
                    if data and data[0] == saved_ext:
                        self._format_combo.setCurrentIndex(i)
                        break
        finally:
            self._loading_settings = False
        self._update_start_button()

    def _save_settings(self) -> None:
        """把当前可见设置写到磁盘。任何时候调用都安全。"""
        if self._loading_settings:
            return
        # 覆盖
        self._settings.setValue('overwrite', self._overwrite_check.isChecked())
        # 输出目录
        if self._output_dir:
            self._settings.setValue('output_dir', self._output_dir)
        else:
            self._settings.remove('output_dir')
        # 当前类别
        for key, btn in self._category_btns.items():
            if btn.isChecked():
                self._settings.setValue('category', key)
                break
        # 当前格式
        data = self._format_combo.currentData()
        if data:
            self._settings.setValue('output_ext', data[0])
        self._settings.sync()

    # ---------- 表格交互 ----------

    def _on_table_double_clicked(self, item: QTableWidgetItem) -> None:
        """双击表格行 → 显示该文件的状态详情（错误堆栈或成功信息）。"""
        row = item.row()
        if row < 0:
            return
        name_item = self._table.item(row, COL_FILE_NAME)
        status_item = self._table.item(row, COL_STATUS)
        if not name_item or not status_item:
            return
        file_path = name_item.data(Qt.ItemDataRole.UserRole) or ''
        status = status_item.text()
        tip = status_item.toolTip() or '尚无更多信息'
        QMessageBox.information(
            self,
            f'{os.path.basename(file_path)} — {status}',
            f'{file_path}\n\n{tip}',
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        重写关闭事件。

        如果正在转换，询问用户是否确认退出。
        退出时绞杀所有残余进程。
        """
        if self._is_converting:
            reply = QMessageBox.question(
                self, '确认退出',
                '转换任务尚未完成，确定要退出吗？\n退出将终止所有正在进行的转换。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        # 退出前再保存一次，防止万一未触发的变更
        self._save_settings()
        # 绞杀所有工作进程
        self._orchestrator.cancel_all()
        event.accept()


APP_QSS = """
/* ============================================================
   全局基础 — 字体、底色
   ============================================================ */
* {
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC",
                 "Helvetica Neue", sans-serif;
    font-size: 10pt;
    color: #1F1F1F;
}
QMainWindow, #CentralWidget {
    background-color: #FAFAFA;
}

/* ============================================================
   标题区
   ============================================================ */
#AppTitle {
    font-size: 20pt;
    font-weight: 600;
    color: #111111;
    padding: 0;
}
#AppSubtitle {
    font-size: 10pt;
    color: #6B6B6B;
    padding-bottom: 6px;
}

/* ============================================================
   设置卡片 — 不画边框，只靠留白形成区块感
   ============================================================ */
#SettingsCard {
    background-color: transparent;
}
#FieldLabel {
    color: #4B4B4B;
    font-size: 10pt;
    font-weight: 500;
}
#SectionTitle {
    font-size: 12pt;
    font-weight: 600;
    color: #111111;
}
#SectionHint {
    color: #8A8A8A;
    font-size: 9pt;
}
#OutputPath {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 6px 12px;
    color: #4B4B4B;
}
#Divider {
    background: #ECECEC;
    border: none;
}

/* ============================================================
   分段控制器 (类别按钮组) — 一体化外壳 + 内部块
   ============================================================ */
#SegmentedControl {
    background-color: #F1F1F1;
    border-radius: 8px;
    padding: 0;
}
QPushButton#SegmentButton {
    border: none;
    background-color: transparent;
    color: #4B4B4B;
    padding: 6px 18px;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton#SegmentButton:hover:!checked {
    background-color: #E5E5E5;
    color: #1F1F1F;
}
QPushButton#SegmentButton:checked {
    background-color: #005FB8;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#SegmentButton:disabled {
    color: #B8B8B8;
}

/* ============================================================
   主 CTA — 全部开始
   ============================================================ */
QPushButton#PrimaryButton {
    background-color: #0078D7;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 700;
    font-size: 10pt;
}
QPushButton#PrimaryButton:hover {
    background-color: #005A9E;
}
QPushButton#PrimaryButton:pressed {
    background-color: #004680;
}
QPushButton#PrimaryButton:disabled {
    background-color: #CFE3F4;
    color: #FFFFFF;
}

/* ============================================================
   次要按钮 — 添加文件 / 清空 / 移除 / 取消 / 选择目录
   ============================================================ */
QPushButton#SecondaryButton {
    background-color: #F3F3F3;
    color: #1F1F1F;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
    font-weight: 500;
}
QPushButton#SecondaryButton:hover {
    background-color: #E8E8E8;
}
QPushButton#SecondaryButton:pressed {
    background-color: #D8D8D8;
}
QPushButton#SecondaryButton:disabled {
    background-color: #F7F7F7;
    color: #C2C2C2;
}

/* 兜底：未指定 objectName 的 QPushButton 也用次要风格 */
QPushButton {
    background-color: #F3F3F3;
    color: #1F1F1F;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
}
QPushButton:hover { background-color: #E8E8E8; }
QPushButton:pressed { background-color: #D8D8D8; }
QPushButton:disabled { background-color: #F7F7F7; color: #C2C2C2; }

/* ============================================================
   输入控件 — ComboBox 等
   ============================================================ */
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 6px 10px;
    color: #1F1F1F;
    selection-background-color: #E5F1FB;
    selection-color: #1F1F1F;
}
QComboBox:hover {
    border-color: #0078D7;
}
QComboBox:focus {
    border-color: #0078D7;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #E5F1FB;
    selection-color: #1F1F1F;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    padding: 6px 10px;
    border-radius: 4px;
    min-height: 22px;
}

/* ============================================================
   表格 — 扁平化、无网格、隔行变色、表头扁平
   ============================================================ */
QTableWidget#FileTable {
    background-color: #FFFFFF;
    alternate-background-color: #F7F8FA;
    border: 1px solid #ECECEC;
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: #E5F1FB;
    selection-color: #1F1F1F;
    outline: 0;
}
QTableWidget#FileTable::item {
    padding: 8px 10px;
    border: none;
}
QTableWidget#FileTable::item:selected {
    background-color: #E5F1FB;
    color: #1F1F1F;
}
QHeaderView::section {
    background-color: #FFFFFF;
    color: #4B4B4B;
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid #ECECEC;
    font-weight: 600;
    font-size: 10pt;
}
QHeaderView::section:first {
    border-top-left-radius: 8px;
}
QHeaderView::section:last {
    border-top-right-radius: 8px;
}
QTableCornerButton::section {
    background-color: #FFFFFF;
    border: none;
}

/* ============================================================
   进度条 — 细线 + 圆角，主题色
   ============================================================ */
QProgressBar#OverallProgress {
    background-color: #ECECEC;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar#OverallProgress::chunk {
    background-color: #0078D7;
    border-radius: 4px;
}
#ProgressCount {
    color: #6B6B6B;
    font-variant-numeric: tabular-nums;
}

/* ============================================================
   复选框
   ============================================================ */
QCheckBox {
    color: #4B4B4B;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #C8C8C8;
    border-radius: 4px;
    background-color: #FFFFFF;
}
QCheckBox::indicator:hover {
    border-color: #0078D7;
}
QCheckBox::indicator:checked {
    background-color: #0078D7;
    border-color: #0078D7;
    image: none;
}

/* ============================================================
   状态栏 — 与背景同色，只留一条细线
   ============================================================ */
QStatusBar#AppStatusBar {
    background-color: #FAFAFA;
    border-top: 1px solid #ECECEC;
    color: #6B6B6B;
    padding: 4px 24px;
}
QStatusBar#AppStatusBar::item {
    border: none;
}

/* ============================================================
   滚动条 — 极简
   ============================================================ */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 2px;
}
QScrollBar::handle:vertical {
    background: #D0D0D0;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #B0B0B0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px 4px 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #D0D0D0;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #B0B0B0;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: transparent;
}

/* ============================================================
   消息框
   ============================================================ */
QMessageBox {
    background-color: #FFFFFF;
}
QMessageBox QLabel {
    color: #1F1F1F;
}
QMessageBox QPushButton {
    min-width: 88px;
    padding: 6px 18px;
}

/* ============================================================
   工具提示
   ============================================================ */
QToolTip {
    background-color: #2B2B2B;
    color: #FFFFFF;
    border: none;
    padding: 6px 10px;
    border-radius: 4px;
}
"""


def _apply_windows_taskbar_identity() -> None:
    """
    让 Windows 任务栏显示我们自己的图标与名称，
    而不是宿主 python.exe 的图标。
    必须在 QApplication 创建之前调用。
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        # AppUserModelID — 任务栏分组依据，自定义后图标不再继承 python.exe
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'AllInOneConverter.App'
        )
    except Exception:
        pass


def run_app() -> None:
    """启动应用程序（供 main.py 调用）。"""
    _apply_windows_taskbar_identity()

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('全能格式转换工具')
    app.setApplicationDisplayName('全能格式转换工具')
    app.setOrganizationName('AllInOneConverter')

    icon = QIcon(get_resource_path('icon.ico'))
    app.setWindowIcon(icon)

    app.setStyleSheet(APP_QSS)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())
