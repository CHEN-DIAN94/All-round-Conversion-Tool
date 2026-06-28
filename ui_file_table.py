"""
ui_file_table.py — 文件表格管理 Mixin

提供文件拖拽、添加、删除、去重等表格操作。
"""


__all__ = ['FileTableMixin']

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QTableWidgetItem, QProgressBar,
    QFileDialog, QMessageBox,
)

from constants import FileStatus, MAX_FILES_PER_BATCH
from utils import get_file_size_str, map_format_to_category
from formats import (
    COL_FILE_NAME, COL_FILE_SIZE, COL_PROGRESS, COL_STATUS,
    _collect_files_from_paths,
)


class FileTableMixin:
    """文件表格管理 mixin。"""

    def _update_empty_state(self) -> None:
        """根据文件列表是否为空切换空状态/表格。"""
        if self._table.rowCount() == 0:
            self._table_stack.setCurrentIndex(0)
        else:
            self._table_stack.setCurrentIndex(1)

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

    def add_files_to_table(self, file_paths: list[str]) -> None:
        """将文件添加到表格。"""
        if len(file_paths) >= MAX_FILES_PER_BATCH:
            QMessageBox.information(self, '提示', f'最多同时添加 {MAX_FILES_PER_BATCH} 个文件，已截断。')
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

    _CATEGORY_FILTERS = {
        'video': '视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.ts *.3gp *.ogv *.m2ts *.vob)',
        'audio': '音频文件 (*.mp3 *.wav *.flac *.aac *.ogg *.wma *.m4a *.opus *.ac3 *.dts *.ape *.aiff)',
        'image': '图片文件 (*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.tif *.webp *.ico *.svg *.heic *.heif)',
        'document': '文档文件 (*.pdf *.docx *.doc *.txt *.rtf *.html *.htm *.md)',
        'spreadsheet': '表格文件 (*.xlsx *.xls)',
        'tools': '音视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.mp3 *.wav *.flac *.aac *.ogg *.m4a);;所有文件 (*.*)',
    }

    def _on_add_file(self) -> None:
        """点击「添加文件」。"""
        current_cat = 'video'
        for key, btn in self._category_btns.items():
            if btn.isChecked():
                current_cat = key
                break
        if current_cat == 'tools':
            cat_filter = self._tool_panel.get_file_filter()
        else:
            cat_filter = self._CATEGORY_FILTERS.get(current_cat, '')
        filter_str = f'{cat_filter};;所有文件 (*.*)'
        files, _ = QFileDialog.getOpenFileNames(
            self, '选择要转换的文件', '', filter_str,
        )
        if files:
            self.add_files_to_table(files)

    def _on_add_folder(self) -> None:
        """点击「添加文件夹」：递归收集该文件夹下所有受支持的文件。"""
        from formats import _collect_files_from_paths
        start_dir = ''
        if self._table.rowCount() > 0:
            first_item = self._table.item(0, COL_FILE_NAME)
            if first_item:
                fp = first_item.data(Qt.ItemDataRole.UserRole)
                if fp:
                    start_dir = os.path.dirname(fp)

        folder = QFileDialog.getExistingDirectory(
            self, '选择要添加的文件夹', start_dir,
        )
        if not folder:
            return

        # 收集当前类别支持的扩展名
        current_cat = 'video'
        for key, btn in self._category_btns.items():
            if btn.isChecked():
                current_cat = key
                break

        # 工具类别接受所有文件
        if current_cat == 'tools':
            all_files = _collect_files_from_paths([folder])
            self.add_files_to_table(all_files)
            return

        # 其他类别按扩展名过滤
        from utils import map_format_to_category
        all_files = _collect_files_from_paths([folder])
        # 按当前类别过滤
        filtered = []
        for fp in all_files:
            ext = os.path.splitext(fp)[1].lower()
            cat = map_format_to_category(ext)
            if cat == current_cat or (current_cat == 'document' and ext in ('.pdf', '.docx', '.doc')):
                filtered.append(fp)

        if not filtered:
            QMessageBox.information(
                self, '提示',
                f'所选文件夹中没有找到当前类别（{current_cat}）支持的文件。\n'
                f'共扫描 {len(all_files)} 个文件。',
            )
            return

        self.add_files_to_table(filtered)

    def _on_clear(self) -> None:
        """清空列表。"""
        if self._is_converting:
            QMessageBox.warning(self, '警告', '转换进行中，请先取消。')
            return
        self._table.setRowCount(0)
        self._file_paths_set.clear()  # 同步清空去重缓存
        self._preview_panel.clear()  # 清空预览
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
