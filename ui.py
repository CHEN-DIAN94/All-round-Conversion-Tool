"""
ui.py — 全能格式转换工具主界面

基于 PyQt6 构建的工业级桌面应用界面。
支持拖拽文件、批量转换、实时进度、取消操作。
"""

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
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
        ('PDF (.pdf)',  '.pdf', '便携式文档格式'),
        ('DOCX (.docx)','.docx','Word 文档格式'),
        ('TXT (.txt)',  '.txt', '纯文本文件'),
        ('RTF (.rtf)',  '.rtf', '富文本格式'),
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

        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        """初始化界面。"""
        self.setWindowTitle('全能格式转换工具')
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ---------- 顶部：格式选择 ----------
        top_group = QGroupBox('转换设置')
        top_layout = QGridLayout(top_group)

        # 第一行：选择转换类别
        top_layout.addWidget(QLabel('转换类型:'), 0, 0)
        self._category_group = QButtonGroup(self)
        category_layout = QHBoxLayout()
        category_layout.setSpacing(6)
        self._category_btns = {}
        cat_names = [
            ('video', '视频'),
            ('audio', '音频'),
            ('image', '图片'),
            ('document', '文档'),
        ]
        for idx, (key, label) in enumerate(cat_names):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumWidth(70)
            btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 16px;
                    border: 2px solid #ccc;
                    border-radius: 4px;
                    background-color: #f0f0f0;
                    font-weight: normal;
                }
                QPushButton:checked {
                    border-color: #0078D4;
                    background-color: #0078D4;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover:!checked {
                    background-color: #e0e0e0;
                    border-color: #999;
                }
            """)
            if idx == 0:
                btn.setChecked(True)
            self._category_group.addButton(btn, idx)
            self._category_btns[key] = btn
            category_layout.addWidget(btn)
        category_layout.addStretch()
        top_layout.addLayout(category_layout, 0, 1, 1, 3)

        # 第二行：输出格式
        top_layout.addWidget(QLabel('输出格式:'), 1, 0)
        self._format_combo = QComboBox()
        self._format_combo.setMinimumWidth(350)
        self._populate_format_combo('video')  # 默认选中视频类别
        top_layout.addWidget(self._format_combo, 1, 1)

        self._output_dir_btn = QPushButton('选择输出目录...')
        top_layout.addWidget(self._output_dir_btn, 1, 2)

        self._output_dir_label = QLabel('与源文件同目录')
        self._output_dir_label.setStyleSheet('color: #666;')
        top_layout.addWidget(self._output_dir_label, 1, 3)

        self._overwrite_check = QCheckBox('覆盖同名文件')
        top_layout.addWidget(self._overwrite_check, 2, 1)

        layout.addWidget(top_group)

        # ---------- 中部：文件列表 ----------
        layout.addWidget(QLabel('文件列表（支持拖拽添加）:'))

        self._table = DropableTableWidget(self)
        self._table.setColumnCount(COL_COUNT)
        self._table.setHorizontalHeaderLabels(['文件名', '大小', '进度', '状态'])
        self._table.horizontalHeader().setSectionResizeMode(COL_FILE_NAME, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(COL_FILE_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setMinimumHeight(250)
        layout.addWidget(self._table)

        # ---------- 底部：进度与操作 ----------
        # 总体进度
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel('总体进度:'))
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        progress_layout.addWidget(self._progress_bar)
        self._progress_label = QLabel('0 / 0')
        progress_layout.addWidget(self._progress_label)
        layout.addLayout(progress_layout)

        # 按钮行
        btn_layout = QHBoxLayout()

        self._add_file_btn = QPushButton('添加文件')
        self._clear_btn = QPushButton('清空列表')
        self._remove_selected_btn = QPushButton('移除选中')
        self._start_btn = QPushButton('全部开始')
        self._start_btn.setEnabled(False)
        self._start_btn.setStyleSheet(
            'QPushButton { background-color: #0078D4; color: white; '
            'padding: 6px 20px; font-weight: bold; border-radius: 4px; }'
            'QPushButton:hover { background-color: #106EBE; }'
            'QPushButton:disabled { background-color: #ccc; color: #888; }'
        )
        self._cancel_btn = QPushButton('取消')
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(
            'QPushButton { background-color: #D32F2F; color: white; '
            'padding: 6px 20px; font-weight: bold; border-radius: 4px; }'
            'QPushButton:hover { background-color: #B71C1C; }'
            'QPushButton:disabled { background-color: #ccc; color: #888; }'
        )

        btn_layout.addWidget(self._add_file_btn)
        btn_layout.addWidget(self._clear_btn)
        btn_layout.addWidget(self._remove_selected_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._start_btn)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

        # ---------- 状态栏 ----------
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage('就绪')

        # 窗口初始大小
        self.resize(950, 650)

    def _populate_format_combo(self, category_key: str = 'video') -> None:
        """根据选中类别填充输出格式下拉框。"""
        self._format_combo.clear()
        self._format_combo.addItem('— 请选择输出格式 —', None)
        self._format_combo.insertSeparator(self._format_combo.count())

        cat_info = FORMAT_BY_KEY.get(category_key)
        if not cat_info:
            return

        title, items = cat_info
        for label, ext, desc in items:
            display = f'{label}  —  {desc}'
            self._format_combo.addItem(display, (ext, category_key))

    def _connect_signals(self) -> None:
        """连接信号与槽。"""
        self._add_file_btn.clicked.connect(self._on_add_file)
        self._clear_btn.clicked.connect(self._on_clear)
        self._remove_selected_btn.clicked.connect(self._on_remove_selected)
        self._start_btn.clicked.connect(self._on_start_all)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._output_dir_btn.clicked.connect(self._on_select_output_dir)
        self._category_group.idClicked.connect(self._on_category_changed)

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
                cat_keys = ['video', 'audio', 'image', 'document']
                idx = cat_keys.index(category_key)
                self._populate_format_combo(category_key)
                self._update_start_button()

    def _on_category_changed(self, idx: int) -> None:
        """类别切换时更新格式下拉框。"""
        cat_keys = ['video', 'audio', 'image', 'document']
        if 0 <= idx < len(cat_keys):
            self._populate_format_combo(cat_keys[idx])
            self._update_start_button()

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
        dir_path = QFileDialog.getExistingDirectory(self, '选择输出目录')
        if dir_path:
            self._output_dir = dir_path
            self._output_dir_label.setText(dir_path)
            self._output_dir_label.setStyleSheet('color: #000;')

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
                msg,
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

        # 绞杀所有工作进程
        self._orchestrator.cancel_all()
        event.accept()


def run_app() -> None:
    """启动应用程序（供 main.py 调用）。"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('全能格式转换工具')
    app.setWindowIcon(QIcon(get_resource_path('icon.ico')))

    # 全局样式 — 现代简洁风格
    app.setStyleSheet("""
        /* ===== 全局基础 ===== */
        QMainWindow {
            background-color: #f0f2f5;
        }
        QWidget {
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            font-size: 13px;
        }
        QLabel {
            color: #333;
        }

        /* ===== GroupBox ===== */
        QGroupBox {
            font-weight: bold;
            font-size: 13px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 18px;
            padding-left: 12px;
            padding-right: 12px;
            padding-bottom: 12px;
            background-color: #ffffff;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 2px 10px;
            background-color: #ffffff;
            color: #1a1a2e;
        }

        /* ===== 表格 ===== */
        QTableWidget {
            border: 1px solid #e0e0e0;
            gridline-color: #f0f0f0;
            background-color: #ffffff;
            alternate-background-color: #f8f9fb;
            border-radius: 6px;
            selection-background-color: #e3f2fd;
            selection-color: #1a1a2e;
            outline: none;
        }
        QTableWidget::item {
            padding: 6px 10px;
            border-bottom: 1px solid #f0f0f0;
        }
        QTableWidget::item:selected {
            background-color: #e3f2fd;
            color: #1a1a2e;
        }
        QHeaderView::section {
            background-color: #f5f6f8;
            color: #555;
            padding: 8px 10px;
            border: none;
            border-bottom: 2px solid #e0e0e0;
            font-weight: bold;
            font-size: 12px;
        }
        QHeaderView::section:hover {
            background-color: #eef0f4;
        }

        /* ===== 按钮 ===== */
        QPushButton {
            padding: 7px 18px;
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            background-color: #ffffff;
            color: #333;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #f0f0f0;
            border-color: #bbb;
        }
        QPushButton:pressed {
            background-color: #e0e0e0;
        }
        QPushButton:disabled {
            background-color: #f5f5f5;
            color: #bbb;
            border-color: #e8e8e8;
        }

        /* ===== 下拉框 ===== */
        QComboBox {
            padding: 6px 10px;
            border: 1px solid #d0d0d0;
            border-radius: 6px;
            background-color: #ffffff;
            color: #333;
            font-size: 13px;
            min-height: 20px;
        }
        QComboBox:hover {
            border-color: #0078D4;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 24px;
            border-left: 1px solid #e0e0e0;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }
        QComboBox QAbstractItemView {
            border: 1px solid #d0d0d0;
            border-radius: 4px;
            background-color: #ffffff;
            selection-background-color: #e3f2fd;
            selection-color: #1a1a2e;
            padding: 4px;
        }

        /* ===== 进度条 ===== */
        QProgressBar {
            border: none;
            border-radius: 6px;
            text-align: center;
            height: 22px;
            background-color: #e8e8e8;
            color: #555;
            font-size: 12px;
            font-weight: bold;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0078D4, stop:1 #00a8ff);
            border-radius: 6px;
        }

        /* ===== 状态栏 ===== */
        QStatusBar {
            background-color: #f5f6f8;
            border-top: 1px solid #e0e0e0;
            color: #666;
            font-size: 12px;
            padding: 4px;
        }

        /* ===== 复选框 ===== */
        QCheckBox {
            spacing: 6px;
            color: #555;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #ccc;
            border-radius: 3px;
        }
        QCheckBox::indicator:checked {
            background-color: #0078D4;
            border-color: #0078D4;
        }

        /* ===== 消息框 ===== */
        QMessageBox {
            background-color: #ffffff;
        }
        QMessageBox QLabel {
            color: #333;
            font-size: 13px;
        }
        QMessageBox QPushButton {
            min-width: 80px;
            padding: 6px 20px;
        }

        /* ===== 滚动条 ===== */
        QScrollBar:vertical {
            border: none;
            background: #f5f5f5;
            width: 8px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical {
            background: #ccc;
            border-radius: 4px;
            min-height: 30px;
        }
        QScrollBar::handle:vertical:hover {
            background: #aaa;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
