"""
project.py — 流光项目文件格式 (.lgp)

保存/加载当前工作状态：文件列表、输出设置、预设选择等。
支持 .lgp (LiuGuang Project) 文件关联。
"""

__all__ = ['ProjectFile']

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ProjectFile:
    """
    流光项目文件。

    .lgp 文件是 JSON 格式，包含：
    - 文件列表
    - 输出格式和目录
    - 预设名称
    - 高级设置
    - 命名模板
    """

    version: str = '1.0'
    files: list[str] = field(default_factory=list)
    output_format: str = 'mp4'
    output_dir: str = ''
    preset_name: str = ''
    advanced_settings: dict = field(default_factory=dict)
    naming_template: str = '{原名}_{格式}'

    def save(self, path: str) -> None:
        """保存项目文件。"""
        data = asdict(self)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> 'ProjectFile':
        """加载项目文件。"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 兼容未来版本：忽略未知字段
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def get_valid_files(self) -> list[str]:
        """返回仍然存在的文件列表。"""
        import os
        return [f for f in self.files if os.path.isfile(f)]

    def get_missing_files(self) -> list[str]:
        """返回已丢失的文件列表。"""
        import os
        return [f for f in self.files if not os.path.isfile(f)]
