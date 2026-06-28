"""
ui_conversion.py — 转换控制 Mixin

提供转换启动、取消、进度更新、工具执行等操作。
"""


__all__ = ['ConversionMixin']

import os
import time
from pathlib import Path

from logging_config import get_logger

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QProgressBar, QFileDialog, QMessageBox

from workers import ConversionWorker, BatchOrchestrator
from constants import FileStatus
from formats import COL_FILE_NAME, COL_STATUS, COL_PROGRESS
from utils import CREATE_NO_WINDOW
from monitor import trace

logger = get_logger(__name__)


class ConversionMixin:
    """转换控制 mixin。"""

    _cancel_in_progress: bool = False  # [STRESS-02 修复] 取消中标志
    _active_batch_id: int = 0

    def _on_start_all(self, retry_rows: list = None) -> None:
        """全部开始转换。retry_rows 指定时只重试指定行。"""
        if isinstance(retry_rows, bool):
            retry_rows = None

        row_count = self._table.rowCount()
        if row_count == 0:
            return
        trace('start_all.enter', rows=row_count, retry=bool(retry_rows))

        try:
            self._do_start_all(retry_rows, row_count)
        except Exception as e:
            import traceback as _tb
            from monitor import monitor_log
            monitor_log(f'!!! _on_start_all crashed !!!\n{_tb.format_exc()}')
            trace('start_all.crash', error=repr(e))
            # 恢复 UI 状态
            try:
                self._is_converting = False
                self._set_controls_enabled(True)
                self._status_bar.showMessage(f'启动转换时出错: {e}', 5000)
            except Exception:
                pass

    def _do_start_all(self, retry_rows: list = None, row_count: int = 0) -> None:
        """实际执行转换启动逻辑。"""

        # 判断是否在工具模式
        is_tools = False
        for key, btn in self._category_btns.items():
            if btn.isChecked() and key == 'tools':
                is_tools = True
                break

        if is_tools:
            trace('start_all.tools_mode')
            self._run_tool(retry_rows)
            return

        # FFmpeg 可用性检查（视频/音频类别必需）
        fmt_data_preview = self._format_combo.currentData()
        need_ffmpeg = True
        if fmt_data_preview:
            _, category_key = fmt_data_preview
            # 文档/表格类别不需要 ffmpeg
            need_ffmpeg = category_key not in ('document', 'spreadsheet')
        if need_ffmpeg and not getattr(self, '_ffmpeg_available', True):
            QMessageBox.critical(
                self, 'FFmpeg 不可用',
                '未检测到 FFmpeg，视频/音频/图片转换无法进行。\n\n'
                '请将 ffmpeg.exe 放入程序目录的 bin/ 文件夹，\n'
                '或将其加入系统 PATH 后重启程序。',
            )
            return

        # 校验文件存在性
        missing = []
        valid_files: set[str] = set()
        check_rows = retry_rows if retry_rows is not None else range(row_count)
        for row in check_rows:
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
                + ('...' if len(missing) > 10 else ''),
            )
            return

        trace('start_all.check_files_done', valid=len(valid_files))

        fmt_data = self._format_combo.currentData()
        if not fmt_data:
            QMessageBox.warning(self, '提示', '请先选择输出格式。')
            return
        output_ext, category_key = fmt_data
        trace('start_all.fmt', ext=output_ext, cat=category_key)

        # 重置状态（仅处理目标行）
        for row in check_rows:
            status_item = self._table.item(row, COL_STATUS)
            if status_item:
                status_item.setText(FileStatus.WAITING)
            progress_bar = self._table.cellWidget(row, COL_PROGRESS)
            if isinstance(progress_bar, QProgressBar):
                progress_bar.setValue(0)

        # 重置命名模板序号
        self._file_counter = 1

        # 创建 worker
        workers = []
        for row in check_rows:
            name_item = self._table.item(row, COL_FILE_NAME)
            status_item = self._table.item(row, COL_STATUS)
            if not name_item:
                continue
            input_path = name_item.data(Qt.ItemDataRole.UserRole)
            if not input_path or input_path not in valid_files:
                if status_item:
                    status_item.setText(FileStatus.FAILED)
                continue

            try:
                trace('start_all.gen_path', row=row, input=input_path)
                output_path = self._generate_output_path(input_path, output_ext)
                trace('start_all.gen_path_done', row=row, output=output_path)
                conv_type = self._determine_conv_type(input_path, output_ext)
                trace('start_all.conv_type', row=row, conv=conv_type)
            except Exception as e:
                trace('start_all.gen_path_err', row=row, error=repr(e))
                if status_item:
                    status_item.setText(FileStatus.FAILED)
                    status_item.setToolTip(str(e))
                continue

            if conv_type is None:
                if status_item:
                    status_item.setText(FileStatus.FAILED)
                input_ext = Path(input_path).suffix.lower()
                if input_ext == '.doc' and output_ext == '.pdf':
                    tip = '旧版 .doc 格式不支持直接转换，请先用 Word 另存为 .docx'
                else:
                    tip = f'不支持的转换: {Path(input_path).suffix} -> {output_ext}'
                name_item.setToolTip(tip)
                continue

            trace('start_all.create_worker', row=row, conv=conv_type)
            worker = ConversionWorker(
                row, input_path, output_path, conv_type,
                settings=self._advanced_settings,
            )
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)
            trace('start_all.worker_created', row=row)

        if not workers:
            trace('start_all.no_workers')
            return

        # 磁盘空间检查：输出目录剩余空间 < 100MB 时警告
        from utils import get_disk_free
        sample_output = workers[0].output_path
        free_bytes = get_disk_free(sample_output)
        if free_bytes >= 0 and free_bytes < 100 * 1024 * 1024:
            free_mb = free_bytes / (1024 * 1024)
            QMessageBox.warning(
                self, '磁盘空间不足',
                f'输出目录所在磁盘剩余空间仅 {free_mb:.1f} MB，\n'
                f'可能导致转换失败。建议先清理磁盘空间。',
            )

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        if category_key in ('document', 'spreadsheet'):
            from PyQt6.QtCore import QSemaphore
            self._orchestrator = BatchOrchestrator(max_concurrency=1)
        else:
            self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)
        trace('start_all.orch_ready', workers=len(workers), batch=current_batch_id)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在转换 {len(workers)} 个文件...')

        trace('start_all.orch_start')
        self._orchestrator.start_all()
        trace('start_all.orch_started')

    def _run_tool(self, retry_rows: list = None) -> None:
        """执行工具模式。"""
        tool_key = self._tool_panel.get_tool_key()
        tool_params = self._tool_panel.get_tool_params()
        row_count = self._table.rowCount()

        if row_count == 0:
            return

        # 收集文件路径
        file_paths = []
        check_rows = retry_rows if retry_rows is not None else range(row_count)
        for row in check_rows:
            item = self._table.item(row, COL_FILE_NAME)
            if item:
                fp = item.data(Qt.ItemDataRole.UserRole)
                if fp and os.path.isfile(fp):
                    file_paths.append(fp)

        if not file_paths:
            QMessageBox.warning(self, '提示', '没有有效的文件。')
            return

        try:
            if tool_key == 'export_cmd':
                self._tool_export_cmd(file_paths)
            elif tool_key == 'embed_subtitle':
                self._tool_embed_subtitle(file_paths, tool_params)
            elif tool_key == 'extract_subtitle':
                self._tool_extract_subtitle(file_paths)
            elif tool_key == 'extract_audio':
                self._tool_extract_audio(file_paths, tool_params)
            elif tool_key == 'merge_media':
                self._tool_merge_media(file_paths)
            elif tool_key == 'crop_video':
                self._tool_crop_video(file_paths, tool_params)
            elif tool_key == 'trim_media':
                self._tool_trim_media(file_paths, tool_params)
            elif tool_key == 'compress_video':
                self._tool_compress_video(file_paths, tool_params)
            elif tool_key == 'video_to_gif':
                self._tool_video_to_gif(file_paths, tool_params)
            elif tool_key == 'media_info':
                self._tool_media_info(file_paths)
            elif tool_key == 'compress_image':
                self._tool_compress_image(file_paths, tool_params)
            elif tool_key == 'resize_image':
                self._tool_resize_image(file_paths, tool_params)
            elif tool_key == 'add_watermark':
                self._tool_add_watermark(file_paths, tool_params)
            elif tool_key == 'merge_pdfs':
                self._tool_merge_pdfs(file_paths)
            elif tool_key == 'split_pdf':
                self._tool_split_pdf(file_paths, tool_params)
            elif tool_key == 'pdf_to_images':
                self._tool_pdf_to_images(file_paths, tool_params)
            elif tool_key == 'images_to_pdf':
                self._tool_images_to_pdf(file_paths, tool_params)
            else:
                QMessageBox.warning(self, '提示', f'未知工具: {tool_key}')
        except Exception as e:
            QMessageBox.critical(self, '工具执行失败', str(e))

    def _tool_export_cmd(self, file_paths: list) -> None:
        """导出 FFmpeg 命令。"""
        from engines.ffmpeg_utils import export_ffmpeg_cmd
        cmds = []
        for fp in file_paths:
            out = str(Path(fp).with_suffix('.out' + Path(fp).suffix))
            cmd = export_ffmpeg_cmd(fp, out, params=self._advanced_settings)
            cmds.append(cmd)
        text = '\n\n'.join(cmds)
        QApplication.clipboard().setText(text)
        QMessageBox.information(
            self, '导出成功',
            f'已生成 {len(cmds)} 条 FFmpeg 命令并复制到剪贴板。'
        )

    def _tool_embed_subtitle(self, file_paths: list, params: dict) -> None:
        """嵌入字幕。"""
        sub_path = params.get('subtitle_path', '')
        if not sub_path or not os.path.isfile(sub_path):
            QMessageBox.warning(self, '提示', '请先选择字幕文件。')
            return
        language = params.get('language', 'chi')

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            out = self._generate_output_path(fp, Path(fp).suffix)
            worker = ConversionWorker(i, fp, out, 'embed_subtitle',
                                      settings={'subtitle_path': sub_path, 'language': language})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator(max_concurrency=1)
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在嵌入字幕 {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_extract_subtitle(self, file_paths: list) -> None:
        """提取字幕（异步执行，避免批量时 UI 冻结）。"""
        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            out = str(Path(fp).with_suffix('.srt'))
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'extract_subtitle')
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator(max_concurrency=1)
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在提取字幕 {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_merge_media(self, file_paths: list) -> None:
        """合并音视频。"""
        from engines.ffmpeg_utils import merge_media
        if len(file_paths) < 2:
            QMessageBox.warning(self, '提示', '合并至少需要 2 个文件。')
            return

        # 输出路径：第一个文件名 + _merged
        first = file_paths[0]
        out = str(Path(first).with_stem(Path(first).stem + '_merged'))
        if self._output_dir:
            out = os.path.join(self._output_dir, Path(out).name)
        if not self._overwrite_check.isChecked():
            out = self._avoid_overwrite(out)

        self._is_converting = True
        self._set_controls_enabled(False)
        self._status_bar.showMessage('正在合并文件...')

        # 用单个 worker 执行合并
        worker = ConversionWorker(0, first, out, 'merge_media',
                                  settings={'merge_paths': file_paths})
        worker.status_updated.connect(self._on_status_updated)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.finished_one.connect(self._on_task_finished)
        self._workers = [worker]
        self._total_workers = 1
        self._active_batch_id += 1
        worker._batch_id = self._active_batch_id
        self._completed_count = 0
        self._orchestrator = BatchOrchestrator(max_concurrency=1)
        self._orchestrator.add_worker(worker)
        self._progress_bar.setMaximum(1)
        self._progress_bar.setValue(0)
        self._progress_label.setText('0 / 1')
        self._orchestrator.start_all()

    def _tool_crop_video(self, file_paths: list, params: dict) -> None:
        """画面裁剪。"""
        w = params.get('width', 1920)
        h = params.get('height', 1080)
        x = params.get('x', 0)
        y = params.get('y', 0)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            out = self._generate_output_path(fp, Path(fp).suffix)
            worker = ConversionWorker(i, fp, out, 'crop_video',
                                      settings={'crop_w': w, 'crop_h': h, 'crop_x': x, 'crop_y': y})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for wk in workers:
            wk._batch_id = current_batch_id
            self._orchestrator.add_worker(wk)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在裁剪 {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_extract_audio(self, file_paths: list, params: dict) -> None:
        """从视频提取音频。"""
        fmt = params.get('format', 'mp3')

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            out = str(Path(fp).with_suffix(f'.{fmt}'))
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'extract_audio',
                                      settings={'format': fmt})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在提取音频 {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_trim_media(self, file_paths: list, params: dict) -> None:
        """截取音视频片段。"""
        start_time = params.get('start_time', '00:00:00')
        end_time = params.get('end_time', '00:01:00')

        if not start_time or not end_time:
            QMessageBox.warning(self, '提示', '请填写起始和结束时间。')
            return

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            stem = Path(fp).stem
            suffix = Path(fp).suffix
            out = str(Path(fp).parent / f'{stem}_trimmed{suffix}')
            if self._output_dir:
                out = os.path.join(self._output_dir, Path(out).name)
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'trim_media',
                                      settings={'start_time': start_time, 'end_time': end_time})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在截取 {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_compress_video(self, file_paths: list, params: dict) -> None:
        """视频压缩。"""
        crf = params.get('crf', 28)
        scale_width = params.get('scale_width', 0)
        target_size_mb = params.get('target_size_mb', 0)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            stem = Path(fp).stem
            suffix = Path(fp).suffix
            out = str(Path(fp).parent / f'{stem}_compressed{suffix}')
            if self._output_dir:
                out = os.path.join(self._output_dir, Path(out).name)
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'compress_video',
                                      settings={'crf': crf, 'scale_width': scale_width, 'target_size_mb': target_size_mb})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在压缩 {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_video_to_gif(self, file_paths: list, params: dict) -> None:
        """视频转 GIF。"""
        fps = params.get('fps', 12)
        width = params.get('width', 480)
        colors = params.get('colors', 256)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)

        workers = []
        for i, fp in enumerate(file_paths):
            out = str(Path(fp).with_suffix('.gif'))
            if self._output_dir:
                out = os.path.join(self._output_dir, Path(out).name)
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'video_to_gif',
                                      settings={'fps': fps, 'width': width, 'colors': colors})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator(max_concurrency=1)
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在转换 GIF {len(workers)} 个文件...')
        self._orchestrator.start_all()

    def _tool_media_info(self, file_paths: list) -> None:
        """查看媒体信息（弹窗显示，不生成文件）。"""
        from engines import get_media_info
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout

        results = []
        for fp in file_paths:
            info = get_media_info(fp)
            info['_path'] = fp
            info['_name'] = os.path.basename(fp)
            results.append(info)

        # 弹窗显示
        dialog = QDialog(self)
        dialog.setWindowTitle('媒体信息')
        dialog.setMinimumSize(600, 450)
        dlg_layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        from PyQt6.QtGui import QFont
        text_edit.setFont(QFont('Consolas', 10))

        lines = []
        for info in results:
            lines.append(f'═══ {info["_name"]} ═══')
            lines.append(f'路径: {info["_path"]}')
            size_mb = info.get('file_size', 0) / (1024 * 1024)
            lines.append(f'文件大小: {size_mb:.2f} MB')
            dur = info.get('duration', 0)
            if dur > 0:
                mins, secs = divmod(int(dur), 60)
                lines.append(f'时长: {mins}分{secs:02d}秒 ({dur:.2f}s)')
            if info.get('format_name'):
                lines.append(f'容器格式: {info["format_name"]}')
            if info.get('video_codec'):
                lines.append(f'视频编码: {info["video_codec"]}')
            if info.get('width') and info.get('height'):
                lines.append(f'分辨率: {info["width"]}×{info["height"]}')
            if info.get('frame_rate'):
                lines.append(f'帧率: {info["frame_rate"]} fps')
            if info.get('video_bitrate'):
                vbr = info['video_bitrate'] / 1000
                lines.append(f'视频码率: {vbr:.0f} kbps')
            if info.get('audio_codec'):
                lines.append(f'音频编码: {info["audio_codec"]}')
            if info.get('audio_bitrate'):
                abr = info['audio_bitrate'] / 1000
                lines.append(f'音频码率: {abr:.0f} kbps')
            if info.get('sample_rate'):
                lines.append(f'采样率: {info["sample_rate"]} Hz')
            lines.append('')

        text_edit.setPlainText('\n'.join(lines))
        dlg_layout.addWidget(text_edit)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton('复制')
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(text_edit.toPlainText()))
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_close = QPushButton('关闭')
        btn_close.clicked.connect(dialog.close)
        btn_row.addWidget(btn_close)
        dlg_layout.addLayout(btn_row)

        dialog.exec()

    def _tool_compress_image(self, file_paths: list, params: dict) -> None:
        """图片压缩。"""
        quality = params.get('quality', 80)
        target_size_kb = params.get('target_size_kb', 0)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)
        self._status_bar.showMessage(f'正在压缩 {len(file_paths)} 张图片...')

        # 图片压缩是 CPU 密集但很快，用 worker 异步执行保持 UI 响应
        workers = []
        for i, fp in enumerate(file_paths):
            out = str(Path(fp).with_stem(Path(fp).stem + '_compressed'))
            if self._output_dir:
                out = os.path.join(self._output_dir, Path(out).name)
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'compress_image',
                                      settings={'quality': quality, 'target_size_kb': target_size_kb})
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._orchestrator.start_all()

    def _tool_resize_image(self, file_paths: list, params: dict) -> None:
        """图片缩放。"""
        workers = []
        for i, fp in enumerate(file_paths):
            out = str(Path(fp).with_stem(Path(fp).stem + '_resized'))
            if self._output_dir:
                out = os.path.join(self._output_dir, Path(out).name)
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'resize_image', settings=params)
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)
        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在缩放 {len(workers)} 张图片...')
        self._orchestrator.start_all()

    def _tool_add_watermark(self, file_paths: list, params: dict) -> None:
        """添加水印。"""
        workers = []
        for i, fp in enumerate(file_paths):
            out = str(Path(fp).with_stem(Path(fp).stem + '_watermark'))
            if self._output_dir:
                out = os.path.join(self._output_dir, Path(out).name)
            if not self._overwrite_check.isChecked():
                out = self._avoid_overwrite(out)
            worker = ConversionWorker(i, fp, out, 'add_watermark', settings=params)
            worker.status_updated.connect(self._on_status_updated)
            worker.progress_updated.connect(self._on_progress_updated)
            worker.finished_one.connect(self._on_task_finished)
            workers.append(worker)

        self._is_converting = True
        self._start_time = time.monotonic()
        self._completed_count = 0
        self._set_controls_enabled(False)
        self._workers = workers
        self._total_workers = len(workers)
        self._active_batch_id += 1
        current_batch_id = self._active_batch_id
        self._orchestrator = BatchOrchestrator()
        for w in workers:
            w._batch_id = current_batch_id
            self._orchestrator.add_worker(w)

        self._progress_bar.setMaximum(len(workers))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f'0 / {len(workers)}')
        self._status_bar.showMessage(f'正在添加水印 {len(workers)} 张图片...')
        self._orchestrator.start_all()

    def _tool_merge_pdfs(self, file_paths: list) -> None:
        """合并 PDF。"""
        from engines import merge_pdfs

        if len(file_paths) < 2:
            QMessageBox.warning(self, '提示', '合并至少需要 2 个 PDF 文件。')
            return

        first = file_paths[0]
        out = str(Path(first).with_stem(Path(first).stem + '_merged'))
        if self._output_dir:
            out = os.path.join(self._output_dir, Path(out).name)
        if not self._overwrite_check.isChecked():
            out = self._avoid_overwrite(out)

        try:
            result = merge_pdfs(file_paths, out)
            self._status_bar.showMessage(f'PDF 合并完成: {os.path.basename(result)}')
            QMessageBox.information(self, '合并完成', f'已合并 {len(file_paths)} 个 PDF。\n输出: {result}')
        except Exception as e:
            QMessageBox.critical(self, '合并失败', str(e))

    def _tool_split_pdf(self, file_paths: list, params: dict) -> None:
        """拆分 PDF。"""
        from engines import split_pdf

        pages_per_file = params.get('pages_per_file', 1)
        results = []

        for fp in file_paths:
            out_dir = self._output_dir or str(Path(fp).parent)
            out_sub = os.path.join(out_dir, Path(fp).stem + '_split')
            try:
                parts = split_pdf(fp, out_sub, pages_per_file=pages_per_file)
                results.extend(parts)
            except Exception as e:
                QMessageBox.critical(self, '拆分失败', f'{Path(fp).name}: {e}')
                return

        self._status_bar.showMessage(f'PDF 拆分完成，共生成 {len(results)} 个文件')
        QMessageBox.information(self, '拆分完成',
                                f'已将 {len(file_paths)} 个 PDF 拆分为 {len(results)} 个文件。')

    def _tool_pdf_to_images(self, file_paths: list, params: dict) -> None:
        """PDF 转图片。"""
        from engines import pdf_to_images

        fmt = params.get('fmt', 'png')
        dpi = params.get('dpi', 200)
        results = []

        for fp in file_paths:
            out_dir = self._output_dir or str(Path(fp).parent)
            try:
                images = pdf_to_images(fp, out_dir, fmt=fmt, dpi=dpi)
                results.extend(images)
            except Exception as e:
                QMessageBox.critical(self, '转换失败', f'{Path(fp).name}: {e}')
                return

        self._status_bar.showMessage(f'PDF 转图片完成，共生成 {len(results)} 张')
        QMessageBox.information(self, '转换完成',
                                f'已将 {len(file_paths)} 个 PDF 转为 {len(results)} 张图片。')

    def _tool_images_to_pdf(self, file_paths: list, params: dict) -> None:
        """图片合并为 PDF。"""
        from engines import images_to_pdf

        page_size = params.get('page_size', 'auto')
        first = file_paths[0]
        out = str(Path(first).with_suffix('.pdf'))
        if self._output_dir:
            out = os.path.join(self._output_dir, Path(out).name)
        if not self._overwrite_check.isChecked():
            out = self._avoid_overwrite(out)

        try:
            result = images_to_pdf(file_paths, out, page_size=page_size)
            self._status_bar.showMessage(f'图片转 PDF 完成: {os.path.basename(result)}')
            QMessageBox.information(self, '转换完成',
                                    f'已将 {len(file_paths)} 张图片合并为 PDF。\n输出: {result}')
        except Exception as e:
            QMessageBox.critical(self, '转换失败', str(e))

    def _on_export_ffmpeg_cmd_shortcut(self) -> None:
        """导出 FFmpeg 命令（Ctrl+E）。"""
        # 复用工具面板的导出功能
        file_paths = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_FILE_NAME)
            if item:
                fp = item.data(Qt.ItemDataRole.UserRole)
                if fp:
                    file_paths.append(fp)
        if file_paths:
            self._tool_export_cmd(file_paths)

    def _on_refresh_files(self) -> None:
        """刷新文件状态（F5）：检查文件是否仍存在。"""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                fp = item.data(Qt.ItemDataRole.UserRole)
                if fp and not os.path.isfile(fp):
                    status_item = self._table.item(row, 3)
                    if status_item:
                        status_item.setText('⚠ 文件丢失')
                        status_item.setToolTip(f'文件不存在: {fp}')
        self._status_bar.showMessage('文件状态已刷新')

    def _on_pause_resume(self) -> None:
        """暂停/恢复队列。"""
        if not self._orchestrator:
            return
        if self._orchestrator.is_paused:
            self._orchestrator.resume_all()
            self._pause_btn.setText('⏸ 暂停')
            self._status_bar.showMessage('队列已恢复')
        else:
            self._orchestrator.pause_all()
            self._pause_btn.setText('▶ 恢复')
            self._status_bar.showMessage('队列已暂停（当前任务继续完成，新任务等待中）')

    def _on_cancel(self) -> None:
        """取消所有转换。避免在 UI 线程同步阻塞等待。"""
        if not self._orchestrator:
            return
        trace('cancel.enter', workers=len(self._workers))
        self._cancel_in_progress = True
        self._status_bar.showMessage('正在取消...')
        self._set_controls_enabled(False)
        self._progress_bar.setMaximum(0)
        self._orchestrator.cancel_all()
        for worker in self._workers:
            if not worker.isRunning():
                status_item = self._table.item(worker.file_index, COL_STATUS)
                if status_item and status_item.text() == FileStatus.WAITING:
                    status_item.setText(FileStatus.CANCELLED)
                    self._completed_count += 1

        if self._completed_count >= self._total_workers:
            self._cancel_in_progress = False
            self._is_converting = False
            self._set_controls_enabled(True)
            self._progress_bar.setMaximum(100)
            self._progress_bar.setValue(0)
            self._status_bar.showMessage('已取消所有转换')
            if self._orchestrator:
                self._orchestrator.clear_all()
            self._workers = []
            self._update_start_button()

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
        trace('task_finished.enter', row=file_index, success=success, msg=message[:80])
        matching_worker = None
        for worker in self._workers:
            if worker.file_index == file_index:
                matching_worker = worker
                break

        # 找不到对应 worker 时，说明是过期信号，直接忽略
        if matching_worker is None:
            trace('task_finished.stale', row=file_index, reason='no_matching_worker')
            return

        worker_batch_id = getattr(matching_worker, '_batch_id', 0)
        if worker_batch_id != self._active_batch_id:
            return

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

        # 记录转换历史
        try:
            from history import HistoryManager
            hm = HistoryManager()
            input_path = ''
            output_path = ''
            if 0 <= file_index < self._table.rowCount():
                ni = self._table.item(file_index, COL_FILE_NAME)
                if ni:
                    input_path = ni.data(Qt.ItemDataRole.UserRole) or ''
            # 从 worker 获取输出路径、FFmpeg 命令、耗时
            ffmpeg_cmd = ''
            duration_ms = 0
            for w in self._workers:
                if w.file_index == file_index:
                    output_path = w.output_path
                    ffmpeg_cmd = getattr(w, '_last_cmd', '')
                    duration_ms = getattr(w, 'duration_ms', 0)
                    break
            hm.add(
                input_path=input_path,
                output_path=output_path,
                conv_type=getattr(self, '_current_tool_type', 'convert'),
                success=success,
                error='' if success else message,
                ffmpeg_cmd=ffmpeg_cmd,
                duration_ms=duration_ms,
            )
        except Exception:
            pass  # 历史记录失败不影响主流程

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

        if self._cancel_in_progress and completed >= total:
            self._cancel_in_progress = False
            self._is_converting = False
            self._set_controls_enabled(True)
            self._progress_bar.setMaximum(100)
            self._progress_bar.setValue(0)
            self._status_bar.showMessage('已取消所有转换')
            if self._orchestrator:
                self._orchestrator.clear_all()
            self._workers = []
            self._update_start_button()
            return

        # 全部完成检查（以计数器为准，消除竞态）
        if self._is_converting and completed >= total:
            self._on_all_finished()

    def _on_all_finished(self) -> None:
        """所有任务完成。"""
        if not self._is_converting:
            return  # 防止重复调用
        self._is_converting = False
        trace('all_finished.enter')
        # [STRESS-02 修复] 确保所有线程已退出后再清理
        if self._orchestrator:
            self._orchestrator.wait_all(timeout_ms=5000)
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
            self._retry_btn.setVisible(True)
            self._retry_btn.setText(f'↻ 重试失败 ({failed})')
            QMessageBox.information(
                self, '转换完成',
                msg + '\n\n双击失败的文件行可查看具体错误原因。',
            )

        finished_workers = list(self._workers)
        self._workers = []
        if self._orchestrator:
            self._orchestrator.clear_all()
        self._update_start_button()

        # [P0-1.4] Toast 通知 + 打开输出目录
        if success > 0:
            self._show_completion_toast(success, failed, cancelled, elapsed, finished_workers)

        # 转换完成后操作（用户选择）
        self._perform_post_action(success, failed, finished_workers)

    def _perform_post_action(self, success: int, failed: int, finished_workers: list) -> None:
        """执行用户选择的转换完成后操作。"""
        if not hasattr(self, '_post_action_combo'):
            return
        action = self._post_action_combo.currentData()
        if not action or action == 'none':
            return

        # 至少有一个成功才执行（避免失败后还执行关机）
        if success == 0:
            return

        if action == 'open_dir':
            # 打开输出目录
            self._on_open_output_dir()

        elif action == 'delete_src':
            # 删除原文件（仅删除转换成功的）
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, '确认删除原文件',
                f'转换已完成（成功 {success} 个）。\n\n'
                f'确定要删除成功转换的原文件吗？\n'
                f'此操作不可撤销！',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            deleted = 0
            for w in finished_workers:
                # 仅删除状态为成功的
                row = w.file_index
                status_item = self._table.item(row, COL_STATUS)
                if status_item and status_item.text() == FileStatus.SUCCESS:
                    try:
                        os.remove(w.input_path)
                        deleted += 1
                    except OSError:
                        pass
            self._status_bar.showMessage(f'已删除 {deleted} 个原文件', 5000)

        elif action == 'shutdown':
            # 关机（1 分钟后）
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, '确认关机',
                f'转换已完成（成功 {success} 个）。\n\n'
                f'确定要关闭计算机吗？\n'
                f'系统将在 60 秒后关机，可在此期间取消。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            import sys
            if sys.platform == 'win32':
                import subprocess
                # shutdown /s /t 60：60 秒后关机，可用 shutdown /a 取消
                subprocess.Popen(
                    ['shutdown', '/s', '/t', '60'],
                    creationflags=CREATE_NO_WINDOW,
                )
                QMessageBox.information(
                    self, '关机已计划',
                    '系统将在 60 秒后关机。\n'
                    '如需取消，请打开命令行执行：shutdown /a',
                )
            else:
                QMessageBox.information(
                    self, '提示',
                    '关机功能仅支持 Windows。',
                )

    def _show_completion_toast(self, success: int, failed: int, cancelled: int, elapsed: float, finished_workers: list | None = None) -> None:
        """转换完成后的即时反馈：Toast 通知 + 打开输出目录按钮。"""
        import sys
        mins, secs = divmod(int(elapsed), 60)
        title = '✅ 转换完成'
        body = f'成功 {success} 个'
        if failed > 0:
            body += f'，失败 {failed} 个'
        if cancelled > 0:
            body += f'，取消 {cancelled} 个'
        body += f'（{mins}分{secs:02d}秒）'

        # Windows Toast 通知（轻量级，不依赖第三方库）
        if sys.platform == 'win32':
            try:
                import ctypes
                # 使用 Windows API 的 Shell_NotifyIcon 显示气泡通知
                # 简化方案：直接用 MessageBox + 超时
                pass
            except Exception:
                pass

        # 在状态栏显示"打开输出目录"快捷操作
        output_dir = getattr(self, '_output_dir', '')
        source_workers = finished_workers or getattr(self, '_workers', [])
        if not output_dir:
            # 从第一个成功的 worker 获取输出目录
            for w in source_workers:
                if hasattr(w, 'output_path') and w.output_path:
                    output_dir = str(Path(w.output_path).parent)
                    break
        if output_dir and os.path.isdir(output_dir):
            self._status_bar.showMessage(
                f'{body}  📂 输出目录: {output_dir}  '
                f'（点击状态栏打开）'
            )
            # 保存当前输出目录引用，供状态栏点击使用（不覆盖 mousePressEvent）
            self._last_output_dir = output_dir

    def _open_output_dir_toast(self, output_dir: str) -> None:
        """点击状态栏打开输出目录。"""
        import sys
        import subprocess
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', output_dir],
                             creationflags=0x08000000)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', output_dir])
        else:
            subprocess.Popen(['xdg-open', output_dir])

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

    def _check_ffmpeg(self) -> None:
        """启动时检测 ffmpeg，不可用时提示用户。"""
        from utils import get_ffmpeg_version
        ver = get_ffmpeg_version()
        if not ver:
            self._status_bar.showMessage('⚠ FFmpeg 未检测到，视频/音频转换将不可用')
            self._ffmpeg_available = False
        else:
            self._ffmpeg_available = True
            # 状态栏显示版本前缀
            short_ver = ver.split('\n')[0] if ver else ''
            if short_ver:
                self._status_bar.showMessage(f'就绪 · {short_ver}', 3000)

    def _on_retry_failed(self) -> None:
        """重试所有失败的文件。"""
        if self._is_converting or self._cancel_in_progress:  # [STRESS-02 修复] 双重守卫
            return
        failed_rows = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_STATUS)
            if item and item.text() == FileStatus.FAILED:
                failed_rows.append(row)
        if not failed_rows:
            return
        self._retry_btn.setVisible(False)
        self._on_start_all(retry_rows=failed_rows)

    def _set_controls_enabled(self, enabled: bool) -> None:
        """统一启用/禁用所有操作控件。"""
        self._start_btn.setEnabled(enabled)
        self._cancel_btn.setEnabled(not enabled)
        self._pause_btn.setEnabled(not enabled)
        self._pause_btn.setVisible(not enabled)
        if enabled:
            self._pause_btn.setText('⏸ 暂停')
        self._add_file_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        self._remove_selected_btn.setEnabled(enabled)
        self._format_combo.setEnabled(enabled)
        self._output_dir_btn.setEnabled(enabled)
        for btn in self._category_btns.values():
            btn.setEnabled(enabled)

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
