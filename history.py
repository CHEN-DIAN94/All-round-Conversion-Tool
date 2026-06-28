"""
history.py — 转换历史记录

JSON 文件存储，支持查询、重做、导出。
"""


__all__ = ['HistoryManager']

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

HISTORY_FILE = Path(__file__).resolve().parent / 'logs' / 'history.json'
MAX_HISTORY = 500


class HistoryManager:
    """转换历史管理器（线程安全）。"""

    def __init__(self, file_path: Optional[str] = None):
        self._file = Path(file_path) if file_path else HISTORY_FILE
        self._lock = Lock()
        self._records: list[dict] = []
        self._load()

    def _load(self) -> None:
        """从文件加载历史。仅接受 list[dict] 结构，脏数据自动降级。"""
        self._records = []
        try:
            if not self._file.exists():
                return
            with open(self._file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        if not isinstance(data, list):
            return

        self._records = [record for record in data if isinstance(record, dict)]

    def _save(self) -> None:
        """保存到文件。"""
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, 'w', encoding='utf-8') as f:
                json.dump(self._records, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def add(
        self,
        input_path: str,
        output_path: str,
        conv_type: str,
        success: bool,
        error: str = '',
        params: Optional[dict] = None,
        ffmpeg_cmd: str = '',
        duration_ms: int = 0,
    ) -> None:
        """添加一条历史记录。"""
        with self._lock:
            record = {
                'timestamp': datetime.now().isoformat(),
                'input': input_path,
                'output': output_path,
                'type': conv_type,
                'success': success,
                'error': error,
                'params': params or {},
                'ffmpeg_cmd': ffmpeg_cmd,
                'duration_ms': duration_ms,
            }
            self._records.append(record)
            # 超限截断
            if len(self._records) > MAX_HISTORY:
                self._records = self._records[-MAX_HISTORY:]
            self._save()

    def get_recent(self, count: int = 50) -> list[dict]:
        """获取最近 N 条记录。"""
        with self._lock:
            return list(reversed(self._records[-count:]))

    def get_failed(self) -> list[dict]:
        """获取所有失败记录。"""
        with self._lock:
            return [r for r in self._records if not r.get('success')]

    def search(self, keyword: str) -> list[dict]:
        """按关键词搜索（文件名/路径）。"""
        with self._lock:
            keyword_lower = keyword.lower()
            return [
                r for r in self._records
                if keyword_lower in r.get('input', '').lower()
                or keyword_lower in r.get('output', '').lower()
            ]

    def clear(self) -> None:
        """清空历史。"""
        with self._lock:
            self._records.clear()
            self._save()

    def export_markdown(self, output_path: str) -> str:
        """导出为 Markdown 报告。"""
        with self._lock:
            lines = ['# 转换历史报告\n']
            lines.append(f'导出时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            lines.append(f'记录总数: {len(self._records)}\n')

            success = sum(1 for r in self._records if r.get('success'))
            failed = len(self._records) - success
            lines.append(f'成功: {success}  失败: {failed}\n\n')

            for i, r in enumerate(self._records, 1):
                status = '✅' if r.get('success') else '❌'
                lines.append(f'## {i}. {status} {os.path.basename(r.get("input", ""))}\n')
                lines.append(f'- 时间: {r.get("timestamp", "")}')
                lines.append(f'- 类型: {r.get("type", "")}')
                lines.append(f'- 输入: `{r.get("input", "")}`')
                lines.append(f'- 输出: `{r.get("output", "")}`')
                if r.get('error'):
                    lines.append(f'- 错误: {r["error"]}')
                if r.get('duration_ms'):
                    lines.append(f'- 耗时: {r["duration_ms"]}ms')
                if r.get('ffmpeg_cmd'):
                    lines.append(f'- FFmpeg 命令: `{r["ffmpeg_cmd"]}`')
                lines.append('')

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            return output_path

    @property
    def count(self) -> int:
        return len(self._records)
