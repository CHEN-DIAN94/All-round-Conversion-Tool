"""
ui.py — 全能格式转换工具主界面

基于 PyQt6 构建的工业级桌面应用界面。
支持拖拽文件、批量转换、实时进度、取消操作。
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSettings, QSize
from PyQt6.QtGui import (
    QDragEnterEvent, QDropEvent,
    QCloseEvent, QIcon,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QStatusBar, QCheckBox,
    QFrame, QButtonGroup,
    QMenu, QStackedWidget,
    QProgressDialog,
)

from workers import ConversionWorker, FileStatus, BatchOrchestrator
from utils import (
    get_resource_path,
    get_file_size_str,
    map_format_to_category,
    ensure_output_dir,
    CREATE_NO_WINDOW,
)
from formats import (
    CATEGORY_KEYS, FORMAT_BY_KEY, FORMAT_CATEGORIES,
    CATEGORY_EXTS, CONVERSION_MAP,
    COL_FILE_NAME, COL_FILE_SIZE, COL_PROGRESS, COL_STATUS, COL_COUNT,
    STATUS_COLORS, _is_legacy_doc, _collect_files_from_paths,
)
from widgets import DropableTableWidget, StatusColorDelegate, ErrorDetailDialog, AdvancedSettingsPanel


class MainWindow(QMainWindow):
    """
    主窗口。

    布局：
    ┌──────────────────────────────────────┐
    │  [图标] 全能格式转换工具               │
    │  视频 · 音频 · 图片 · 文档 — 一站式    │
    ├──────────────────────────────────────┤
    │  ┌ 设置卡片（白底圆角）──────────────┐ │
    │  │ 转换类型: [视频|音频|图片|...]    │ │
    │  │ 输出格式: [下拉框]               │ │
    │  │ 输出目录: [路径] [选择目录]       │ │
    │  │ [x] 覆盖同名文件                 │ │
    │  └──────────────────────────────────┘ │
    ├──────────────────────────────────────┤
    │  文件列表 · 支持拖拽                   │
    │  ┌──────────────────────────────────┐ │
    │  │ 文件名 | 大小 | 进度 | 状态      │ │
    │  └──────────────────────────────────┘ │
    ├──────────────────────────────────────┤
    │  总体进度: [████████░░] 3/5          │
    │  [添加][清空][移除]    [打开目录][取消][全部开始] │
    ├──────────────────────────────────────┤
    │  状态栏: 就绪                         │
    └──────────────────────────────────────┘
    """

    def __init__(self):
        super().__init__()
        self._workers: list[ConversionWorker] = []
        self._orchestrator = BatchOrchestrator()
        self._output_dir: Optional[str] = None
        self._is_converting = False
        self._start_time: float = 0  # ETA 用
        self._total_workers: int = 0
        self._completed_count: int = 0
        self._empty_state_widget: Optional[QWidget] = None
        self._advanced_settings: dict = {}  # N-09: 高级设置缓存
        # 文件去重缓存（O(1) 判重，替代 O(N) 表格扫描）
        self._file_paths_set: set[str] = set()
        # 用户偏好持久化
        self._settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            'AllInOneConverter',
            'AllInOneConverter',
        )
        self._loading_settings = False

        self._init_ui()
        self._connect_signals()
        self._load_settings()
        self._cleanup_stale_temps()

    def _init_ui(self) -> None:
        """初始化界面。"""
        self.setWindowTitle('全能格式转换工具')
        self.setMinimumSize(1000, 720)
        self.setAcceptDrops(True)

        central = QWidget()
        central.setObjectName('CentralWidget')
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # ---------- 标题区 ----------
        header = QWidget()
        header.setObjectName('HeaderArea')
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)
        header_layout.setSpacing(16)

        # 图标
        icon_label = QLabel()
        icon_label.setObjectName('AppIcon')
        icon_pixmap = QIcon(get_resource_path('icon.ico')).pixmap(QSize(44, 44))
        icon_label.setPixmap(icon_pixmap)
        icon_label.setFixedSize(44, 44)
        header_layout.addWidget(icon_label)

        # 标题文字
        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title_label = QLabel('全能格式转换工具')
        title_label.setObjectName('AppTitle')
        subtitle_label = QLabel('VIDEO  ·  AUDIO  ·  IMAGE  ·  DOCUMENT')
        subtitle_label.setObjectName('AppSubtitle')
        title_col.addWidget(title_label)
        title_col.addWidget(subtitle_label)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        # 版本标签
        version_label = QLabel('v1.0')
        version_label.setObjectName('SectionHint')
        version_label.setStyleSheet('color: #334155; font-size: 9pt;')
        header_layout.addWidget(version_label)

        layout.addWidget(header)

        # ---------- 设置卡片 ----------
        settings_card = QWidget()
        settings_card.setObjectName('SettingsCard')
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(20, 16, 20, 16)
        settings_layout.setSpacing(14)

        # 第一行：分段控制器
        cat_row = QHBoxLayout()
        cat_row.setSpacing(12)
        cat_label = QLabel('转换类型')
        cat_label.setObjectName('FieldLabel')
        cat_label.setFixedWidth(70)
        cat_row.addWidget(cat_label)

        seg_wrap = QWidget()
        seg_wrap.setObjectName('SegmentedControl')
        seg_layout = QHBoxLayout(seg_wrap)
        seg_layout.setContentsMargins(4, 4, 4, 4)
        seg_layout.setSpacing(2)

        self._category_group = QButtonGroup(self)
        self._category_btns = {}
        cat_names = [
            ('video', '视频'), ('audio', '音频'), ('image', '图片'),
            ('document', '文档'), ('spreadsheet', '表格'),
        ]
        for idx, (key, label) in enumerate(cat_names):
            btn = QPushButton(label)
            btn.setObjectName('SegmentButton')
            btn.setCheckable(True)
            btn.setMinimumWidth(86)
            btn.setMinimumHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if idx == 0:
                btn.setChecked(True)
            self._category_group.addButton(btn, idx)
            self._category_btns[key] = btn
            seg_layout.addWidget(btn)

        cat_row.addWidget(seg_wrap)
        cat_row.addStretch()
        settings_layout.addLayout(cat_row)

        # 第二行：输出格式
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(12)
        fmt_label = QLabel('输出格式')
        fmt_label.setObjectName('FieldLabel')
        fmt_label.setFixedWidth(70)
        fmt_row.addWidget(fmt_label)

        self._format_combo = QComboBox()
        self._format_combo.setObjectName('FormatCombo')
        self._format_combo.setMinimumWidth(380)
        self._format_combo.setMinimumHeight(36)
        self._format_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._populate_format_combo('video')
        fmt_row.addWidget(self._format_combo)
        fmt_row.addStretch()
        settings_layout.addLayout(fmt_row)

        # 第三行：输出目录
        dir_row = QHBoxLayout()
        dir_row.setSpacing(12)
        dir_label = QLabel('输出目录')
        dir_label.setObjectName('FieldLabel')
        dir_label.setFixedWidth(70)
        dir_row.addWidget(dir_label)

        self._output_dir_label = QLabel('与源文件同目录')
        self._output_dir_label.setObjectName('OutputPath')
        self._output_dir_label.setMinimumHeight(36)
        dir_row.addWidget(self._output_dir_label, 1)

        self._output_dir_btn = QPushButton('选择目录...')
        self._output_dir_btn.setObjectName('SecondaryButton')
        self._output_dir_btn.setMinimumHeight(36)
        self._output_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dir_row.addWidget(self._output_dir_btn)

        settings_layout.addLayout(dir_row)

        # 第四行：覆盖选项
        opts_row = QHBoxLayout()
        opts_row.setSpacing(12)
        spacer = QLabel('')
        spacer.setFixedWidth(70)
        opts_row.addWidget(spacer)
        self._overwrite_check = QCheckBox('覆盖同名文件')
        opts_row.addWidget(self._overwrite_check)
        opts_row.addStretch()
        settings_layout.addLayout(opts_row)

        layout.addWidget(settings_card)

        # ---------- 高级设置（可折叠） ----------
        self._advanced_panel = AdvancedSettingsPanel()
        self._advanced_panel.setObjectName('AdvancedSettings')
        self._advanced_panel.setVisible(False)  # 默认隐藏
        self._advanced_panel.settings_changed.connect(self._on_advanced_settings_changed)
        layout.addWidget(self._advanced_panel)

        # ---------- 分割线 ----------
        sep = QFrame()
        sep.setObjectName('Divider')
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ---------- 文件列表标题 ----------
        list_header = QHBoxLayout()
        list_header.setSpacing(8)
        list_title = QLabel('文件列表')
        list_title.setObjectName('SectionTitle')
        list_header.addWidget(list_title)
        list_hint = QLabel('支持拖拽添加  双击行查看详情')
        list_hint.setObjectName('SectionHint')
        list_header.addWidget(list_hint)
        list_header.addStretch()
        layout.addLayout(list_header)

        # ---------- 文件列表（带空状态） ----------
        self._table_stack = QStackedWidget()

        # 空状态页面
        empty_widget = QWidget()
        empty_widget.setObjectName('EmptyState')
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon = QLabel('⬇')  # 下箭头 unicode
        empty_icon.setObjectName('EmptyIcon')
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text = QLabel('拖拽文件到此处开始转换')
        empty_text.setObjectName('EmptyText')
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel('支持 MP4 · MOV · AVI · MP3 · PNG · PDF 等格式')
        empty_hint.setObjectName('SectionHint')
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setStyleSheet('color: #334155; font-size: 9pt;')
        empty_layout.addStretch()
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_text)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch()
        self._empty_state_widget = empty_widget
        self._table_stack.addWidget(empty_widget)

        # 表格页面
        self._table = DropableTableWidget(self)
        self._table.setObjectName('FileTable')
        self._table.setColumnCount(COL_COUNT)
        self._table.setHorizontalHeaderLabels(['文件名', '大小', '进度', '状态'])
        self._table.horizontalHeader().setSectionResizeMode(
            COL_FILE_NAME, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_FILE_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().resizeSection(COL_PROGRESS, 120)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setFixedHeight(40)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setMinimumHeight(200)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        # 状态列颜色代理
        self._status_delegate = StatusColorDelegate(self._table)
        self._table.setItemDelegateForColumn(COL_STATUS, self._status_delegate)

        self._table_stack.addWidget(self._table)
        self._table_stack.setCurrentIndex(0)  # 默认显示空状态

        layout.addWidget(self._table_stack, 1)

        # ---------- 总体进度 ----------
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        progress_label_static = QLabel('进度')
        progress_label_static.setObjectName('FieldLabel')
        progress_label_static.setFixedWidth(40)
        progress_row.addWidget(progress_label_static)
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName('OverallProgress')
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(14)
        progress_row.addWidget(self._progress_bar, 1)
        self._progress_label = QLabel('0 / 0')
        self._progress_label.setObjectName('ProgressCount')
        self._progress_label.setMinimumWidth(60)
        self._progress_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self._progress_label)
        layout.addLayout(progress_row)

        # ---------- 操作按钮 ----------
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        # 左侧：文件管理
        self._add_file_btn = QPushButton('＋ 添加文件')
        self._add_file_btn.setObjectName('SecondaryButton')
        self._clear_btn = QPushButton('清空')
        self._clear_btn.setObjectName('SecondaryButton')
        self._remove_selected_btn = QPushButton('移除选中')
        self._remove_selected_btn.setObjectName('SecondaryButton')
        self._advanced_btn = QPushButton('⚙ 高级设置')
        self._advanced_btn.setObjectName('SecondaryButton')
        self._advanced_btn.setCheckable(True)

        for b in (self._add_file_btn, self._clear_btn, self._remove_selected_btn, self._advanced_btn):
            b.setMinimumHeight(42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_layout.addWidget(self._add_file_btn)
        btn_layout.addWidget(self._clear_btn)
        btn_layout.addWidget(self._remove_selected_btn)
        btn_layout.addWidget(self._advanced_btn)
        btn_layout.addStretch()

        # 右侧：操作
        self._open_dir_btn = QPushButton('📂 输出目录')
        self._open_dir_btn.setObjectName('SecondaryButton')
        self._open_dir_btn.setMinimumHeight(42)
        self._open_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._cancel_btn = QPushButton('✕ 取消')
        self._cancel_btn.setObjectName('DangerButton')
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setMinimumHeight(42)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._start_btn = QPushButton('▶  全部开始')
        self._start_btn.setObjectName('PrimaryButton')
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumHeight(42)
        self._start_btn.setMinimumWidth(150)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_layout.addWidget(self._open_dir_btn)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._start_btn)

        layout.addLayout(btn_layout)

        # ---------- 状态栏 ----------
        self._status_bar = QStatusBar()
        self._status_bar.setObjectName('AppStatusBar')
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage('就绪')

        self.resize(1060, 760)

    def _update_empty_state(self) -> None:
        """根据文件列表是否为空切换空状态/表格。"""
        if self._table.rowCount() == 0:
            self._table_stack.setCurrentIndex(0)
        else:
            self._table_stack.setCurrentIndex(1)

    def _populate_format_combo(self, category_key: str = 'video') -> None:
        """根据选中类别填充输出格式下拉框。"""
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
        self._open_dir_btn.clicked.connect(self._on_open_output_dir)
        self._advanced_btn.clicked.connect(self._on_toggle_advanced)
        self._category_group.idClicked.connect(self._on_category_changed)
        self._format_combo.currentIndexChanged.connect(self._update_start_button)
        self._format_combo.currentIndexChanged.connect(self._save_settings)
        self._overwrite_check.stateChanged.connect(self._save_settings)
        self._table.itemDoubleClicked.connect(self._on_table_double_clicked)

    # ---------- 拖拽支持 ----------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            raw_paths = [url.toLocalFile() for url in event.mimeData().urls()]
            files = _collect_files_from_paths(raw_paths)
            if files:
                self.add_files_to_table(files)
            event.acceptProposedAction()

    # ---------- 文件列表管理 ----------

    def add_files_to_table(self, file_paths: list[str]) -> None:
        """将文件添加到表格。"""
        if len(file_paths) >= 500:
            QMessageBox.information(self, '提示', '最多同时添加 500 个文件，已截断。')
        first_category = None
        added_count = 0
        for fp in file_paths:
            abs_fp = os.path.abspath(fp)
            if abs_fp in self._file_paths_set:
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)

            # 文件名
            name_item = QTableWidgetItem(os.path.basename(fp))
            name_item.setData(Qt.ItemDataRole.UserRole, fp)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, COL_FILE_NAME, name_item)

            # 大小
            size_item = QTableWidgetItem(get_file_size_str(fp))
            size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, COL_FILE_SIZE, size_item)

            # 进度条 widget
            progress_bar = QProgressBar()
            progress_bar.setObjectName('CellProgress')
            progress_bar.setMinimum(0)
            progress_bar.setMaximum(100)
            progress_bar.setValue(0)
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(8)
            self._table.setCellWidget(row, COL_PROGRESS, progress_bar)

            # 状态
            status_item = QTableWidgetItem(FileStatus.WAITING)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_STATUS, status_item)

            # 同步更新去重缓存
            self._file_paths_set.add(abs_fp)

            if first_category is None:
                ext = Path(fp).suffix.lower().lstrip('.')
                first_category = map_format_to_category(ext)
            added_count += 1

        # 自动跳转到对应类别
        if first_category and first_category != 'unknown':
            self._switch_category(first_category)

        # 如果当前输出格式与输入文件同扩展名，自动选下一个
        if first_category and first_category != 'unknown' and added_count > 0:
            first_ext = Path(file_paths[0]).suffix.lower()
            fmt_data = self._format_combo.currentData()
            if fmt_data and fmt_data[0] == first_ext:
                for i in range(self._format_combo.count()):
                    data = self._format_combo.itemData(i)
                    if data and data[0] != first_ext:
                        self._format_combo.setCurrentIndex(i)
                        break

        if added_count > 0:
            self._status_bar.showMessage(f'已添加 {added_count} 个文件')

        self._update_start_button()
        self._update_empty_state()

    def _is_file_in_table(self, file_path: str) -> bool:
        """检查文件是否已在表格中（O(1) set 查找）。"""
        return os.path.abspath(file_path) in self._file_paths_set

    def _switch_category(self, category_key: str) -> None:
        """切换到指定类别。"""
        if category_key in self._category_btns:
            btn = self._category_btns[category_key]
            if not btn.isChecked():
                btn.setChecked(True)
                self._populate_format_combo(category_key)
                self._update_start_button()

    def _on_category_changed(self, idx: int) -> None:
        """类别切换时更新格式下拉框。"""
        cat_keys = CATEGORY_KEYS
        if 0 <= idx < len(cat_keys):
            self._populate_format_combo(cat_keys[idx])
            self._update_start_button()
            self._save_settings()

    _CATEGORY_FILTERS = {
        'video': '视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.ts *.3gp *.ogv *.m2ts *.vob)',
        'audio': '音频文件 (*.mp3 *.wav *.flac *.aac *.ogg *.wma *.m4a *.opus *.ac3 *.dts *.ape *.aiff)',
        'image': '图片文件 (*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.tif *.webp *.ico *.svg)',
        'document': '文档文件 (*.pdf *.docx *.doc *.txt *.rtf *.html *.htm *.md)',
        'spreadsheet': '表格文件 (*.xlsx *.xls)',
    }

    def _on_add_file(self) -> None:
        """点击「添加文件」。"""
        current_cat = 'video'
        for key, btn in self._category_btns.items():
            if btn.isChecked():
                current_cat = key
                break
        cat_filter = self._CATEGORY_FILTERS.get(current_cat, '')
        filter_str = f'{cat_filter};;所有文件 (*.*)'
        files, _ = QFileDialog.getOpenFileNames(
            self, '选择要转换的文件', '', filter_str,
        )
        if files:
            self.add_files_to_table(files)

    def _on_clear(self) -> None:
        """清空列表。"""
        if self._is_converting:
            QMessageBox.warning(self, '警告', '转换进行中，请先取消。')
            return
        self._table.setRowCount(0)
        self._file_paths_set.clear()  # 同步清空去重缓存
        self._progress_bar.setValue(0)
        self._progress_label.setText('0 / 0')
        self._update_start_button()
        self._update_empty_state()

    def _on_remove_selected(self) -> None:
        """移除选中行。"""
        if self._is_converting:
            QMessageBox.warning(self, '警告', '转换进行中，请先取消。')
            return
        selected_rows = set()
        for item in self._table.selectedItems():
            selected_rows.add(item.row())
        for row in sorted(selected_rows, reverse=True):
            self._table.removeRow(row)
        # 重建去重缓存（比逐行 discard 更可靠）
        self._file_paths_set = set()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_FILE_NAME)
            if item:
                fp = item.data(Qt.ItemDataRole.UserRole)
                if fp:
                    self._file_paths_set.add(os.path.abspath(fp))
        self._update_start_button()
        self._update_empty_state()

    # ---------- 高级设置 ----------

    def _on_toggle_advanced(self, checked: bool) -> None:
        """切换高级设置面板显示/隐藏。"""
        self._advanced_panel.setVisible(checked)
        if checked:
            self._advanced_btn.setText('⚙ 收起设置')
        else:
            self._advanced_btn.setText('⚙ 高级设置')

    def _on_advanced_settings_changed(self, settings: dict) -> None:
        """高级设置变更回调。"""
        self._advanced_settings = settings
        self._save_settings()
        self._status_bar.showMessage('高级设置已更新', 2000)

    # ---------- 输出目录 ----------

    def _on_select_output_dir(self) -> None:
        """选择输出目录。"""
        start = self._output_dir or ''
        dir_path = QFileDialog.getExistingDirectory(self, '选择输出目录', start)
        if dir_path:
            self._output_dir = dir_path
            self._output_dir_label.setText(dir_path)
            self._save_settings()

    def _on_open_output_dir(self) -> None:
        """打开输出目录。"""
        target = self._output_dir
        if not target:
            if self._table.rowCount() > 0:
                item = self._table.item(0, COL_FILE_NAME)
                if item:
                    fp = item.data(Qt.ItemDataRole.UserRole)
                    if fp:
                        target = str(Path(fp).parent)
        if not target or not os.path.isdir(target):
            QMessageBox.information(self, '提示', '暂无可打开的输出目录。')
            return
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', target], creationflags=CREATE_NO_WINDOW)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        else:
            subprocess.Popen(['xdg-open', target])

    # ---------- 转换控制 ----------

    def _on_start_all(self) -> None:
        """全部开始转换。"""
        row_count = self._table.rowCount()
        if row_count == 0:
            return

        # 校验文件存在性
        missing = []
        valid_files: set[str] = set()
        for row in range(row_count):
            item = self._table.item(row, COL_FILE_NAME)
            if item:
                fp = item.data(Qt.ItemDataRole.UserRole)
                if fp and os.path.isfile(fp):
                    valid_files.add(fp)
                elif fp:
                    missing.append(os.path.basename(fp))
        if missing:
            QMessageBox.warning(
                self, '文件不存在',
                '以下文件已被移动或删除：\n\n' + '\n'.join(missing[:10])
                + ('\n...' if len(missing) > 10 else ''),
            )
            return

        fmt_data = self._format_combo.currentData()
        if not fmt_data:
            QMessageBox.warning(self, '提示', '请先选择输出格式。')
            return
        output_ext, category_key = fmt_data

        # 重置状态
        for row in range(row_count):
            self._table.item(row, COL_STATUS).setText(FileStatus.WAITING)
            progress_bar = self._table.cellWidget(row, COL_PROGRESS)
            if isinstance(progress_bar, QProgressBar):
                progress_bar.setValue(0)

        # 创建 worker
        workers = []
        for row in range(row_count):
            input_path = self._table.item(row, COL_FILE_NAME).data(
                Qt.ItemDataRole.UserRole)
            if not input_path or input_path not in valid_files:
                self._table.item(row, COL_STATUS).setText(FileStatus.FAILED)
                continue

            output_path = self._generate_output_path(input_path, output_ext)
            conv_type = self._determine_conv_type(input_path, output_ext)

            if conv_type is None:
                self._table.item(row, COL_STATUS).setText(FileStatus.FAILED)
                # M-01: .doc 格式给出具体提示
                input_ext = Path(input_path).suffix.lower()
                if input_ext == '.doc' and output_ext == '.pdf':
                    tip = '旧版 .doc 格式不支持直接转换，请先用 Word 另存为 .docx'
                else:
                    tip = f'不支持的转换: {Path(input_path).suffix} -> {output_ext}'
                self._table.item(row, COL_FILE_NAME).setToolTip(tip)
                continue

            worker = ConversionWorker(
                row, input_path, output_path, conv_type,
                settings=self._advanced_settings,  # N-09: 传递高级设置
            )
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        if not workers:
            return

        self._workers = workers
        self._total_workers = len(workers)
        # FIX-07/NEW-12: 文档/表格类转换限制并发为 1（COM 线程安全）
        # 必须在 add_worker 之前设置 semaphore，否则 worker 引用旧对象
        if category_key in ('document', 'spreadsheet'):
            from PyQt6.QtCore import QSemaphore
            self._orchestrator = BatchOrchestrator(max_concurrency=1)
        else:
            self._orchestrator = BatchOrchestrator()
        for w in workers:
            self._orchestrator.add_worker(w)

        # 转换模式
        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        # H-01: total 使用实际参与转换的 worker 数量
        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在转换 {len(workers)} 个文件...')

        self._orchestrator.start_all()

    def _on_cancel(self) -> None:
        """取消所有转换。"""
        self._status_bar.showMessage('正在取消...')
        self._set_controls_enabled(False)
        self._orchestrator.cancel_all()

    def _on_status_updated(self, file_index: int, status: str) -> None:
        """更新状态列。"""
        if file_index < self._table.rowCount():
            item = self._table.item(file_index, COL_STATUS)
            if item:
                item.setText(status)

    def _on_progress_updated(self, file_index: int, percent: int) -> None:
        """更新进度列（进度条 widget）。"""
        if file_index < self._table.rowCount():
            progress_bar = self._table.cellWidget(file_index, COL_PROGRESS)
            if isinstance(progress_bar, QProgressBar):
                progress_bar.setValue(percent)

    def _on_task_finished(self, file_index: int, success: bool, message: str) -> None:
        """单个任务完成。"""
        if 0 <= file_index < self._table.rowCount():
            status_item = self._table.item(file_index, COL_STATUS)
            name_item = self._table.item(file_index, COL_FILE_NAME)
            tip = message or ('转换完成' if success else '转换失败')
            if status_item:
                status_item.setToolTip(tip)
            if name_item:
                name_item.setToolTip(
                    f'{name_item.data(Qt.ItemDataRole.UserRole)}\n\n'
                    f'{"失败: " if not success else "成功: "}{tip}'
                )

        # 更新总体进度（用 self._completed_count 计数，不依赖线程状态查询）
        self._completed_count += 1
        completed = self._completed_count
        total = self._total_workers
        self._progress_label.setText(f'{completed} / {total}')
        if total > 0:
            pct = int(completed / total * 100)
            self._progress_bar.setValue(pct)

            # ETA
            if completed > 0 and pct < 100:
                elapsed = time.monotonic() - self._start_time
                remaining = elapsed / completed * (total - completed)
                mins, secs = divmod(int(remaining), 60)
                self._status_bar.showMessage(
                    f'已完成 {completed}/{total} 个文件  预计剩余 {mins}分{secs:02d}秒'
                )
            else:
                self._status_bar.showMessage(f'已完成 {completed}/{total} 个文件')

        # 全部完成检查（以计数器为准，消除竞态）
        if self._is_converting and completed >= total:
            self._on_all_finished()

    def _on_all_finished(self) -> None:
        """所有任务完成。"""
        if not self._is_converting:
            return  # 防止重复调用
        self._is_converting = False
        self._set_controls_enabled(True)

        # 统计（total 改为表格行数，与遍历口径一致）
        total = self._table.rowCount()
        success = failed = cancelled = 0
        for row in range(total):
            item = self._table.item(row, COL_STATUS)
            if not item:
                continue
            text = item.text()
            if text == FileStatus.SUCCESS:
                success += 1
            elif text == FileStatus.FAILED:
                failed += 1
            elif text == FileStatus.CANCELLED:
                cancelled += 1

        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        mins, secs = divmod(int(elapsed), 60)
        msg = f'转换完成：成功 {success}，失败 {failed}，取消 {cancelled}，共 {total} 个（耗时 {mins}分{secs:02d}秒）'
        self._status_bar.showMessage(msg)

        if failed > 0:
            QMessageBox.information(
                self, '转换完成',
                msg + '\n\n双击失败的文件行可查看具体错误原因。',
            )

        self._workers.clear()
        self._orchestrator.clear_all()
        self._update_start_button()

    # ---------- 临时文件管理 ----------

    def _cleanup_stale_temps(self) -> None:
        """清理上次崩溃残留的临时文件（.~tmp.*）。弹窗确认后删除。"""
        import glob
        dirs_to_scan = set()
        # 仅扫描用户设置的输出目录（不扫描 Desktop/Downloads，避免误删）
        if self._output_dir and os.path.isdir(self._output_dir):
            dirs_to_scan.add(self._output_dir)

        stale = []
        for d in dirs_to_scan:
            for tmp in glob.glob(os.path.join(d, '*.~tmp.*')):
                stale.append(tmp)

        if stale:
            reply = QMessageBox.question(
                self, '发现残留临时文件',
                f'发现 {len(stale)} 个未清理的临时文件，是否删除？\n\n'
                + '\n'.join(stale[:5]) + ('...' if len(stale) > 5 else ''),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                for f in stale:
                    try:
                        os.remove(f)
                    except OSError:
                        pass

    # ---------- 辅助方法 ----------

    def _set_controls_enabled(self, enabled: bool) -> None:
        """统一启用/禁用所有操作控件。"""
        self._start_btn.setEnabled(enabled)
        self._cancel_btn.setEnabled(not enabled)
        self._add_file_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        self._remove_selected_btn.setEnabled(enabled)
        self._format_combo.setEnabled(enabled)
        self._output_dir_btn.setEnabled(enabled)
        for btn in self._category_btns.values():
            btn.setEnabled(enabled)

    def _generate_output_path(self, input_path: str, output_ext: str) -> str:
        """生成输出路径。"""
        input_stem = Path(input_path).stem
        if self._output_dir:
            output_path = os.path.join(self._output_dir, input_stem + output_ext)
        else:
            output_path = str(Path(input_path).with_suffix(output_ext))

        if not self._overwrite_check.isChecked():
            output_path = self._avoid_overwrite(output_path)

        ensure_output_dir(output_path)
        return output_path

    def _avoid_overwrite(self, file_path: str) -> str:
        """自动添加数字后缀避免覆盖。上限 9999，超出抛 OSError。"""
        if not os.path.exists(file_path):
            return file_path

        p = Path(file_path)
        stem = p.stem
        suffix = p.suffix
        parent = p.parent

        for counter in range(1, 10000):
            new_path = str(parent / f'{stem} ({counter}){suffix}')
            if not os.path.exists(new_path):
                return new_path
        raise RuntimeError(f'无法生成不重复的文件名，已尝试 9999 次: {file_path}')

    def _determine_conv_type(self, input_path: str, output_ext: str) -> Optional[str]:
        """确定转换类型。"""
        input_ext = Path(input_path).suffix.lower()
        category = map_format_to_category(input_ext)

        if category == 'document':
            if input_ext == '.pdf' and output_ext == '.docx':
                return 'pdf_to_docx'
            elif input_ext == '.docx' and output_ext == '.pdf':
                return 'docx_to_pdf'
            elif input_ext == '.doc' and output_ext == '.pdf':
                if _is_legacy_doc(input_path):
                    return None  # 旧版 .doc 二进制格式，docx2pdf 不支持
                return 'docx_to_pdf'
            return None

        if category == 'spreadsheet':
            if input_ext in ('.xlsx', '.xls') and output_ext in ('.png', '.jpg', '.jpeg'):
                return 'excel_to_image'
            return None

        if category in ('video', 'audio', 'image'):
            if input_ext == output_ext:
                return None
            key = (category, output_ext)
            if key in CONVERSION_MAP:
                return CONVERSION_MAP[key]
            return category

        return None

    def _update_start_button(self) -> None:
        """更新开始按钮状态。"""
        has_files = self._table.rowCount() > 0
        has_format = self._format_combo.currentData() is not None
        self._start_btn.setEnabled(has_files and has_format and not self._is_converting)

    # ---------- 持久化偏好 ----------

    def _load_settings(self) -> None:
        """启动时恢复设置。"""
        self._loading_settings = True
        try:
            overwrite = self._settings.value('overwrite', False, type=bool)
            self._overwrite_check.setChecked(bool(overwrite))

            saved_dir = self._settings.value('output_dir', '', type=str)
            if saved_dir and os.path.isdir(saved_dir):
                self._output_dir = saved_dir
                self._output_dir_label.setText(saved_dir)

            cat_keys = CATEGORY_KEYS
            saved_cat = self._settings.value('category', 'video', type=str)
            if saved_cat not in cat_keys:
                saved_cat = 'video'
            if saved_cat in self._category_btns:
                self._category_btns[saved_cat].setChecked(True)
                self._populate_format_combo(saved_cat)

            # 设置恢复增加类别校验
            saved_ext = self._settings.value('output_ext', '', type=str)
            if saved_ext:
                # 校验 saved_ext 是否在当前类别的可选格式中
                valid_exts = {ext for _, ext, _ in FORMAT_BY_KEY.get(
                    saved_cat, ('', []))[1]}
                if saved_ext in valid_exts:
                    for i in range(self._format_combo.count()):
                        data = self._format_combo.itemData(i)
                        if data and data[0] == saved_ext:
                            self._format_combo.setCurrentIndex(i)
                            break
                else:
                    # 旧值不在当前类别中，清除
                    self._settings.remove('output_ext')

            # N-09: 加载高级设置
            self._settings.beginGroup('AdvancedSettings')
            for key, default in AdvancedSettingsPanel.DEFAULTS.items():
                val = self._settings.value(key, default)
                # 类型转换
                if isinstance(default, int):
                    val = int(val)
                elif isinstance(default, str):
                    val = str(val)
                self._advanced_settings[key] = val
            self._settings.endGroup()
            self._advanced_panel.set_settings(self._advanced_settings)

        finally:
            self._loading_settings = False
        self._update_start_button()

    def _save_settings(self) -> None:
        """保存设置到磁盘。"""
        if self._loading_settings:
            return
        self._settings.setValue('overwrite', self._overwrite_check.isChecked())
        if self._output_dir:
            self._settings.setValue('output_dir', self._output_dir)
        else:
            self._settings.remove('output_dir')
        for key, btn in self._category_btns.items():
            if btn.isChecked():
                self._settings.setValue('category', key)
                break
        data = self._format_combo.currentData()
        if data:
            self._settings.setValue('output_ext', data[0])

        # N-09: 保存高级设置
        self._settings.beginGroup('AdvancedSettings')
        for key, value in self._advanced_settings.items():
            self._settings.setValue(key, value)
        self._settings.endGroup()

        self._settings.sync()

    # ---------- 表格交互 ----------

    def _on_table_double_clicked(self, item: QTableWidgetItem) -> None:
        """双击行查看详情（失败文件弹出详情对话框）。"""
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

        if status == FileStatus.FAILED:
            # 失败文件：弹出详情对话框
            dialog = ErrorDetailDialog(file_path, tip, self)
            dialog.exec()
        else:
            QMessageBox.information(
                self,
                f'{os.path.basename(file_path)} — {status}',
                f'{file_path}\n\n{tip}',
            )

    def _on_table_context_menu(self, pos) -> None:
        """右键菜单。"""
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        status_item = self._table.item(row, COL_STATUS)
        status_text = status_item.text() if status_item else ''

        if self._is_converting and status_text == FileStatus.CONVERTING:
            cancel_action = menu.addAction('取消此文件')
            cancel_action.triggered.connect(lambda checked, r=row: self._cancel_single(r))
        elif status_text == FileStatus.FAILED:
            detail_action = menu.addAction('查看详情')
            detail_action.triggered.connect(
                lambda: self._on_table_double_clicked(
                    self._table.item(row, COL_FILE_NAME))
            )

        # 导出失败报告（有失败文件时显示）
        has_failures = self._has_failed_files()
        if has_failures:
            menu.addSeparator()
            export_action = menu.addAction('导出失败报告')
            export_action.triggered.connect(self._export_failure_report)

        if not menu.isEmpty():
            menu.exec(self._table.viewport().mapToGlobal(pos))

    def _cancel_single(self, row: int) -> None:
        """取消单个文件。"""
        for worker in self._workers:
            if worker.file_index == row and worker.isRunning():
                worker.cancel()
                self._status_bar.showMessage(
                    f'已取消: {os.path.basename(worker.input_path)}')
                return

    def _has_failed_files(self) -> bool:
        """检查是否有失败的文件。"""
        for row in range(self._table.rowCount()):
            status_item = self._table.item(row, COL_STATUS)
            if status_item and status_item.text() == FileStatus.FAILED:
                return True
        return False

    def _export_failure_report(self) -> None:
        """导出失败报告为 Markdown 文件。"""
        from datetime import datetime

        # 收集失败文件
        failures = []
        for row in range(self._table.rowCount()):
            status_item = self._table.item(row, COL_STATUS)
            if status_item and status_item.text() == FileStatus.FAILED:
                name_item = self._table.item(row, COL_FILE_NAME)
                file_path = name_item.data(Qt.ItemDataRole.UserRole) if name_item else ''
                error_msg = status_item.toolTip() or '未知错误'
                failures.append((file_path, error_msg))

        if not failures:
            QMessageBox.information(self, '导出报告', '没有失败的转换任务')
            return

        # 生成报告
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report = '# 转换失败报告\n\n'
        report += f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
        report += f'失败数量: {len(failures)}\n\n'

        for i, (path, error) in enumerate(failures, 1):
            report += f'## {i}. {os.path.basename(path)}\n\n'
            report += f'**文件路径**: `{path}`\n\n'
            report += f'**错误信息**:\n```\n{error}\n```\n\n'
            report += '---\n\n'

        # 保存文件
        file_path, _ = QFileDialog.getSaveFileName(
            self, '保存失败报告',
            f'转换失败报告_{timestamp}.md',
            'Markdown 文件 (*.md);;所有文件 (*.*)',
        )

        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(report)
            QMessageBox.information(self, '导出成功', f'报告已保存到:\n{file_path}')

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭事件（优雅退出三步协议）。"""
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

        self._save_settings()

        # 优雅退出三步协议
        if self._orchestrator and self._orchestrator.workers:
            # Step 1: 发送取消信号
            self._orchestrator.cancel_all()

            # Step 2: 等待所有 worker 退出（最多 5 秒），显示进度对话框
            progress = QProgressDialog("正在安全退出...", None, 0, 0, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.show()
            QApplication.processEvents()

            self._orchestrator.wait_all(5000)

            progress.close()

        event.accept()


def _load_stylesheet() -> str:
    """从 styles.qss 加载样式表。"""
    qss_path = get_resource_path('styles.qss')
    try:
        with open(qss_path, encoding='utf-8') as f:
            return f.read()
    except (OSError, IOError):
        return ''


def _apply_windows_taskbar_identity() -> None:
    """让 Windows 任务栏显示自己的图标与名称。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'AllInOneConverter.App'
        )
    except Exception:
        pass


def run_app() -> None:
    """启动应用程序。"""
    _apply_windows_taskbar_identity()

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('全能格式转换工具')
    app.setApplicationDisplayName('全能格式转换工具')
    app.setOrganizationName('AllInOneConverter')

    icon = QIcon(get_resource_path('icon.ico'))
    app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())
