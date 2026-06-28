"""
ui_settings.py — 设置/主题/布局 Mixin

提供设置持久化、主题切换、路径生成、右键菜单、窗口事件等。
"""


__all__ = ['SettingsMixin']

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

from logging_config import get_logger
from monitor import trace

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QMenu,
    QProgressDialog,
)

from constants import FileStatus
from utils import (
    get_file_size_str,
    map_format_to_category, ensure_output_dir, CREATE_NO_WINDOW,
)
from formats import (
    CATEGORY_KEYS, FORMAT_BY_KEY,
    CONVERSION_MAP,
    COL_FILE_NAME, COL_STATUS, COL_PROGRESS,
    _is_legacy_doc,
)
from widgets import ErrorDetailDialog, AdvancedSettingsPanel, HistoryDialog
from constants import SHUTDOWN_WAIT_MS
from themes import THEMES, DEFAULT_THEME, get_theme_qss

logger = get_logger(__name__)


class SettingsMixin:
    """设置/主题/布局 mixin。"""

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
        self._add_folder_btn.clicked.connect(self._on_add_folder)
        self._clear_btn.clicked.connect(self._on_clear)
        self._remove_selected_btn.clicked.connect(self._on_remove_selected)
        self._start_btn.clicked.connect(self._on_start_all)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._pause_btn.clicked.connect(self._on_pause_resume)
        self._retry_btn.clicked.connect(self._on_retry_failed)
        self._output_dir_btn.clicked.connect(self._on_select_output_dir)
        self._open_dir_btn.clicked.connect(self._on_open_output_dir)
        self._advanced_btn.clicked.connect(self._on_toggle_advanced)
        self._category_group.idClicked.connect(self._on_category_changed)
        self._format_combo.currentIndexChanged.connect(self._update_start_button)
        self._format_combo.currentIndexChanged.connect(self._save_settings)
        self._format_combo.currentIndexChanged.connect(self._update_filename_preview)
        self._overwrite_check.stateChanged.connect(self._save_settings)
        self._post_action_combo.currentIndexChanged.connect(self._save_settings)
        self._table.itemDoubleClicked.connect(self._on_table_double_clicked)
        self._table.currentItemChanged.connect(self._on_table_selection_changed)

        # 键盘快捷键
        QShortcut(QKeySequence('Ctrl+O'), self).activated.connect(self._on_add_file)
        QShortcut(QKeySequence('Ctrl+Shift+O'), self).activated.connect(self._on_add_folder)
        QShortcut(QKeySequence('Delete'), self).activated.connect(self._on_remove_selected)
        QShortcut(QKeySequence('Ctrl+A'), self).activated.connect(self._table.selectAll)
        QShortcut(QKeySequence('Escape'), self).activated.connect(self._on_cancel)
        QShortcut(QKeySequence('Ctrl+Return'), self).activated.connect(self._on_start_all)
        QShortcut(QKeySequence('Ctrl+E'), self).activated.connect(self._on_export_ffmpeg_cmd_shortcut)
        QShortcut(QKeySequence('F5'), self).activated.connect(self._on_refresh_files)

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
        logger.info('切换分类 idx=%s keys=%s', idx, cat_keys)
        if 0 <= idx < len(cat_keys):
            cat = cat_keys[idx]
            is_tools = (cat == 'tools')
            logger.info('分类切换 cat=%s is_tools=%s advanced_checked=%s', cat, is_tools, self._advanced_btn.isChecked() if hasattr(self, '_advanced_btn') else None)
            # 切换格式行/工具面板的可见性
            self._set_format_row_visible(not is_tools)
            self._tool_panel.setVisible(is_tools)
            self._set_dir_row_visible(not is_tools)
            if hasattr(self, '_tmpl_row_widget'):
                self._tmpl_row_widget.setVisible(not is_tools)
            if hasattr(self, '_preset_combo'):
                self._preset_combo.setVisible(not is_tools)
            if hasattr(self, '_advanced_btn'):
                self._advanced_btn.setVisible(not is_tools)
            if hasattr(self, '_advanced_panel'):
                if is_tools:
                    self._advanced_panel.hide()
                    if hasattr(self, '_advanced_btn'):
                        self._advanced_btn.setChecked(False)
            if is_tools and hasattr(self, '_advanced_btn'):
                self._advanced_btn.setChecked(False)
            if not is_tools:
                self._populate_format_combo(cat)
            self._update_start_button()
            self._save_settings()

    def _set_format_row_visible(self, visible: bool) -> None:
        """显示/隐藏格式选择行。"""
        if hasattr(self, '_fmt_row_widget'):
            self._fmt_row_widget.setVisible(visible)

    def _set_dir_row_visible(self, visible: bool) -> None:
        """显示/隐藏输出目录行。"""
        if hasattr(self, '_dir_row_widget'):
            self._dir_row_widget.setVisible(visible)

    def _on_toggle_advanced(self, checked: bool) -> None:
        """打开高级设置弹窗。"""
        logger.info('打开高级设置弹窗 checked=%s', checked)
        if checked:
            self._advanced_panel.show()
            self._advanced_panel.raise_()
            self._advanced_panel.activateWindow()
            self._advanced_btn.setText('⚙ 收起设置')
        else:
            self._advanced_panel.hide()
            self._advanced_btn.setText('⚙ 高级设置')
        logger.info('高级设置弹窗 visible=%s', self._advanced_panel.isVisible())

    def _on_advanced_dialog_closed(self, result) -> None:
        """高级设置弹窗关闭时同步按钮状态。"""
        self._advanced_btn.setChecked(False)
        self._advanced_btn.setText('⚙ 高级设置')

    def _on_theme_changed(self, idx: int) -> None:
        """主题切换。"""
        key = self._theme_combo.currentData()
        if key:
            self._apply_theme(key)
            self._save_settings()

    def _apply_theme(self, theme_key: str) -> None:
        """应用指定主题（含动画）。"""
        trace('theme.apply.enter', theme=theme_key)
        from themes import activate_animation
        qss = get_theme_qss(theme_key)
        if qss:
            QApplication.instance().setStyleSheet(qss)
        self._current_theme = theme_key
        trace('theme.apply.qss_done', theme=theme_key)
        # 激活动画（如有）
        activate_animation(theme_key, self)
        trace('theme.apply.anim_done', theme=theme_key)

    def _on_advanced_settings_changed(self, settings: dict) -> None:
        """高级设置变更回调。"""
        allowed_keys = set(AdvancedSettingsPanel.DEFAULTS)
        self._advanced_settings = {
            key: value for key, value in settings.items()
            if key in allowed_keys
        }
        self._save_settings()
        self._status_bar.showMessage('高级设置已更新', 2000)

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

    def _open_file(self, file_path: str) -> None:
        """用系统默认程序打开文件。"""
        if sys.platform == 'win32':
            os.startfile(file_path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', file_path])
        else:
            subprocess.Popen(['xdg-open', file_path])

    def _reveal_in_explorer(self, file_path: str) -> None:
        """在文件管理器中定位文件。"""
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', '/select,', file_path],
                           creationflags=CREATE_NO_WINDOW)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', file_path])
        else:
            subprocess.Popen(['xdg-open', str(Path(file_path).parent)])

    def _get_output_path_for(self, row: int) -> str:
        """获取指定行的输出文件路径。"""
        fmt_data = self._format_combo.currentData()
        if not fmt_data:
            return ''
        output_ext, _ = fmt_data
        name_item = self._table.item(row, COL_FILE_NAME)
        if not name_item:
            return ''
        input_path = name_item.data(Qt.ItemDataRole.UserRole)
        if not input_path:
            return ''
        return self._generate_output_path(input_path, output_ext)

    def _generate_output_path(self, input_path: str, output_ext: str) -> str:
        """生成输出路径（支持命名模板）。"""
        from datetime import datetime
        input_stem = Path(input_path).stem
        input_ext_no_dot = output_ext.lstrip('.')

        # 获取模板
        template = ''
        if hasattr(self, '_template_input'):
            template = self._template_input.currentText().strip()

        # 默认模板
        if not template or '{' not in template:
            template = '{原名}.{ext}'

        # 替换变量
        now = datetime.now()
        file_name = template.replace('{原名}', input_stem)
        file_name = file_name.replace('{日期}', now.strftime('%Y%m%d'))
        file_name = file_name.replace('{序号}', f'{self._file_counter:03d}')
        file_name = file_name.replace('{格式}', input_ext_no_dot)
        file_name = file_name.replace('{ext}', input_ext_no_dot)

        self._file_counter += 1

        if self._output_dir:
            output_path = os.path.join(self._output_dir, file_name)
        else:
            output_path = str(Path(input_path).parent / file_name)

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
        # 判断当前是否在工具模式
        is_tools = False
        for key, btn in self._category_btns.items():
            if btn.isChecked() and key == 'tools':
                is_tools = True
                break
        if is_tools:
            has_format = True  # 工具模式不需要格式选择
            self._start_btn.setText('▶  执行工具')
        else:
            has_format = self._format_combo.currentData() is not None
            self._start_btn.setText('▶  全部开始')
        self._start_btn.setEnabled(has_files and has_format and not self._is_converting)

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

            # 恢复转换后操作
            if hasattr(self, '_post_action_combo'):
                saved_post = self._settings.value('post_action', 'none', type=str)
                for i in range(self._post_action_combo.count()):
                    if self._post_action_combo.itemData(i) == saved_post:
                        self._post_action_combo.setCurrentIndex(i)
                        break

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
                # 类型安全读取：指定 type 避免重启后返回字符串
                if isinstance(default, int):
                    val = self._settings.value(key, default, type=int)
                elif isinstance(default, float):
                    val = self._settings.value(key, default, type=float)
                else:
                    val = self._settings.value(key, default, type=str)
                self._advanced_settings[key] = val
            self._settings.endGroup()
            self._advanced_panel.set_settings(self._advanced_settings)

            # 加载主题
            saved_theme = self._settings.value('theme', DEFAULT_THEME, type=str)
            if saved_theme not in THEMES:
                saved_theme = DEFAULT_THEME
            self._current_theme = saved_theme
            # 设置下拉框选中项（不触发信号）
            self._theme_combo.blockSignals(True)
            for i in range(self._theme_combo.count()):
                if self._theme_combo.itemData(i) == saved_theme:
                    self._theme_combo.setCurrentIndex(i)
                    break
            self._theme_combo.blockSignals(False)
            # 应用主题
            self._apply_theme(saved_theme)

            # 加载命名模板
            saved_template = self._settings.value('naming_template', '{原名}.{ext}', type=str)
            if hasattr(self, '_template_input') and saved_template:
                self._template_input.setCurrentText(saved_template)

        finally:
            self._loading_settings = False

        # 初始化预设管理器
        from presets import PresetManager
        self._preset_manager = PresetManager()
        self._preset_combo.set_manager(self._preset_manager)

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

        # 保存主题
        if hasattr(self, '_current_theme'):
            self._settings.setValue('theme', self._current_theme)

        # 保存命名模板
        if hasattr(self, '_template_input'):
            self._settings.setValue('naming_template', self._template_input.currentText())

        # 保存转换后操作
        if hasattr(self, '_post_action_combo'):
            self._settings.setValue('post_action', self._post_action_combo.currentData() or 'none')

        self._settings.sync()

    def _update_filename_preview(self, *args) -> None:
        """实时更新输出文件名预览。"""
        if not hasattr(self, '_filename_preview_label'):
            return
        template = self._template_input.currentText().strip() if hasattr(self, '_template_input') else ''
        if not template or '{' not in template:
            template = '{原名}.{ext}'

        # 取当前选中文件作为样例，没有则用「示例文件」
        sample_name = '示例文件'
        if self._table.rowCount() > 0:
            item = self._table.item(0, COL_FILE_NAME)
            if item:
                fp = item.data(Qt.ItemDataRole.UserRole)
                if fp:
                    sample_name = Path(fp).stem

        # 取当前选中的输出扩展名
        sample_ext = 'mp4'
        if hasattr(self, '_format_combo'):
            fmt_data = self._format_combo.currentData()
            if fmt_data:
                sample_ext = fmt_data[0].lstrip('.')

        from datetime import datetime
        now = datetime.now()
        preview = template.replace('{原名}', sample_name)
        preview = preview.replace('{日期}', now.strftime('%Y%m%d'))
        preview = preview.replace('{序号}', '001')
        preview = preview.replace('{格式}', sample_ext)
        preview = preview.replace('{ext}', sample_ext)

        self._filename_preview_label.setText(f'预览: {preview}')

    def _on_table_selection_changed(self, current, previous) -> None:
        """表格选中行变化时更新预览。"""
        if current is None:
            self._preview_panel.clear()
            return
        row = current.row()
        if row < 0:
            return
        name_item = self._table.item(row, COL_FILE_NAME)
        if name_item:
            file_path = name_item.data(Qt.ItemDataRole.UserRole)
            if file_path:
                self._preview_panel.preview_file(file_path)

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
        name_item = self._table.item(row, COL_FILE_NAME)
        file_path = name_item.data(Qt.ItemDataRole.UserRole) if name_item else ''

        if self._is_converting and status_text == FileStatus.CONVERTING:
            cancel_action = menu.addAction('取消此文件')
            cancel_action.triggered.connect(lambda checked, r=row: self._cancel_single(r))
        elif status_text == FileStatus.FAILED:
            detail_action = menu.addAction('查看详情')
            detail_action.triggered.connect(
                lambda: self._on_table_double_clicked(
                    self._table.item(row, COL_FILE_NAME))
            )

        # 文件操作（非转换中）
        if not self._is_converting and file_path:
            if os.path.isfile(file_path):
                open_action = menu.addAction('打开文件')
                open_action.triggered.connect(lambda: self._open_file(file_path))

                reveal_action = menu.addAction('打开所在文件夹')
                reveal_action.triggered.connect(lambda: self._reveal_in_explorer(file_path))

            if status_text == FileStatus.SUCCESS:
                output_path = self._get_output_path_for(row)
                if output_path and os.path.isfile(output_path):
                    open_output = menu.addAction('打开输出文件')
                    open_output.triggered.connect(lambda: self._open_file(output_path))

        # 导出失败报告（有失败文件时显示）
        has_failures = self._has_failed_files()
        if has_failures:
            menu.addSeparator()
            export_action = menu.addAction('导出失败报告')
            export_action.triggered.connect(self._export_failure_report)

        if not menu.isEmpty():
            menu.exec(self._table.viewport().mapToGlobal(pos))

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭事件（优雅退出三步协议）。"""
        trace('closeEvent.enter', converting=self._is_converting)
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

        # 停止主题动画
        from themes import stop_current_animation
        stop_current_animation()
        trace('closeEvent.anim_stopped')

        # 优雅退出三步协议
        if self._orchestrator and self._orchestrator.workers:
            self._orchestrator.cancel_all()
            self._orchestrator.wait_all(timeout_ms=3000)
            trace('closeEvent.threads_joined')

        event.accept()
        trace('closeEvent.exit')

    def _on_preset_applied(self, params: dict) -> None:
        """预设应用回调。"""
        # 保存请求：把当前高级设置存为新预设
        if '__save_request__' in params:
            name = params['__save_request__']
            current = self._advanced_settings.copy()
            current['description'] = f'用户自定义预设'
            self._preset_manager.add_preset(name, current)
            self._preset_manager.save()
            self._preset_combo.set_manager(self._preset_manager)
            self._status_bar.showMessage(f'预设已保存: {name}', 3000)
            return

        allowed_keys = set(AdvancedSettingsPanel.DEFAULTS)
        filtered = {
            key: value for key, value in params.items()
            if key in allowed_keys
        }

        # 应用预设参数到高级设置面板
        self._advanced_settings.update(filtered)
        self._advanced_panel.set_settings(self._advanced_settings)
        self._save_settings()
        self._status_bar.showMessage('预设已应用', 2000)

    def _on_show_history(self) -> None:
        """显示转换历史对话框。"""
        trace('history.show.enter')
        try:
            dialog = HistoryDialog(self)
            trace('history.dialog_created')
            dialog.setModal(False)
            dialog.show()
            trace('history.dialog_shown')
            dialog.raise_()
            dialog.activateWindow()
            if not hasattr(self, '_history_dialogs'):
                self._history_dialogs = []
            self._history_dialogs.append(dialog)
            trace('history.dialog_stored', total=len(self._history_dialogs))
        except Exception as e:
            import traceback as _tb
            from monitor import monitor_log
            monitor_log(f'!!! _on_show_history crashed !!!\n{_tb.format_exc()}')
            trace('history.crash', error=repr(e))
