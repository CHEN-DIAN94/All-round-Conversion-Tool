"""
task_models.py — 任务模型与执行契约

为 Phase 1 重构提供强类型任务对象，替代散落的字符串和裸 dict。
"""

from __future__ import annotations

__all__ = [
    'ExecutionResult',
    'TaskSpec',
]

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TaskSpec:
    """描述一次可执行任务。"""

    key: str
    input_path: str
    output_path: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionResult:
    """执行结果模型。"""

    output_path: str | None = None
    progress_complete: bool = False
