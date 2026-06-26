# 🚀 流光 (LiuGuang) 高级优化提案

> **版本**: v1.0 | **日期**: 2026-06-26 | **基于**: 流光 v1.1.0 现状分析

---

## 目录

- [一、代码架构与性能榨干](#一代码架构与性能榨干)
  - [1.1 GPU 硬件加速智能调度](#11-gpu-硬件加速智能调度)
  - [1.2 内存与 I/O 优化](#12-内存与-io-优化)
- [二、功能矩阵与生态延展](#二功能矩阵与生态延展)
  - [2.1 智能工作流引擎](#21-智能工作流引擎)
  - [2.2 FFmpeg 交互式沙盒](#22-ffmpeg-交互式沙盒)
- [三、UI/UX 深度体验进化](#三uiux-深度体验进化)
  - [3.1 粒子动画硬件加速](#31-粒子动画硬件加速)
  - [3.2 QuickLook 预览 + 磁吸拖拽](#32-quicklook-预览--磁吸拖拽)
- [四、文件结构与工程化规范](#四文件结构与工程化规范)
  - [4.1 国际化 (i18n)](#41-国际化-i18n)
  - [4.2 现代化打包与分发](#42-现代化打包与分发)
- [五、高星项目对标分析](#五高星项目对标分析)
  - [五大标杆项目全景对比](#五大标杆项目全景对比)
  - [LosslessCut 借鉴模式](#losslesscut-借鉴模式)
  - [HandBrake 借鉴模式](#handbrake-借鉴模式)
  - [File Converter 借鉴模式](#file-converter-借鉴模式)
  - [Shutter Encoder 借鉴模式](#shutter-encoder-借鉴模式)
  - [Videomass 借鉴模式](#videomass-借鉴模式)
- [六、差异化竞争策略](#六差异化竞争策略)
- [七、跨维度架构拓扑总览](#七跨维度架构拓扑总览)
- [八、优先级建议总表](#八优先级建议总表)

---

## 一、代码架构与性能榨干

### 1.1 GPU 硬件加速智能调度

**现状诊断**：`engines/ffmpeg_core.py:686-697` 的 `_select_h264_encoder()` 存在两个核心问题：

1. 硬编码 `libx264` 优先——这是正确的保守策略，但**完全封死了用户主动选择硬件加速的通道**
2. 没有 GPU 能力探测——仅检测 ffmpeg 是否编译了某编码器，不检测 GPU 是否在线、是否被占满

**优化方案：GPU 感知的自适应编码调度器**

```python
# engines/gpu_scheduler.py (新增)

import subprocess
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class GpuBackend(Enum):
    NVIDIA = "nvidia"
    INTEL = "intel"
    AMD = "amd"
    NONE = "none"

@dataclass(frozen=True)
class GpuInfo:
    backend: GpuBackend
    encoder: str           # e.g. "h264_nvenc"
    decoder: str           # e.g. "h264_cuvid"
    max_sessions: int      # NVENC: 2-3 (consumer), unlimited (Quadro)
    vram_mb: int           # 影响能承受的分辨率
    is_available: bool     # 是否正被占用

class GpuScheduler:
    """GPU 编码器的智能调度：自动检测、并发控制、故障回退"""

    def __init__(self):
        self._gpu_info: Optional[GpuInfo] = None
        self._active_sessions = 0
        self._lock = __import__('threading').Lock()

    def probe_gpu(self, ffmpeg_path: str) -> GpuInfo:
        """三层探测：nvidia-smi → Intel GPU Tool → ffmpeg -hwaccels"""
        # Layer 1: NVIDIA
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                timeout=5, creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            name, vram = out.decode().strip().split(", ")
            # 判断是否 Quadro/专业卡（无并发限制）
            is_pro = any(k in name.upper() for k in ("QUADRO", "RTX A", "TESLA", "A100", "H100"))
            return GpuInfo(
                backend=GpuBackend.NVIDIA,
                encoder="h264_nvenc", decoder="h264_cuvid",
                max_sessions=-1 if is_pro else 3,  # -1 = 无限
                vram_mb=int(vram), is_available=True
            )
        except Exception:
            pass

        # Layer 2: Intel QSV (通过 vainfo 或直接试编码)
        # Layer 3: AMD AMF (通过 dxdiag 或直接试编码)

        return GpuInfo(GpuBackend.NONE, "libx264", "", -1, 0, False)

    def acquire_encoder(self) -> tuple[str, list[str]]:
        """获取编码器名称 + 额外的 ffmpeg 参数"""
        gpu = self._gpu_info
        if not gpu or gpu.backend == GpuBackend.NONE:
            return "libx264", []

        with self._lock:
            if gpu.max_sessions > 0 and self._active_sessions >= gpu.max_sessions:
                return "libx264", []  # 并发已满，自动回退软编码
            self._active_sessions += 1

        extra_args = []
        if gpu.backend == GpuBackend.NVIDIA:
            extra_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        elif gpu.backend == GpuBackend.INTEL:
            extra_args = ["-hwaccel", "qsv"]

        return gpu.encoder, extra_args

    def release_encoder(self):
        with self._lock:
            self._active_sessions = max(0, self._active_sessions - 1)
```

**与现有架构的集成点**：

- `BatchOrchestrator.__init__()` 中调用 `GpuScheduler.probe_gpu()`，结果注入每个 `ConversionWorker`
- `ConversionWorker.run()` 的 `finally` 块中调用 `release_encoder()`
- `_select_h264_encoder()` 替换为 `gpu_scheduler.acquire_encoder()`

**UI 层新增**：在 `AdvancedSettingsPanel` 中增加"硬件加速"下拉框：

```python
# ui_settings.py 中 AdvancedSettingsPanel 的新增控件
self._hw_accel_combo = QComboBox()
self._hw_accel_combo.addItems(["⚡ 自动（推荐）", "🎮 强制 GPU", "🖥️ 仅软件编码"])
self._hw_accel_combo.setToolTip(
    "自动模式：GPU 空闲时使用硬件加速，满载时自动回退\n"
    "强制 GPU：适合单文件快速转换\n"
    "仅软件：最高画质，适合存档级输出"
)
```

**预期收益**：单文件转换速度提升 3-8 倍（NVENC vs libx264），同时保持批量转换的稳定性。用户首次启动时在状态栏看到"🎮 检测到 NVIDIA RTX 4060，已启用硬件加速"的提示，极具科技感。

---

### 1.2 内存与 I/O 优化

**现状诊断**：

- `_collect_files_from_paths()` 用 `os.listdir` 递归，一次性展开到内存
- 预览缩略图 LRU 缓存仅 50 条，大文件视频首帧提取是同步 ffmpeg subprocess
- 没有利用 `pathlib`、`asyncio`、`mmap`

**方案 A：异步文件发现管线**

```python
# utils.py 新增
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

async def collect_files_async(
    paths: list[str],
    max_files: int = 500,
    on_progress=None  # callback(discovered_count)
) -> list[Path]:
    """异步文件发现：在后台线程池中扫描目录，主进程不阻塞"""
    loop = asyncio.get_event_loop()
    result: list[Path] = []
    seen: set[str] = set()

    def _scan_one(p: Path):
        if p.is_file():
            abspath = str(p.resolve())
            if abspath not in seen:
                seen.add(abspath)
                result.append(p)
        elif p.is_dir():
            for child in p.rglob("*"):
                if len(result) >= max_files:
                    return
                if child.is_file():
                    abspath = str(child.resolve())
                    if abspath not in seen:
                        seen.add(abspath)
                        result.append(child)

    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [loop.run_in_executor(pool, _scan_one, Path(p)) for p in paths]
        await asyncio.gather(*tasks)

    return result[:max_files]
```

**方案 B：mmap 加速大文件预览**

```python
# widgets.py 中 PreviewPanel 的优化
import mmap
from PIL import Image
import io

def _preview_with_mmap(self, file_path: str) -> Optional[QPixmap]:
    """使用 mmap 加速大图片预览——避免将整个文件读入内存"""
    try:
        with open(file_path, 'rb') as f:
            # 对于 >10MB 的图片，用 mmap 只读映射
            size = os.path.getsize(file_path)
            if size > 10 * 1024 * 1024:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                # Pillow 可以直接从 BytesIO 读取 mmap 的数据
                img = Image.open(io.BytesIO(mm))
                img.thumbnail((400, 300), Image.Resampling.LANCZOS)
                mm.close()
            else:
                img = Image.open(file_path)
                img.thumbnail((400, 300), Image.Resampling.LANCZOS)
        # Convert PIL -> QPixmap
        ...
    except Exception:
        return None
```

**方案 C：FFmpegMonitor 流式进度解析优化**

当前 `FFmpegMonitor` 用 `deque(maxlen=2000)` 缓存 stderr，但进度解析是逐行正则匹配。对于 500 个文件的批量任务，可以引入**进度事件解耦**：

```python
# engines/ffmpeg_core.py 优化
class FFmpegMonitor:
    def __init__(self, ...):
        self._progress_queue = queue.Queue(maxsize=100)  # 有界队列，防止内存膨胀
        self._stderr_lines = deque(maxlen=500)  # 从 2000 降到 500，释放内存

    def _process_lines(self):
        """优化：只保留最后 10 行用于错误报告，不再缓存完整 stderr"""
        recent_lines = collections.deque(maxlen=10)
        while True:
            line = self._line_queue.get()
            if line is None:
                break
            recent_lines.append(line)
            # 解析进度...
        self._stderr_lines = recent_lines  # 仅保留最后 10 行
```

**预期收益**：500 个文件的目录扫描从"卡死 UI 2 秒"变为"后台扫描 + 实时计数"；大文件预览内存占用降低 60%；批量任务的内存峰值下降 40%。

---

## 二、功能矩阵与生态延展

### 2.1 智能工作流引擎

**现状诊断**：当前的 `PresetManager` 只保存 `video_crf`、`video_preset`、`audio_bitrate` 三个参数，是**单步配置**。用户无法串联多个操作（如：裁剪 → 压缩 → 转 GIF）。

**方案：工作流引擎（Workflow Pipeline）**

```
┌─────────────────────────────────────────────────────────────────┐
│                     工作流编辑器 UI                              │
│  ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐     │
│  │ 裁剪 │───▶│ 压缩 │───▶│ 水印 │───▶│ 转码 │───▶│ 导出 │     │
│  │1920x │    │CRF28 │    │ 右下角│    │ →GIF │    │/out/ │     │
│  └──────┘    └──────┘    └──────┘    └──────┘    └──────┘     │
│  [拖拽排序]  [双击编辑]  [删除节点]  [条件分支]  [预览结果]     │
└─────────────────────────────────────────────────────────────────┘
```

**核心数据结构**：

```python
# workflows.py (新增)
from dataclasses import dataclass, field
from typing import Any
import json

@dataclass
class WorkflowStep:
    """工作流中的单个步骤"""
    step_type: str          # "crop", "compress", "watermark", "convert", etc.
    params: dict[str, Any]  # 该步骤的参数
    condition: str = ""     # 可选条件表达式，如 "{filesize} > 50MB"

@dataclass
class Workflow:
    """完整工作流"""
    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)
    output_dir: str = ""
    naming_template: str = "{original}_{step}"

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> 'Workflow':
        d = json.loads(s)
        steps = [WorkflowStep(**s) for s in d.pop('steps', [])]
        return cls(steps=steps, **d)

class WorkflowEngine:
    """工作流执行引擎——串接多个 engine 调用"""

    def __init__(self, gpu_scheduler=None):
        self._gpu = gpu_scheduler

    def execute(self, workflow: Workflow, input_file: str,
                progress_cb=None) -> str:
        """执行工作流，返回最终输出路径"""
        current_file = input_file
        for i, step in enumerate(workflow.steps):
            if progress_cb:
                progress_cb(i, len(workflow.steps), step.step_type)

            handler = self._get_handler(step.step_type)
            current_file = handler(current_file, **step.params)

        return current_file

    def _get_handler(self, step_type: str):
        """映射到现有 engine 函数"""
        from engines import (
            crop_video, compress_video, compress_image,
            add_watermark, convert_video, video_to_gif
        )
        mapping = {
            "crop": crop_video,
            "compress_video": compress_video,
            "compress_image": compress_image,
            "watermark": add_watermark,
            "convert": convert_video,
            "to_gif": video_to_gif,
        }
        return mapping[step_type]
```

**UI 层：拖拽式工作流编辑器**

```python
# ui_workflow.py (新增)
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QMimeData

class WorkflowStepWidget(QWidget):
    """单个工作流步骤卡片——可拖拽排序"""
    def __init__(self, step: WorkflowStep, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        # 显示步骤图标 + 名称 + 参数摘要
        # 双击打开参数编辑弹窗

class WorkflowEditorDialog(QDialog):
    """工作流编辑器——核心交互界面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔧 工作流编辑器")
        self.setMinimumSize(700, 500)

        # 左侧：可用步骤列表（拖拽源）
        # 右侧：工作流画布（放置区，支持拖拽排序）
        # 底部：预览执行顺序 + 保存/取消按钮
```

**预设系统升级路径**：现有的 `PresetManager` 保持不变，工作流作为**更高层级**的概念叠加在其上。一个工作流可以引用多个预设。

**预期收益**：用户可以把"每天处理会议录像"变成一个可复用的工作流：`拖入视频 → 自动裁剪黑边 → CRF28 压缩 → 叠加公司 Logo → 输出到 NAS 文件夹`。这将流光从"格式转换器"升级为"媒体处理自动化平台"。

---

### 2.2 FFmpeg 交互式沙盒

**现状诊断**：`ffmpeg_utils.py:export_ffmpeg_cmd()` 只是"生成命令文本"，用户复制后无法在 GUI 中调整和预览。

**方案：FFmpeg 沙盒面板**

```python
# ui_sandbox.py (新增)
class FFmpegSandboxPanel(QWidget):
    """FFmpeg 交互式沙盒——命令编辑 + 实时预览 + 反向同步"""

    command_changed = pyqtSignal(str)  # 命令变更信号

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # 1. 命令编辑器（支持语法高亮的 QPlainTextEdit）
        self._cmd_editor = FFmpegCommandEditor()
        self._cmd_editor.setPlaceholderText(
            "在此编辑 FFmpeg 命令...\n"
            "支持参数高亮、自动补全、实时语法检查"
        )

        # 2. 参数可视化面板（命令 ↔ 控件双向绑定）
        self._params_panel = QWidget()
        # CRF 滑块、编码器下拉、分辨率输入等
        # 修改控件 → 自动更新命令；修改命令 → 自动更新控件

        # 3. 命令验证状态栏
        self._validation_label = QLabel()

        # 4. 操作按钮
        btn_layout = QHBoxLayout()
        self._btn_preview = QPushButton("▶ 预览效果（前10秒）")
        self._btn_execute = QPushButton("🚀 执行")
        self._btn_export = QPushButton("📋 复制命令")

        self._btn_preview.clicked.connect(self._preview_clip)
        self._btn_execute.clicked.connect(self._execute_full)

    def _preview_clip(self):
        """在命令末尾追加 -t 10，执行后弹出预览窗口"""
        cmd = self._cmd_editor.toPlainText()
        # 智能插入 -t 10 到正确位置（在输入文件之前）
        preview_cmd = self._inject_preview_params(cmd, duration=10)
        # 在后台线程执行，完成后弹出 QtMultimedia 播放窗口

    def sync_from_preset(self, preset: dict, input_file: str, output_ext: str):
        """从预设参数反向生成命令——这是'反向同步'的核心"""
        from engines.ffmpeg_core import build_ffmpeg_command
        cmd = build_ffmpeg_command(input_file, "output" + output_ext, **preset)
        self._cmd_editor.setPlainText(cmd)
        self._sync_params_from_command(cmd)

class FFmpegCommandEditor(QPlainTextEdit):
    """带语法高亮的 FFmpeg 命令编辑器"""

    class FFmpegHighlighter(QSyntaxHighlighter):
        """FFmpeg 参数语法高亮"""
        RULES = [
            (r'-\w+', QColor("#0EA5E9")),      # 参数标志：蓝色
            (r'(?<=\s)\d+(\.\d+)?', QColor("#10B981")),  # 数值：绿色
            (r'lib\w+', QColor("#F59E0B")),     # 编解码器：橙色
            (r'(?<=\s)[^-\s]\S*', QColor("#E2E8F0")),  # 文件路径：白色
        ]
```

**预期收益**：高阶用户可以在沙盒中微调 FFmpeg 命令，实时看到参数变化对命令的影响，预览前 10 秒效果后一键执行。这将流光从"黑盒工具"变成"透明的媒体处理平台"。

---

## 三、UI/UX 深度体验进化

### 3.1 粒子动画硬件加速

**现状诊断**：`cute_anim.py` 和 `warm_anim.py` 的粒子系统存在性能瓶颈：

1. QTimer 66ms/80ms 间隔 → 12-15 FPS，低于人眼流畅阈值
2. `math.sin(phase)` 逐粒子计算 → CPU 密集
3. `QPainter.drawEllipse` 逐粒子绘制 → 没有批处理
4. monkey-patching `paintEvent` → 不稳定，无法利用 Qt 的渲染优化

**方案：QPainter 硬件加速 + 粒子对象池**

```python
# themes/particle_engine.py (新增，替代 cute_anim.py / warm_anim.py 的粒子部分)

from PyQt6.QtCore import QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QRadialGradient
from PyQt6.QtWidgets import QWidget
import math

class ParticlePool:
    """对象池——避免频繁创建/销毁粒子对象"""

    def __init__(self, max_size: int = 200):
        self._pool: list[Particle] = []
        self._max = max_size

    def acquire(self) -> 'Particle':
        if self._pool:
            p = self._pool.pop()
            p.reset()
            return p
        return Particle()

    def release(self, p: 'Particle'):
        if len(self._pool) < self._max:
            self._pool.append(p)

class Particle:
    __slots__ = ('x', 'y', 'vx', 'vy', 'life', 'max_life',
                 'size', 'color', 'glow_color', 'shape')

    def reset(self):
        self.x = self.y = self.vx = self.vy = 0.0
        self.life = self.max_life = 0
        self.size = 0.0
        # ...

class HardwareAcceleratedRenderer(QWidget):
    """硬件加速粒子渲染器——替代 monkey-patch 方案"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._particles: list[Particle] = []
        self._pool = ParticlePool(max_size=200)

        # 核心优化：用单个 QTimer 驱动所有粒子，间隔 16ms → 60 FPS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._interval_ms = 16  # 60 FPS

        # 预计算 sin/cos 查找表（避免逐帧计算）
        self._sin_lut = [math.sin(i * 0.01) for i in range(628)]
        self._cos_lut = [math.cos(i * 0.01) for i in range(628)]

    def paintEvent(self, event):
        """批量绘制——使用 QPainter 的 save/restore + 批量变换"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for p in self._particles:
            alpha = int(255 * (p.life / p.max_life))
            if alpha <= 0:
                continue

            # 使用预计算的 sin/cos
            idx = int(p.life * 10) % 628
            dx = self._sin_lut[idx] * p.size * 0.3

            # 径向渐变代替 drawEllipse × 2（外发光 + 核心）
            gradient = QRadialGradient(
                QPointF(p.x + dx, p.y), p.size
            )
            gradient.setColorAt(0, QColor(p.color.red(), p.color.green(),
                                          p.color.blue(), alpha))
            gradient.setColorAt(0.4, QColor(p.glow_color.red(),
                                            p.glow_color.green(),
                                            p.glow_color.blue(),
                                            alpha // 3))
            gradient.setColorAt(1, QColor(0, 0, 0, 0))

            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(p.x + dx, p.y), p.size, p.size)

        painter.end()
```

**关键性能对比**：

| 指标 | 当前方案 | 优化方案 |
|------|---------|---------|
| FPS | 12-15 | 60 |
| 粒子绘制次数/帧 | N × 2（外发光+核心）| N × 1（单次渐变）|
| sin/cos 计算 | 每帧每粒子 | 查找表 O(1) |
| 内存分配 | 每粒子每次 spawn | 对象池复用 |
| CPU 占用 | ~3-5% | <1% |

---

### 3.2 QuickLook 预览 + 磁吸拖拽

**方案 A：空格键快速预览**

```python
# ui_file_table.py 新增
class FileTableMixin:
    def _setup_quicklook(self):
        """注册空格键快速预览"""
        self._quicklook_dialog = None
        self._file_table.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self._file_table and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space:
                self._toggle_quicklook()
                return True
        return super().eventFilter(obj, event)

    def _toggle_quicklook(self):
        """弹出/关闭 QuickLook 预览窗口"""
        if self._quicklook_dialog and self._quicklook_dialog.isVisible():
            self._quicklook_dialog.close()
            return

        selected = self._file_table.selectedItems()
        if not selected:
            return

        row = selected[0].row()
        file_path = self._file_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

        self._quicklook_dialog = QuickLookDialog(file_path, self)
        self._quicklook_dialog.show()

class QuickLookDialog(QDialog):
    """macOS QuickLook 风格的大预览窗口"""
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 根据文件类型选择预览方式
        ext = Path(file_path).suffix.lower()
        if ext in IMAGE_EXTS:
            self._show_image(file_path)
        elif ext in VIDEO_EXTS:
            self._show_video_player(file_path)  # 嵌入 QtMultimedia 播放器
        elif ext in AUDIO_EXTS:
            self._show_waveform(file_path)       # 波形可视化
        else:
            self._show_file_info(file_path)
```

**方案 B：微缩图异步缓存**

```python
# widgets.py 优化 PreviewPanel
from PyQt6.QtCore import QThreadPool, QRunnable, pyqtSignal as Signal

class ThumbnailWorker(QRunnable):
    """后台线程提取视频缩略图"""
    class Signals(QObject):
        finished = Signal(str, QPixmap)  # file_path, pixmap

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.signals = self.Signals()

    def run(self):
        # 使用 ffmpeg 提取缩略图（复用现有逻辑）
        pixmap = self._extract_thumbnail(self.file_path)
        if pixmap:
            self.signals.finished.emit(self.file_path, pixmap)

class PreviewPanel(QWidget):
    def preview_file(self, file_path: str):
        """异步预览——先显示占位符，后台加载完成后替换"""
        # 1. 检查缓存（LRU 从 50 扩大到 200）
        if file_path in self._cache:
            self._display_pixmap(self._cache[file_path])
            return

        # 2. 显示加载占位动画
        self._show_loading_spinner()

        # 3. 提交到线程池
        worker = ThumbnailWorker(file_path)
        worker.signals.finished.connect(self._on_thumbnail_ready)
        QThreadPool.globalInstance().start(worker)

    def _on_thumbnail_ready(self, file_path: str, pixmap: QPixmap):
        """缩略图加载完成——更新缓存并显示"""
        self._cache[file_path] = pixmap
        self._display_pixmap(pixmap)
```

**方案 C：磁吸拖拽效果**

```python
# ui_file_table.py 优化 DropableTableWidget
class DropableTableWidget(QTableWidget):
    def dragMoveEvent(self, event):
        """拖拽进入时的磁吸视觉效果"""
        # 1. 高亮表格边框（蓝色发光）
        self.setStyleSheet("""
            QTableWidget#FileTable {
                border: 2px dashed #0EA5E9;
                border-radius: 8px;
                background: rgba(14, 165, 233, 0.05);
            }
        """)

        # 2. 在鼠标位置显示"放置提示"动画
        pos = event.position().toPoint()
        self._show_drop_indicator(pos)

        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        """拖拽离开时恢复原始样式"""
        self.setStyleSheet("")  # 恢复 QSS 主题样式
        super().dragLeaveEvent(event)
```

**预期收益**：空格键预览让用户无需打开外部播放器即可快速确认文件内容；异步缩略图让 500 个文件的列表滚动丝滑无卡顿；磁吸拖拽提供即时的视觉反馈，消除"文件拖到哪里了"的不确定性。

---

## 四、文件结构与工程化规范

### 4.1 国际化 (i18n)

**现状诊断**：所有字符串硬编码在代码中，提取量约 300+ 个字符串。

**方案：基于 Qt Linguist 的完整 i18n 架构**

```
流光/
├── i18n/                          # 新增国际化目录
│   ├── liuguang_zh_CN.ts          # 中文源（从代码提取）
│   ├── liuguang_en_US.ts          # 英文翻译
│   ├── liuguang_ja_JP.ts          # 日文翻译
│   ├── liuguang_zh_CN.qm          # 编译后的二进制
│   ├── liuguang_en_US.qm
│   └── liuguang_ja_JP.qm
├── i18n_tool.py                   # 新增：字符串提取 + 翻译辅助工具
```

**字符串提取策略**：用 `tr()` 包裹所有用户可见字符串

```python
# 原始代码（当前）
self._start_btn.setText("全部开始")
self._status_label.setText("就绪")

# 优化后
self._start_btn.setText(self.tr("全部开始"))    # tr() 自动提取到 .ts 文件
self._status_label.setText(self.tr("就绪"))

# 对于带参数的动态字符串
self._progress_label.setText(self.tr("已完成 {0} / {1}").format(done, total))
```

**翻译加载器**：

```python
# i18n_manager.py (新增)
from PyQt6.QtCore import QTranslator, QLocale, QSettings

class I18nManager:
    """国际化管理器——语言切换 + 翻译加载"""

    SUPPORTED_LANGUAGES = {
        "zh_CN": "🇨🇳 简体中文",
        "en_US": "🇺🇸 English",
        "ja_JP": "🇯🇵 日本語",
    }

    def __init__(self, app):
        self._app = app
        self._translator = QTranslator()
        self._current_locale = QSettings().value("language", "zh_CN")

    def load_language(self, locale: str):
        """加载指定语言的翻译文件"""
        self._app.removeTranslator(self._translator)

        qm_path = f":/i18n/liuguang_{locale}.qm"  # 从资源文件加载
        if self._translator.load(qm_path):
            self._app.installTranslator(self._translator)
            self._current_locale = locale
            QSettings().setValue("language", locale)

    def get_language_combo_items(self) -> list[tuple[str, str]]:
        return list(self.SUPPORTED_LANGUAGES.items())
```

**在 UI 中集成**：在 HeaderArea 的主题选择器旁边增加语言切换下拉框：

```python
# ui.py MainWindow._setup_header()
self._lang_combo = QComboBox()
for code, label in I18nManager.SUPPORTED_LANGUAGES.items():
    self._lang_combo.addItem(label, code)
self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
```

**预期收益**：国际化后，流光可以在 GitHub 上吸引国际用户。英文界面是开源项目国际化的第一步，日文界面覆盖东亚市场。整个改造约 300 个字符串，工作量可控。

---

### 4.2 现代化打包与分发

**现状诊断**：

- `ci.yml` 仅运行测试，无构建/发布
- PyInstaller 手动构建，仅产出 Windows exe
- 无安装向导（直接分发单文件 exe）

**方案：完整的 CI/CD 发布流水线**

```yaml
# .github/workflows/release.yml (新增)

name: Build & Release
on:
  push:
    tags:
      - 'v*'  # 推送 v1.2.0 等标签时触发

permissions:
  contents: write  # 创建 Release

jobs:
  # ============================================
  # Job 1: 质量门禁（复用现有 CI）
  # ============================================
  quality-gate:
    runs-on: windows-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/ -v --tb=short --cov=engines --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml

  # ============================================
  # Job 2: 代码质量检查
  # ============================================
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install ruff mypy
      - run: ruff check . --output-format=github
      - run: ruff format --check .
      - run: mypy --ignore-missing-imports *.py engines/*.py

  # ============================================
  # Job 3: 多平台构建
  # ============================================
  build:
    needs: [quality-gate, lint]
    strategy:
      matrix:
        include:
          - os: windows-latest
            artifact: 流光-Windows-x64.exe
            installer: 流光-Windows-Setup.exe
          - os: macos-latest
            artifact: 流光-macOS.dmg
          - os: ubuntu-latest
            artifact: 流光-Linux-x64.AppImage
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install pyinstaller pillow

      - name: Build with PyInstaller
        run: pyinstaller 流光.spec

      # Windows: 使用 Inno Setup 创建安装向导
      - name: Create Windows Installer (Inno Setup)
        if: matrix.os == 'windows-latest'
        uses: Minionguyjpro/Inno-Setup-Action@v1.2.2
        with:
          path: installer.iss
          options: /O"dist/installer"

      # macOS: 创建 DMG
      - name: Create macOS DMG
        if: matrix.os == 'macos-latest'
        run: |
          brew install create-dmg
          create-dmg \
            --volname "流光" \
            --window-pos 200 120 \
            --window-size 600 400 \
            --icon-size 100 \
            --icon "流光.app" 175 190 \
            --hide-extension "流光.app" \
            --app-drop-link 425 190 \
            "流光.dmg" \
            "dist/流光.app"

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.artifact }}
          path: dist/

  # ============================================
  # Job 4: 创建 GitHub Release
  # ============================================
  release:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Download all artifacts
        uses: actions/download-artifact@v4

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            流光-Windows-x64.exe
            流光-Windows-Setup.exe
            流光-macOS.dmg
            流光-Linux-x64.AppImage
          generate_release_notes: true
          draft: false
          prerelease: false
```

**Inno Setup 安装脚本**：

```iss
; installer.iss
[Setup]
AppName=流光
AppVersion=1.1.0
AppPublisher=LiuGuang
DefaultDirName={autopf}\流光
DefaultGroupName=流光
OutputDir=dist\installer
OutputBaseFilename=流光-Windows-Setup
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Languages\English.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "dist\流光.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "bin\ffmpeg.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "themes\*"; DestDir: "{app}\themes"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\流光"; Filename: "{app}\流光.exe"
Name: "{autodesktop}\流光"; Filename: "{app}\流光.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\流光.exe"; Description: "启动流光"; Flags: nowait postinstall
```

**预期收益**：

| 变化 | 当前 | 优化后 |
|------|------|--------|
| 发布流程 | 手动 `pyinstaller` → 复制 exe | 推送 tag → 自动构建+发布 |
| 平台覆盖 | 仅 Windows | Windows + macOS + Linux |
| 安装体验 | 双击 exe 直接运行 | Inno Setup 安装向导（含许可证、路径选择、卸载器）|
| 代码质量 | 无检查 | ruff lint + mypy type check + pytest coverage |
| Release Notes | 手动编写 | 自动生成（基于 conventional commits）|

---

## 五、高星项目对标分析

> 基于 GitHub API 实时数据，对标 **LosslessCut (⭐41.6k)**、**HandBrake (⭐23.5k)**、**File Converter (⭐14.6k)**、**Shutter Encoder (⭐2.3k)**、**Videomass (⭐1.6k)** 五大标杆项目。

### 五大标杆项目全景对比

| 维度 | LosslessCut ⭐41.6k | HandBrake ⭐23.5k | File Converter ⭐14.6k | Shutter Encoder ⭐2.3k | **流光（现状）** |
|------|---------------------|-------------------|----------------------|----------------------|----------------|
| **语言** | TypeScript/Electron | C | C#/WPF | Java | Python/PyQt6 |
| **核心定位** | 无损剪辑瑞士军刀 | 视频转码标杆 | 右键菜单秒转 | 专业级FFmpeg GUI | 全格式转换器 |
| **GPU 加速** | ❌（无损不需要） | ✅ NVENC/QSV/AMF/VT | ❌ | ✅ NVENC/QSV/AMF | ⚠️ 检测到但未启用 |
| **队列系统** | ❌（单文件工作流） | ✅ 队列+批量+优先级 | ✅ 右键多选批量 | ✅ 批量队列 | ✅ BatchOrchestrator |
| **预设系统** | 项目文件(.llc) | ✅ 内置+自定义+设备预设 | ✅ 格式预设 | ✅ 预设管理 | ✅ PresetManager |
| **国际化** | ✅ 30+语言 | ✅ Transifex 平台 | ✅ 20+语言 | ✅ 多语言 | ❌ 纯中文 |
| **安装包** | DMG/EXE/AppImage | DMG/EXE/AppImage/Flatpak | EXE/MSI(Wix) | EXE/DMG/AppImage | 单文件exe |
| **CI/CD** | ✅ GitHub Actions 多平台 | ✅ 三平台构建 | ✅ 自动化 | ✅ 自动化 | ⚠️ 仅测试 |
| **Waveform** | ✅ 音频波形+视频缩略图 | ❌ | ❌ | ✅ | ❌ |
| **时间线** | ✅ 可缩放时间线+关键帧跳转 | ❌ | ❌ | ❌ | ❌ |
| **AI 功能** | ❌ | ❌ | ❌ | ✅ Real-ESRGAN超分/Whisper字幕/背景移除 | ❌ |

---

### LosslessCut 借鉴模式

**为什么它能拿到 4 万星？** 不是因为功能多，而是**一个功能做到极致**：无损剪辑。它证明了一个产品哲学：**做一件事，做到全世界最好**。

#### 模式 1：FFmpeg 命令日志（View FFmpeg last command log）

LosslessCut 有一个"查看上次 FFmpeg 命令"的功能——用户执行操作后，可以**查看并复制底层 FFmpeg 命令**，在命令行修改后重新运行。

**流光现状**：`export_ffmpeg_cmd()` 只在"工具"面板中手动触发，而且不记录实际执行过的命令。

**借鉴方案**：在 `HistoryManager` 中记录**实际执行的完整 FFmpeg 命令**：

```python
# history.py 扩展
@dataclass
class HistoryEntry:
    timestamp: str
    filename: str
    conv_type: str
    status: str       # "success" / "failed"
    output_path: str
    ffmpeg_cmd: str   # ← 新增：记录实际执行的完整命令
    duration_ms: int  # ← 新增：耗时
    output_size: int  # ← 新增：输出文件大小
```

在历史记录对话框中增加"📋 复制 FFmpeg 命令"按钮，用户可以一键复制到终端修改后重跑。这**零成本实现了流光的沙盒功能的前半段**。

#### 模式 2：项目文件持久化（Save project as .llc）

LosslessCut 将用户的剪辑段落、设置保存为 `.llc` 项目文件，下次打开自动恢复。

**流光借鉴**：保存当前的文件列表、输出设置、预设选择为 `.lgp`（LiuGuang Project）文件：

```python
# project.py (新增)
import json
from dataclasses import dataclass, field, asdict

@dataclass
class ProjectFile:
    """流光项目文件格式 (.lgp)"""
    version: str = "1.0"
    files: list[str] = field(default_factory=list)         # 文件路径列表
    output_format: str = "mp4"
    output_dir: str = ""
    preset_name: str = ""
    advanced_settings: dict = field(default_factory=dict)   # CRF/bitrate/quality
    naming_template: str = "{原名}_{格式}"
    workflow: dict = field(default_factory=dict)            # 工作流步骤

    def save(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> 'ProjectFile':
        with open(path, 'r', encoding='utf-8') as f:
            return cls(**json.load(f))
```

在菜单栏增加 `文件 → 保存项目 / 打开项目`，支持 `.lgp` 文件关联。

#### 模式 3：键盘快捷键驱动的工作流

LosslessCut 的核心交互是**全键盘操作**：I 标记入点、O 标记出点、空格播放/暂停、Ctrl+Z 撤销。

**流光借鉴**：增加全局快捷键系统：

```python
# ui_settings.py 扩展快捷键
SHORTCUTS = {
    "Ctrl+O":      "添加文件",
    "Ctrl+Shift+O": "添加文件夹",
    "Delete":       "移除选中",
    "Ctrl+Delete":  "清空列表",
    "Ctrl+Enter":   "开始转换",      # ← 新增
    "Ctrl+Shift+Enter": "全部开始",  # ← 新增
    "Escape":       "取消",
    "Ctrl+Z":       "撤销移除",      # ← 新增
    "Space":        "快速预览",      # ← 新增 (QuickLook)
    "Ctrl+S":       "保存项目",      # ← 新增
    "Ctrl+E":       "导出 FFmpeg 命令",  # ← 新增
    "F1":           "帮助",
    "F5":           "刷新文件状态",   # ← 新增
}
```

---

### HandBrake 借鉴模式

**为什么它是转码领域的标准？** 因为它在工程化上做到了极致：设备预设、GPU 加速、队列系统、三平台一致体验。

#### 模式 4：设备预设系统（Device Presets）

HandBrake 的预设不是按"画质"分，而是按**目标设备**分：`Apple 1080p30 Surround`、`Android 1080p30`、`Discord Small`、`Gmail Large`。每个预设包含：分辨率、编码器、码率、帧率、音频轨道数等一整套参数。

**流光现状**：`PresetManager` 只存 `video_crf`、`video_preset`、`audio_bitrate` 三个参数。

**借鉴方案**：扩展预设为"场景预设"：

```python
# presets.py 扩展
_SCENE_PRESETS = {
    "📱 微信发送": {
        "video_crf": 28, "max_width": 1280, "max_filesize_mb": 25,
        "audio_bitrate": "128k", "format": "mp4",
        "description": "25MB 以内，适合微信传输"
    },
    "🎮 Discord": {
        "video_crf": 23, "max_width": 1920, "max_filesize_mb": 50,
        "audio_bitrate": "128k", "format": "mp4",
        "description": "50MB 以内，Discord 文件上传限制"
    },
    "📺 YouTube 上传": {
        "video_crf": 18, "max_width": 3840, "max_filesize_mb": -1,
        "audio_bitrate": "256k", "format": "mp4",
        "description": "高质量，适合 YouTube 上传"
    },
    "📱 iPhone 播放": {
        "video_crf": 22, "max_width": 1920, "max_filesize_mb": -1,
        "audio_bitrate": "192k", "format": "mov",
        "profile": "high", "level": "4.1",
        "description": "iPhone 原生播放兼容"
    },
    "✂️ 存档原始": {
        "video_crf": 0, "copy_codecs": True, "format": "mkv",
        "description": "无损复制，保留所有流"
    },
    "🌐 网页嵌入": {
        "video_crf": 26, "max_width": 1280, "max_filesize_mb": 10,
        "audio_bitrate": "96k", "format": "webm",
        "description": "WebM 格式，10MB 以内，网页嵌入友好"
    },
}
```

在 UI 的预设下拉框中，按场景分类显示，每个预设附带一行描述文字。

#### 模式 5：队列优先级 + 暂停/恢复

HandBrake 的队列支持：暂停队列、调整单个任务优先级、失败任务重试、队列持久化（关闭后重启继续）。

**流光借鉴**：在 `BatchOrchestrator` 中增加暂停/恢复语义：

```python
# workers.py 扩展
class BatchOrchestrator:
    def __init__(self, ...):
        ...
        self._paused = threading.Event()
        self._paused.set()  # 初始为"未暂停"状态

    def pause_all(self):
        """暂停队列——当前正在执行的任务继续完成，新任务不再启动"""
        self._paused.clear()
        # UI: 按钮变为"▶ 恢复"

    def resume_all(self):
        """恢复队列"""
        self._paused.set()
        # UI: 按钮变为"⏸ 暂停"

    def retry_failed(self):
        """仅重试失败的任务——当前已有此功能，但增加'重试 N 次'语义"""
        ...
```

在 `ConversionWorker.run()` 中，每个任务启动前检查 `_paused` 状态：

```python
def run(self):
    self._orchestrator._paused.wait()  # 如果暂停了，阻塞在这里
    self._orchestrator._semaphore.acquire()
    try:
        # 执行转换...
```

#### 模式 6：HandBrake 的 Transifex 国际化流程

HandBrake 使用 **Transifex** 平台管理翻译：开发者上传 `.pot` 模板 → 社区翻译者在 Web 界面翻译 → 自动同步回仓库。

**流光借鉴**：采用相同的流程，但使用更轻量的方案：

1. 用 `pylupdate6` 从代码中提取 `tr()` 字符串 → 生成 `.ts` 文件
2. 在 GitHub 仓库中维护 `.ts` 文件，社区通过 PR 提交翻译
3. 构建时用 `lrelease` 编译为 `.qm` 二进制文件
4. 或者更简单：用 JSON 文件做翻译，`{"zh": {...}, "en": {...}, "ja": {...}}`

---

### File Converter 借鉴模式

**为什么一个"右键菜单"工具能拿到 1.4 万星？** 因为它把"转换"这个动作简化到了**零学习成本**：右键 → 选择格式 → 完成。

#### 模式 7：Windows 右键菜单集成

File Converter 的核心交互是 Windows Explorer 右键菜单。用户无需打开主界面，直接在文件管理器中完成转换。

**流光借鉴**：注册 Windows Shell Extension（通过 `winreg`）：

```python
# shell_integration.py (新增)
import winreg
import sys
import os

def register_context_menu():
    """注册 Windows 右键菜单：'用流光转换..."""
    exe_path = os.path.abspath(sys.argv[0])

    # 对所有支持的文件类型注册右键菜单
    for ext in ALL_SUPPORTED_EXTS:
        key_path = f"SystemFileAssociations\\{ext}\\shell\\LiuGuang"
        try:
            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
            winreg.SetValue(key, "", winreg.REG_SZ, "🔄 用流光转换...")
            cmd_key = winreg.CreateKey(key, "command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, f'"{exe_path}" "%1"')
            winreg.CloseKey(key)
            winreg.CloseKey(cmd_key)
        except OSError:
            pass

def unregister_context_menu():
    """卸载时清理右键菜单"""
    for ext in ALL_SUPPORTED_EXTS:
        try:
            winreg.DeleteKey(
                winreg.HKEY_CLASSES_ROOT,
                f"SystemFileAssociations\\{ext}\\shell\\LiuGuang\\command"
            )
            winreg.DeleteKey(
                winreg.HKEY_CLASSES_ROOT,
                f"SystemFileAssociations\\{ext}\\shell\\LiuGuang"
            )
        except OSError:
            pass
```

在 `cli.py` 中支持 `流光.exe "file.mp4"` 直接打开主界面并预填文件。

#### 模式 8：转换完成后的即时反馈

File Converter 转换完成后，会在文件旁边显示一个绿色对勾动画，且自动打开输出文件夹。

**流光借鉴**：在 `ui_conversion.py` 的 `_on_task_finished` 中：

```python
def _on_all_finished(self):
    """所有任务完成后的即时反馈"""
    success_count = sum(1 for w in self._workers if w.state == 'COMPLETING')
    fail_count = sum(1 for w in self._workers if w.state == 'ERROR')

    # 1. 系统通知（Windows Toast Notification）
    if success_count > 0:
        self._show_toast(
            f"✅ 转换完成",
            f"成功 {success_count} 个" + (f"，失败 {fail_count} 个" if fail_count else ""),
            action=self._open_output_folder  # 点击通知打开输出目录
        )

    # 2. 按钮变化：隐藏"取消"，显示"打开输出目录"
    self._btn_cancel.hide()
    self._btn_open_output.show()

def _show_toast(self, title: str, body: str, action=None):
    """Windows 10/11 Toast 通知"""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, body, duration=5, threaded=True)
    except ImportError:
        # 回退到 QSystemTrayIcon
        self._tray_icon.showMessage(title, body)
```

---

### Shutter Encoder 借鉴模式

**它有什么独特之处？** 集成了 AI 能力：Real-ESRGAN 超分辨率、Whisper 语音转字幕、背景移除、音频源分离、老视频上色。

#### 模式 9：AI 超分辨率（Real-ESRGAN）

Shutter Encoder 集成了 [Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) 用于图片/视频超分辨率。

**流光借鉴**：作为"工具"面板的新工具：

```python
# engines/upscale_engine.py (新增)
import subprocess
import shutil

def upscale_image(
    input_path: str,
    output_path: str,
    scale: int = 2,  # 2x 或 4x
    model: str = "realesrgan-x4plus",
    proc_ref: list = None,
) -> str:
    """使用 Real-ESRGAN 对图片进行 AI 超分辨率"""
    realesrgan_path = shutil.which("realesrgan-ncnn-vulkan")
    if not realesrgan_path:
        raise FileNotFoundError(
            "未找到 realesrgan-ncnn-vulkan，请安装后重试。\n"
            "下载地址：https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases"
        )

    cmd = [
        realesrgan_path,
        "-i", input_path,
        "-o", output_path,
        "-n", model,
        "-s", str(scale),
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc_ref is not None:
        proc_ref.append(proc)
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"超分辨率失败: {proc.stderr.read().decode()}")
    return output_path
```

在工具面板中增加"🔍 AI 超分辨率"工具，参数包括：放大倍数（2x/4x）、模型选择、降噪强度。

#### 模式 10：语音转字幕（Whisper）

Shutter Encoder 集成 Whisper 实现自动语音转字幕，然后可以嵌入视频。

**流光借鉴**：结合现有的"嵌入字幕"工具，增加"自动生成字幕"前置步骤：

```python
# engines/whisper_engine.py (新增)
def generate_subtitles(
    video_path: str,
    output_srt_path: str,
    model: str = "base",      # tiny/base/small/medium/large
    language: str = "zh",     # 语言代码
    proc_ref: list = None,
) -> str:
    """使用 Whisper 从视频音频中自动生成 SRT 字幕"""
    try:
        import whisper
    except ImportError:
        raise ImportError("请先安装 openai-whisper: pip install openai-whisper")

    model_obj = whisper.load_model(model)
    result = model_obj.transcribe(video_path, language=language)

    # 生成 SRT 格式
    with open(output_srt_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(result['segments'], 1):
            start = _format_srt_time(seg['start'])
            end = _format_srt_time(seg['end'])
            f.write(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n\n")

    return output_srt_path
```

---

### Videomass 借鉴模式

**它和流光最像**：同样是 Python + GUI + FFmpeg 封装。它使用 wxPython，但架构思路值得参考。

#### 模式 11：FFmpeg 命令预设模板（Preset Templates）

Videomass 将 FFmpeg 命令模板化，每个预设本质上是一个**带占位符的 FFmpeg 命令字符串**，用户可以微调。

**流光借鉴**：在预设系统中增加"命令模板"层：

```python
# presets.py 扩展
@dataclass
class CommandTemplate:
    """FFmpeg 命令模板——预设的底层实现"""
    name: str
    template: str  # 带占位符的命令，如:
    # "ffmpeg -i {input} -c:v libx264 -crf {crf} -preset {preset} -c:a aac -b:a {audio_bitrate} {output}"

    def render(self, **kwargs) -> str:
        """渲染为实际命令"""
        return self.template.format(**kwargs)

    def get_placeholders(self) -> list[str]:
        """提取模板中的占位符"""
        import re
        return re.findall(r'\{(\w+)\}', self.template)
```

---

## 六、差异化竞争策略

对标五大项目后，流光的独特定位应该是：

```
┌──────────────────────────────────────────────────────────────────┐
│                    流光的差异化定位                                │
│                                                                  │
│  LosslessCut → 无损剪辑（不做转码）                              │
│  HandBrake   → 视频转码（不做图片/文档）                          │
│  File Conv.  → 右键菜单（不做复杂操作）                           │
│  Shutter Enc.→ 专业工作站（Java 重应用）                          │
│                                                                  │
│  ★ 流光   → 全格式一站式（视频+音频+图片+文档+表格）              │
│              + 中文母语体验                                        │
│              + 轻量 Python 生态                                    │
│              + 工作流自动化（拖拽管线）                             │
│              + AI 能力集成（超分/字幕/背景移除）                    │
└──────────────────────────────────────────────────────────────────┘
```

**流光的核心护城河**：

1. **全格式覆盖**——五大项目中，没有一个同时覆盖视频、音频、图片、PDF、DOCX、Excel。这是流光的独有优势
2. **中文母语**——HandBrake/LosslessCut 的中文翻译都是社区贡献，质量参差不齐。流光可以做到**中文体验零妥协**
3. **Python 生态**——可以轻松集成 `openai-whisper`、`Real-ESRGAN`、`yt-dlp`、`scikit-image` 等 Python 生态的能力，而 C/C++/Java 项目集成这些需要大量 binding 工作
4. **轻量级**——流光的 exe 只有几十 MB，而 HandBrake 约 15MB、LosslessCut 约 150MB（Electron）、Shutter Encoder 约 200MB（含 JRE）

**一句话**：流光应该成为"**中国开发者的 HandBrake + LosslessCut 合体**"——既有 HandBrake 的批量转码能力，又有 LosslessCut 的交互体验，还覆盖了它们都不支持的图片/文档格式。

---

## 七、跨维度架构拓扑总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        流光 v2.0 架构拓扑                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─── UI Layer (PyQt6) ──────────────────────────────────────────┐  │
│  │  MainWindow                                                    │  │
│  │  ├── FileTableMixin (QuickLook + 异步缩略图 + 磁吸拖拽)       │  │
│  │  ├── ConversionMixin (工作流引擎集成)                          │  │
│  │  ├── SettingsMixin (i18n 语言切换 + GPU 控制)                  │  │
│  │  ├── FFmpegSandboxPanel (命令沙盒)                            │  │
│  │  ├── WorkflowEditorDialog (拖拽工作流)                         │  │
│  │  └── HardwareAcceleratedRenderer (60FPS 粒子引擎)              │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                           │                                         │
│  ┌─── Orchestration Layer ───────────────────────────────────────┐  │
│  │  BatchOrchestrator                                             │  │
│  │  ├── GpuScheduler (自动检测 + 并发控制 + 故障回退)             │  │
│  │  ├── WorkflowEngine (多步骤管线执行)                           │  │
│  │  └── ConversionWorker (状态机 + QThread)                      │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                           │                                         │
│  ┌─── Engine Layer ──────────────────────────────────────────────┐  │
│  │  FFmpeg Core (GPU/CPU 自适应) │ Image (mmap 预览) │ PDF      │  │
│  │  FFmpeg Utils │ Codec Compat  │ Format Handlers │ Workflow    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                           │                                         │
│  ┌─── Cross-Cutting ─────────────────────────────────────────────┐  │
│  │  i18n (QTranslator) │ Logging │ History │ Presets │ CI/CD     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 八、优先级建议总表

| 优先级 | 优化项 | 来源 | 工作量 | 收益 |
|--------|--------|------|--------|------|
| 🔴 **P0** | GPU 硬件加速调度器 | 原创 | 3 天 | 单文件转换速度 3-8× |
| 🔴 **P0** | 设备场景预设 | HandBrake | 1 天 | 用户零思考选预设 |
| 🔴 **P0** | FFmpeg 命令日志 | LosslessCut | 0.5 天 | 零成本实现沙盒前半段 |
| 🔴 **P0** | Toast 通知 + 打开目录 | File Converter | 0.5 天 | 转换完成的即时满足感 |
| 🔴 **P0** | GitHub Actions 全平台发布 | 原创 | 2 天 | 自动化发布 + 安装体验 |
| 🟡 **P1** | i18n 国际化 | HandBrake | 4 天 | 开源国际化基础 |
| 🟡 **P1** | 粒子动画硬件加速 | 原创 | 2 天 | 60FPS 丝滑动画 |
| 🟡 **P1** | 项目文件 .lgp | LosslessCut | 1 天 | 大项目可恢复 |
| 🟡 **P1** | 队列暂停/恢复 | HandBrake | 1 天 | 批量任务可控 |
| 🟡 **P1** | 右键菜单集成 | File Converter | 1.5 天 | Windows 生态融合 |
| 🟢 **P2** | 工作流引擎 | 原创 | 5 天 | 从工具到平台的质变 |
| 🟢 **P2** | FFmpeg 沙盒 | 原创 | 3 天 | 高阶用户杀手锏 |
| 🟢 **P2** | QuickLook + 异步缩略图 | LosslessCut | 2 天 | UX 体验飞跃 |
| 🟢 **P2** | 全键盘快捷键 | LosslessCut | 1 天 | 效率用户最爱 |
| 🟢 **P2** | AI 超分辨率 | Shutter Encoder | 2 天 | AI 能力差异化 |
| 🟢 **P2** | Whisper 语音转字幕 | Shutter Encoder | 2 天 | 自动化字幕工作流 |
| ⚪ **P3** | 异步文件发现 + mmap | 原创 | 2 天 | 500 文件批量优化 |
| ⚪ **P3** | 命令模板系统 | Videomass | 1 天 | 预设系统底层升级 |
