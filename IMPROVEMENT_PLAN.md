# 全能转换工具 — 改进方案

> 生成时间: 2026-06-25
> 基于完整代码审查，覆盖功能、配置、代码、UI 四个维度

---

## 一、已修复的 BUG（本次）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `format_handlers.py:52,114` | IcoHandler/TiffHandler 的 `get_default_params` 缺少 `img` 参数，转 ICO/TIFF 必崩 | 补齐签名 `(self, img=None)` |
| 2 | `image_engine.py:92-123` | `_handle_alpha_channel` 不返回结果，RGBA→JPG 白色背景合成失效 | 改为 return img，调用方捕获返回值 |
| 3 | `ffmpeg_core.py:499` | MP4/MOV 默认音频 bitrate 硬编码 `'192k'`，忽略用户高级设置 | 改用 `audio_bitrate` 变量 + 加 `-ar` |
| 4 | `utils.py:258` | .gif 强制归入 video，拖入 .gif 文件自动跳转"视频"类别，用户困惑 | 改为归入 image |

---

## 二、P1 — 近期必做

### 2.1 清理死代码：queue_manager.py

**现状**: `ConversionQueue` 类从未被引用，UI 用的是 `BatchOrchestrator`。

**方案 A（推荐）— 删除**:
- 删除 `queue_manager.py` 和 `tests/test_queue_manager.py`
- 减少维护负担，避免新人困惑

**方案 B — 集成**:
- 把 `ConversionQueue` 的去重、暂停、拖拽排序能力移植到 `BatchOrchestrator`
- 工作量大，收益有限，不推荐现在做

### 2.2 ffmpeg 启动检测

**现状**: 用户没装 ffmpeg 时，视频/音频转换会报一个晦涩的 RuntimeError。

**方案**:
```python
# ui.py — MainWindow.__init__ 中添加
def _check_ffmpeg(self):
    from utils import get_ffmpeg_version
    ver = get_ffmpeg_version()
    if not ver:
        QMessageBox.warning(self, 'FFmpeg 未安装',
            '视频/音频转换需要 FFmpeg。\n\n'
            '请下载并放入项目 bin/ 目录，或添加到系统 PATH。\n'
            '下载地址: https://ffmpeg.org/download.html')
        # 禁用视频/音频类别的开始按钮
```

### 2.3 image_engine 警告接入 UI

**现状**: `image_engine.py:61` 用 `print()` 输出警告，用户看不到。

**方案**: 引擎函数增加 `warnings` 参数（可变列表），UI 层收集后批量展示。
```python
# image_engine.py
def convert_image(..., warnings_collector: list = None):
    ...
    if warnings_collector is not None:
        warnings_collector.extend(warnings)
    else:
        for w in warnings:
            print(f'[警告] {w}')
```

### 2.4 删除多余空行（format_handlers.py 尾部）

`format_handlers.py` 末尾有 5 行多余空行（126-130），应清理。

---

## 三、P2 — 功能增强

### 3.1 重试失败文件

**需求**: 批量转换后，用户想一键重试所有失败的文件。

**方案**:
```python
# ui.py — 在 _on_all_finished 中添加按钮
if failed > 0:
    self._retry_btn.setVisible(True)
    self._retry_btn.setText(f'重试失败文件 ({failed})')

def _on_retry_failed(self):
    """只重新创建失败文件的 worker"""
    failed_rows = []
    for row in range(self._table.rowCount()):
        item = self._table.item(row, COL_STATUS)
        if item and item.text() == FileStatus.FAILED:
            failed_rows.append(row)
    # 复用 _on_start_all 的逻辑，只传 failed_rows
```

### 3.2 键盘快捷键

```python
# ui.py — _connect_signals 中添加
from PyQt6.QtGui import QShortcut, QKeySequence

QShortcut(QKeySequence('Ctrl+O'), self, self._on_add_file)
QShortcut(QKeySequence('Delete'), self, self._on_remove_selected)
QShortcut(QKeySequence('Ctrl+A'), self, self._table.selectAll)
QShortcut(QKeySequence('Escape'), self, self._on_cancel)
```

### 3.3 右键菜单增强

当前右键只有"取消此文件"和"查看详情"。建议增加：

```python
# ui.py — _on_table_context_menu
if not self._is_converting:
    open_action = menu.addAction('打开文件')
    open_action.triggered.connect(lambda: os.startfile(file_path))

    reveal_action = menu.addAction('打开所在文件夹')
    reveal_action.triggered.connect(
        lambda: subprocess.Popen(['explorer', '/select,', file_path]))

    if status_text == FileStatus.SUCCESS:
        output = self._get_output_path(row)  # 需新增
        open_output = menu.addAction('打开输出文件')
        open_output.triggered.connect(lambda: os.startfile(output))
```

### 3.4 文件信息列扩展

在表格中增加一列显示源文件格式/编码信息（ffprobe 探测）：

| 文件名 | 格式 | 大小 | 进度 | 状态 |
|--------|------|------|------|------|
| video.mp4 | H.264/AAC | 150 MB | ████░ | 成功 |

**方案**: 添加文件时异步调用 ffprobe，结果存入 UserRole+1。
需要新增 `COL_FORMAT = 1`，后续列索引顺延。

### 3.5 拖拽排序

`queue_manager.py` 已有 `reorder()` 但 UI 未接入。

**方案**: 在 `DropableTableWidget` 中启用内部拖拽排序：
```python
self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
# 同步更新 worker 列表顺序和 _file_paths_set
```

---

## 四、P2 — 代码质量

### 4.1 拆分 ui.py（1245 行 → 4 个文件）

| 新文件 | 职责 | 预估行数 |
|--------|------|----------|
| `main_window.py` | 窗口框架、布局、信号连接 | ~300 |
| `file_table.py` | 文件列表管理（添加/删除/去重/拖拽） | ~200 |
| `conversion.py` | 转换控制（启动/取消/进度/完成） | ~250 |
| `settings.py` | 设置加载/保存/高级设置 | ~150 |

拆分方式：用 Mixin 模式或组合模式，避免循环导入。
```python
# main_window.py
class MainWindow(QMainWindow):
    def __init__(self):
        ...
        self._file_mgr = FileTableManager(self._table)
        self._conv_ctrl = ConversionController(self._orchestrator, self._table)
```

### 4.2 统一常量定义

```python
# constants.py（新建）
MAX_FILES_PER_BATCH = 500
MAX_EXCEL_ROWS = 5000
MAX_CANVAS_PIXELS = 4096 * 4096
DEFAULT_VIDEO_CRF = 23
DEFAULT_AUDIO_BITRATE = '192k'
VERSION = '1.1.0'
```

### 4.3 版本号统一管理

```python
# constants.py
VERSION = '1.1.0'
BUILD_DATE = '2026-06-25'

# ui.py:144
version_label = QLabel(f'v{VERSION}')
```

### 4.4 补充测试

优先级排序：

| 测试文件 | 测什么 | 难度 |
|----------|--------|------|
| `test_utils.py` | `safe_temp_path`, `finalize_file`, `get_file_size_str`, `map_format_to_category` | 低（纯函数） |
| `test_image_engine.py` | 用临时图片文件测端到端转换，验证 alpha 通道修复 | 中 |
| `test_ffmpeg_core.py` | 测命令构建逻辑（mock subprocess），不需真 ffmpeg | 中 |
| `test_document_engine.py` | mock pdf2docx/docx2pdf，测错误处理分支 | 中 |
| `test_workers.py` | 测状态机转换、cancel 幂等性 | 高（需 QThread） |

### 4.5 进度条性能优化

**现状**: 每行一个 `QProgressBar` cell widget，500 个文件 = 500 个 widget。

**方案**: 用自定义 `QStyledItemDelegate` 绘制进度条，只存数据不创建 widget：
```python
class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        progress = index.data(Qt.ItemDataRole.UserRole) or 0
        # 用 QPainter 画矩形进度条，零 widget 开销
```

对应地，进度值存入 item 的 UserRole，不再用 cellWidget。

---

## 五、P3 — 远期功能

### 5.1 深色模式

```python
# styles_dark.qss
# 复用现有 QSS 结构，替换颜色变量
QSS_LIGHT = load_qss('styles.qss')
QSS_DARK = load_qss('styles_dark.qss')

# 切换
def _toggle_theme(self, dark: bool):
    QApplication.instance().setStyleSheet(QSS_DARK if dark else QSS_LIGHT)
```

### 5.2 转换预设系统

```json
// presets.json
{
  "微信发送": {"video_crf": 28, "video_preset": "fast", "audio_bitrate": "128k"},
  "剪辑存档": {"video_crf": 18, "video_preset": "slow", "audio_bitrate": "320k"},
  "网页上传": {"image_quality": 80, "image_resize": 50}
}
```

### 5.3 命名模板

支持自定义输出文件名格式：
```
{原名}_{日期}_{序号}.{ext}
→ vacation_20260625_001.mp4
```

### 5.4 打包分发

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "all-in-one-converter"
version = "1.1.0"
requires-python = ">=3.10"
dependencies = [
    "PyQt6>=6.5.0",
    "Pillow>=10.0.0",
    "openpyxl>=3.1.0",
    "pdf2docx>=0.5.0",
    "docx2pdf>=0.1.0",
    "pywin32>=306",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-qt>=4.0"]
```

PyInstaller 打包配置：
```python
# build.spec
a = Analysis(
    ['main.py'],
    datas=[('styles.qss', '.'), ('icon.ico', '.')],
    hiddenimports=['engines.format_handlers', 'engines.codec_compat'],
    ...
)
```

---

## 六、执行路线图

```
第 1 周: P1 全部完成（ffmpeg 检测、警告接入、清理死代码）
第 2 周: P2 功能（重试失败、快捷键、右键菜单）
第 3 周: P2 代码（拆分 ui.py、统一常量、补充测试）
第 4 周: P3（深色模式、打包分发）
```

---

## 七、修改文件清单（本次修复）

```
E:\weapon\全能转换工具\engines\format_handlers.py  — IcoHandler/TiffHandler 签名修复
E:\weapon\全能转换工具\engines\image_engine.py     — _handle_alpha_channel 返回值修复
E:\weapon\全能转换工具\engines\ffmpeg_core.py      — 音频 bitrate 变量修复
E:\weapon\全能转换工具\utils.py                    — GIF 分类修复
```
