"""
ui.py — 流光主界面

基于 PyQt6 构建的工业级桌面应用界面。
支持拖拽文件、批量转换、实时进度、取消操作。

拆分为 3 个 mixin 文件：
- ui_file_table.py: FileTableMixin — 文件表格管理
- ui_conversion.py: ConversionMixin — 转换控制
- ui_settings.py: SettingsMixin — 设置/主题/布局
"""


__all__ = ['MainWindow', 'run_app']

import os
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QSettings, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QHeaderView, QTableWidget,
    QPushButton, QComboBox, QLabel, QProgressBar,
    QCheckBox,
    QFrame, QButtonGroup,
    QStackedWidget, QStatusBar,
)

from workers import ConversionWorker, BatchOrchestrator
from utils import get_resource_path
from formats import (
    COL_FILE_NAME, COL_FILE_SIZE, COL_PROGRESS, COL_STATUS, COL_COUNT,
)
from widgets import DropableTableWidget, StatusColorDelegate, AdvancedSettingsPanel, PreviewPanel, ToolPanel, HistoryDialog, PresetCombo
from constants import (
    VERSION,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT,
)
from themes import get_theme_keys, get_theme_display

# 导入 mixin
from ui_file_table import FileTableMixin
from ui_conversion import ConversionMixin
from ui_settings import SettingsMixin


class MainWindow(FileTableMixin, ConversionMixin, SettingsMixin, QMainWindow):
    """
    主窗口。

    布局：
    ┌──────────────────────────────────────┐
    │  [图标] 流光                          │
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
            'LiuGuang',
            'LiuGuang',
        )
        self._loading_settings = False
        self._file_counter = 1  # 命名模板序号计数器

        self._init_ui()
        self._connect_signals()
        self._load_settings()
        self._cleanup_stale_temps()
        self._check_ffmpeg()

    def _init_ui(self) -> None:
        """初始化界面。"""
        self.setWindowTitle('流光')
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
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
        title_label = QLabel('流光')
        title_label.setObjectName('AppTitle')
        subtitle_label = QLabel('VIDEO  ·  AUDIO  ·  IMAGE  ·  DOCUMENT')
        subtitle_label.setObjectName('AppSubtitle')
        title_col.addWidget(title_label)
        title_col.addWidget(subtitle_label)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        # 版本标签
        version_label = QLabel(f'v{VERSION}')
        version_label.setObjectName('SectionHint')
        version_label.setStyleSheet('font-size: 9pt;')
        header_layout.addWidget(version_label)

        # 主题切换
        self._theme_combo = QComboBox()
        self._theme_combo.setObjectName('ThemeCombo')
        self._theme_combo.setMinimumWidth(120)
        self._theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key in get_theme_keys():
            display = get_theme_display(key)
            self._theme_combo.addItem(display, key)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        header_layout.addWidget(self._theme_combo)

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
            ('tools', '🔧 工具'),
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
        self._fmt_row_widget = fmt_row  # 保存引用以便隐藏

        # 工具面板（工具类别时显示，替代格式行）
        self._tool_panel = ToolPanel()
        self._tool_panel.setVisible(False)
        settings_layout.addWidget(self._tool_panel)

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

        # 第五行：命名模板
        tmpl_row = QHBoxLayout()
        tmpl_row.setSpacing(12)
        tmpl_label = QLabel('命名模板')
        tmpl_label.setObjectName('FieldLabel')
        tmpl_label.setFixedWidth(70)
        tmpl_row.addWidget(tmpl_label)

        self._template_input = QComboBox()
        self._template_input.setEditable(True)
        self._template_input.setMinimumHeight(36)
        self._template_input.setMinimumWidth(380)
        self._template_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self._template_input.addItems([
            '{原名}.{ext}',
            '{原名}_{序号}.{ext}',
            '{原名}_{日期}.{ext}',
            '{日期}_{序号}.{ext}',
        ])
        self._template_input.setCurrentText('{原名}.{ext}')
        self._template_input.currentTextChanged.connect(self._save_settings)
        tmpl_row.addWidget(self._template_input)

        tmpl_hint = QLabel('{原名} {日期} {序号} {格式}')
        tmpl_hint.setObjectName('SectionHint')
        tmpl_row.addWidget(tmpl_hint)
        tmpl_row.addStretch()
        settings_layout.addLayout(tmpl_row)

        # 第六行：快速预设
        self._preset_combo = PresetCombo()
        self._preset_combo.preset_applied.connect(self._on_preset_applied)
        settings_layout.addWidget(self._preset_combo)

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

        # ---------- 预览面板 ----------
        self._preview_panel = PreviewPanel(self)
        layout.addWidget(self._preview_panel)

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

        # 历史按钮
        self._history_btn = QPushButton('📜 历史')
        self._history_btn.setObjectName('SecondaryButton')
        self._history_btn.setMinimumHeight(42)
        self._history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._history_btn.clicked.connect(self._on_show_history)
        btn_layout.addWidget(self._history_btn)
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

        self._pause_btn = QPushButton('⏸ 暂停')
        self._pause_btn.setObjectName('SecondaryButton')
        self._pause_btn.setEnabled(False)
        self._pause_btn.setMinimumHeight(42)
        self._pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_btn.setVisible(False)

        self._retry_btn = QPushButton('↻ 重试失败')
        self._retry_btn.setObjectName('SecondaryButton')
        self._retry_btn.setVisible(False)
        self._retry_btn.setMinimumHeight(42)
        self._retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._start_btn = QPushButton('▶  全部开始')
        self._start_btn.setObjectName('PrimaryButton')
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumHeight(42)
        self._start_btn.setMinimumWidth(150)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_layout.addWidget(self._open_dir_btn)
        btn_layout.addWidget(self._retry_btn)
        btn_layout.addWidget(self._pause_btn)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._start_btn)

        layout.addLayout(btn_layout)

        # ---------- 状态栏 ----------
        self._status_bar = QStatusBar()
        self._status_bar.setObjectName('AppStatusBar')
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage('就绪')

        self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)


def _apply_windows_taskbar_identity() -> None:
    """Windows 任务栏图标独立（避免 Python 图标）。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        from constants import VERSION
        myappid = f'LiuGuang.Converter.{VERSION}'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass


def run_app() -> None:
    """启动应用程序。"""
    _apply_windows_taskbar_identity()

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('流光')
    app.setApplicationDisplayName('流光')
    app.setOrganizationName('LiuGuang')

    icon = QIcon(get_resource_path('icon.ico'))
    app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())
