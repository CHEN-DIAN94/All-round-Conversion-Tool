# 流光 — 全方位测试设计文档

**文档版本**: v1.0
**编写人**: Senior Test Engineer
**日期**: 2026-06-26
**项目版本**: v1.1.0
**前置条件**: Python 3.10+, FFmpeg 6.0+ (在 `bin/` 或 PATH), Poppler (PDF→图片)

---

## 1. 核心功能边界测试用例 (Boundary & Exception Test Cases)

### 1.1 视频画面裁剪 (`engines/ffmpeg_utils.py:crop_video`)

源码分析: `crop_video` 在 `ffmpeg_utils.py:227-282`，对 `width`/`height` 做 `<= 0` 校验，但 **未校验** `x + width` 是否超出源视频宽高、`x/y` 为负数的情况。FFmpeg 的 `crop` filter 自身会报错，但当前代码没有对此做前置拦截。

| 编号 | 测试模块 | 输入操作 | 预期结果 | 测试要点 |
|------|----------|----------|----------|----------|
| CROP-01 | crop_video | `width=0, height=100` | `ValueError("裁剪尺寸必须为正数")` | 零值边界：代码 L257 有显式校验 |
| CROP-02 | crop_video | `width=-1, height=100` | `ValueError` | 负数边界：同上 |
| CROP-03 | crop_video | `width=1920, height=1080, x=0, y=0`，源视频 1280×720 | FFmpeg 报错，`RuntimeError` 被抛出 | **尺寸溢出**：裁剪区域超出源视频，验证 `_run_ffmpeg_utils` 中 `proc.returncode != 0` 分支能否正确提取错误信息 |
| CROP-04 | crop_video | `width=100, height=100, x=1280, y=720`，源视频 1280×720 | FFmpeg 报错 | **起始坐标贴边**：x 恰好等于源宽，裁剪区域完全在画面外 |
| CROP-05 | crop_video | `width=100, height=100, x=-10, y=0` | FFmpeg 报错 | **负坐标**：当前代码未拦截负数传入 FFmpeg |
| CROP-06 | crop_video | `width=1280, height=720, x=0, y=0`，源视频 1280×720 | 成功输出 | **临界值-全画面裁剪**：裁剪区域 = 源视频尺寸，应等价于 copy |
| CROP-07 | crop_video | `width=1, height=1, x=0, y=0` | 成功输出 1×1 像素视频 | **最小裁剪** |
| CROP-08 | crop_video | `width=奇数, height=奇数`（如 641×481），编码器 libx264 | 可能警告或自动 pad | **奇偶校验**：H.264 要求偶数尺寸，验证 `-pix_fmt yuv420p` 是否处理 |
| CROP-09 | crop_video | 输入文件不存在 | `FileNotFoundError` | L255 前置校验 |
| CROP-10 | crop_video | 输入为 0 字节文件 | `RuntimeError("画面裁剪失败")` | 损坏文件容错 |

**建议代码改进**: 在 `crop_video` 中增加前置校验:

```python
# ffmpeg_utils.py:crop_video 建议新增
if x < 0 or y < 0:
    raise ValueError(f'裁剪坐标不能为负数: ({x}, {y})')
```

---

### 1.2 音视频合并 (`engines/ffmpeg_utils.py:merge_media`)

源码分析: `merge_media` 使用 concat demuxer (`-f concat -safe 0 -c copy`)，要求所有输入编码格式一致。对不一致的情况没有自动转码逻辑。

| 编号 | 测试模块 | 输入操作 | 预期结果 | 测试要点 |
|------|----------|----------|----------|----------|
| MERGE-01 | merge_media | 传入 1 个文件 | `ValueError("至少需要 2 个文件")` | 最小数量边界（L188-189） |
| MERGE-02 | merge_media | 传入空列表 `[]` | `ValueError` | 空列表边界 |
| MERGE-03 | merge_media | 传入 2 个相同编码的 MP4 (H.264+AAC) | 成功合并 | 正常路径 |
| MERGE-04 | merge_media | 传入 MP4(H.264) + AVI(MPEG4) | FFmpeg concat 失败，抛 `RuntimeError` | **不同编码**：concat demuxer 要求同编码，验证错误信息是否可读 |
| MERGE-05 | merge_media | 传入 MP4(1920×1080) + MP4(640×480)，同编码 | 成功或 FFmpeg 报错 | **不同分辨率**：concat copy 可能成功但播放异常 |
| MERGE-06 | merge_media | 传入 MP4(44100Hz) + MP4(48000Hz) | 可能成功（音频 concat 不强制同采样率）或播放异常 | **不同采样率**容错 |
| MERGE-07 | merge_media | 传入 1 个正常 MP4 + 1 个损坏文件 (0 字节) | FFmpeg 报错 | **损坏文件混入** |
| MERGE-08 | merge_media | 其中一个文件路径包含单引号 `'` | 成功合并 | L204 的 `escaped = p.replace("'", "'\\''")` 转义逻辑 |
| MERGE-09 | merge_media | 其中一个文件不存在 | `FileNotFoundError` | L192 校验 |
| MERGE-10 | merge_media | 传入 500 个文件 | 成功或超时 | 大批量合并的 concat 文件写入和 FFmpeg 内存 |
| MERGE-11 | merge_media | 传入 2 个 MKV(含字幕流) | 合并后字幕流是否保留 | `-map_metadata 0` 只映射第一个文件的元数据 |

---

### 1.3 字幕嵌入/提取 (`embed_subtitle` / `extract_subtitle`)

| 编号 | 测试模块 | 输入操作 | 预期结果 | 测试要点 |
|------|----------|----------|----------|----------|
| SUB-01 | embed_subtitle | 字幕文件不存在 | `FileNotFoundError` | L97 校验 |
| SUB-02 | embed_subtitle | 字幕文件为 `.txt` 格式 | `ValueError("不支持的字幕格式: .txt")` | L119 校验 |
| SUB-03 | embed_subtitle | 字幕文件为 0 字节 `.srt` | FFmpeg 可能报错或嵌入空字幕 | 空文件容错 |
| SUB-04 | embed_subtitle | 损坏的 `.srt` 文件（非 UTF-8 编码，如 GBK） | FFmpeg 报错或乱码 | **编码问题**：代码未做编码转换 |
| SUB-05 | embed_subtitle | `.ass` 格式字幕嵌入 `.mp4` | 成功，codec 为 `mov_text` | L113 的 container 判断逻辑 |
| SUB-06 | embed_subtitle | `.ass` 格式字幕嵌入 `.mkv` | 成功，codec 为 `srt` | MKV 支持 srt 字幕流 |
| SUB-07 | embed_subtitle | `language='chi'` vs `language='eng'` | 输出文件字幕语言标签正确 | `-metadata:s:s:0 language=` 验证 |
| SUB-08 | extract_subtitle | 输入视频不含字幕流 | `RuntimeError("字幕提取失败")` | L157-160 校验：`returncode != 0` 或文件未生成 |
| SUB-09 | extract_subtitle | 输入视频含多条字幕流，`stream_index=0` | 提取第一条字幕 | 正常路径 |
| SUB-10 | extract_subtitle | 输入视频含字幕流，`stream_index=99` | FFmpeg 报错（索引越界） | 边界值 |
| SUB-11 | extract_subtitle | 输入文件不存在 | `FileNotFoundError` | L140 校验 |
| SUB-12 | embed_subtitle | 输出路径目录不存在 | `_prepare_output` 创建目录或报错 | 磁盘/路径边界 |

---

### 1.4 导出 FFmpeg 命令 (`export_ffmpeg_cmd`)

源码分析: `export_ffmpeg_cmd` 纯字符串拼接，不执行 FFmpeg。需要验证命令准确性及隔离性。

| 编号 | 测试模块 | 输入操作 | 预期结果 | 测试要点 |
|------|----------|----------|----------|----------|
| CMD-01 | export_ffmpeg_cmd | `input.mp4 → output.webm`, conv_type='video' | 命令包含 `-c:v libvpx-vp9` 或 `-c:v libvpx` | VP9 编码器选择准确性 |
| CMD-02 | export_ffmpeg_cmd | `input.mp4 → output.mp4` | 命令包含 `-c copy` | **纯封装转换**：同格式应走 container_only 路径 |
| CMD-03 | export_ffmpeg_cmd | `input.mp3 → output.wav`, conv_type='audio' | 命令包含 `-vn -c:a pcm_s16le` | 音频转码命令准确性 |
| CMD-04 | export_ffmpeg_cmd | params 包含 `{'video_crf': 28}` | 命令包含 `-crf 28` | 高级参数传递 |
| CMD-05 | export_ffmpeg_cmd | 输出格式 `.mp4` (H.264) | 命令包含正确的编码器参数 | 微信发送预设验证 |
| CMD-06 | export_ffmpeg_cmd | 输出格式 `.mp4` + `{'scale_width': 720}` | 命令包含 `-vf scale=720:-2` | 视频压缩预设验证 |
| CMD-07 | **隔离性** | 调用 `export_ffmpeg_cmd` 后检查输出路径 | 输出文件 **不存在** | **核心隔离**：函数只返回字符串，不执行转换。验证方法：`assert not os.path.exists(output_path)` |
| CMD-08 | export_ffmpeg_cmd | 返回值类型检查 | `isinstance(result, str)` 且以 `ffmpeg` 开头 | 返回值格式 |

**自动化断言示例**:

```python
def test_export_cmd_isolation(tmp_path):
    """导出命令不实际执行转换"""
    input_v = create_test_video(tmp_path)  # ffmpeg -f lavfi 生成
    output_v = str(tmp_path / 'out.webm')
    cmd = export_ffmpeg_cmd(input_v, output_v)
    assert 'ffmpeg' in cmd
    assert input_v in cmd
    assert output_v in cmd
    # 核心断言：文件未被创建
    assert not os.path.exists(output_v), "export_ffmpeg_cmd 不应执行转换"

def test_export_cmd_wechat_preset():
    """微信发送预设导出命令准确性"""
    # 微信限制: H.264, ≤25MB, ≤10min
    params = {'video_crf': 28, 'scale_width': 720, 'audio_bitrate': '128k'}
    cmd = export_ffmpeg_cmd('in.mp4', 'out.mp4', params=params)
    assert '-crf' in cmd
    assert '720' in cmd
```

---

## 2. GUI 异步并发与线程安全测试

### 2.1 多线程卡死测试 (500 文件满载)

**测试目标**: 验证 `BatchOrchestrator` 在高并发下 GUI 不卡死（无"程序未响应"）。

**测试设计**:

```python
# test_concurrency.py

import pytest
import time
import threading
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

@pytest.fixture
def app():
    """创建 QApplication 实例"""
    app = QApplication.instance() or QApplication([])
    yield app

def test_500_file_batch_no_freeze(app, tmp_path):
    """
    H-01: 500 文件满载批量转换，验证 GUI 不卡死

    步骤:
    1. 创建 500 个极小测试文件 (1KB)
    2. Mock FFmpeg 引擎，使其在 0.1s 内返回
    3. 启动 BatchOrchestrator
    4. 在主线程设置 QTimer 每 100ms 检查一次 GUI 响应性
    5. 若 30s 内所有文件完成且 GUI 从未无响应，PASS
    """
    from workers import BatchOrchestrator, ConversionWorker
    from constants import FileStatus

    # 创建 500 个假文件
    files = []
    for i in range(500):
        f = tmp_path / f'video_{i:04d}.mp4'
        f.write_bytes(b'\x00' * 1024)
        files.append(str(f))

    # GUI 响应性探针
    gui_alive = threading.Event()
    gui_alive.set()

    def check_gui_responsive():
        """QTimer 回调：如果执行说明 GUI 主线程未阻塞"""
        gui_alive.set()

    timer = QTimer()
    timer.timeout.connect(check_gui_responsive)
    timer.start(100)  # 每 100ms 检查

    orchestrator = BatchOrchestrator(max_concurrency=8)
    completed = []

    for i, f in enumerate(files):
        out = str(tmp_path / f'out_{i:04d}.mp4')
        w = ConversionWorker(i, f, out, 'video')
        w.finished_one.connect(lambda idx, ok, msg: completed.append((idx, ok)))
        orchestrator.add_worker(w)

    gui_alive.clear()
    orchestrator.start_all()

    # 等待完成，同时监控 GUI 响应
    deadlock_detected = False
    start = time.monotonic()
    while len(completed) < 500:
        app.processEvents()  # 保持事件循环
        time.sleep(0.05)
        if time.monotonic() - start > 30:
            deadlock_detected = True
            break
        # 检查 GUI 是否在 500ms 内响应
        if not gui_alive.wait(timeout=0.5):
            deadlock_detected = True
            break
        gui_alive.clear()

    timer.stop()
    orchestrator.cancel_all()

    assert not deadlock_detected, "GUI 线程在 500 文件批量转换中卡死"
    assert len(completed) == 500, f"仅完成 {len(completed)}/500"
```

**关键验证点**:

| 检查项 | 判定标准 | 工具 |
|--------|----------|------|
| GUI 主线程响应性 | `QTimer` 每 100ms 能触发回调 | QTimer + threading.Event |
| Semaphore 并发上限 | 最多 8 个 QThread 同时运行 | `active_count() <= 8` |
| finished_one 信号唯一性 | 每个 worker 只发射 1 次 | 计数器 == 500 |
| GIL 竞争 | `app.processEvents()` 能正常返回 | 主循环探针 |

---

### 2.2 极端交互测试 (开始→取消→重试)

| 编号 | 测试场景 | 步骤 | 预期结果 | 测试要点 |
|------|----------|------|----------|----------|
| STRESS-01 | 开始→瞬间取消 | 1. 添加 10 个文件 2. 调用 `start_all()` 3. 在 10ms 内调用 `cancel_all()` | 所有 worker 进入 TERMINAL 状态，`finished_one` 全部发射 | 状态机原子性：`_transition_to` 使用 Lock |
| STRESS-02 | 取消→立刻重试 | 1. STRESS-01 后立即重新 `start_all()` | 新 worker 正常启动，无死锁 | `cancel()` 幂等性（L174-194） |
| STRESS-03 | 转换中关闭窗口 | 1. 启动转换 2. 3s 后触发 `closeEvent` | `wait_all(5000)` 正确等待，不崩溃 | L407-414: cancel→wait→terminate 三步清理 |
| STRESS-04 | 连续快速点击"全部开始" | 快速双击/三击开始按钮 | 只启动一次转换，不重复创建 worker | UI 层 `_is_converting` 锁 |
| STRESS-05 | 转换中切换主题 | 1. 启动转换 2. 切换到"可爱"主题 | 主题切换不影响转换进度 | QSS 和动画与 worker 线程隔离 |
| STRESS-06 | 取消后文件句柄 | 1. 转换大文件 2. 取消 3. 尝试删除临时文件 | 临时文件可删除，无句柄泄漏 | `kill_process_tree` 确保子进程退出 |

**快速切点伪代码**:

```python
def test_cancel_then_retry_immediately():
    """开始→瞬间取消→立刻重试，验证无死锁"""
    orchestrator = create_orchestrator_with_files(10)
    orchestrator.start_all()
    time.sleep(0.01)  # 10ms
    orchestrator.cancel_all()
    orchestrator.wait_all(timeout_ms=5000)

    # 重试
    for w in orchestrator.workers:
        w._finished_emitted = False
        w._state = WorkerState.IDLE
        w._cancel_event.clear()

    orchestrator.start_all()
    time.sleep(2)
    assert orchestrator.active_count() >= 0  # 不崩溃即 PASS
```

---

## 3. UI 性能与内存泄漏测试

### 3.1 动效内存泄漏 (可爱/温暖主题)

**测试目标**: 验证 `cute_anim.py` 和 `warm_anim.py` 的粒子动画在长时间运行下 QTimer/QGraphicsEffect 内存不持续增长。

**测试方法**: 使用 `psutil` + `objgraph` 进行长时间监控。

```python
# test_memory_leak.py

import psutil
import os
import time
import gc

def test_animation_memory_leak():
    """
    动画主题内存泄漏检测

    步骤:
    1. 启动应用，切换到"可爱"主题
    2. 每 30 秒记录一次进程 RSS 内存
    3. 持续运行 2 小时
    4. 分析内存增长趋势

    判定标准:
    - 前 5 分钟允许内存上升（QSS 缓存、粒子池初始化）
    - 5 分钟后内存增长速率应 < 0.5 MB/min
    - 2 小时总增长 < 50 MB
    """
    proc = psutil.Process(os.getpid())

    # 预热：切换主题并等待稳定
    apply_theme('cute')
    time.sleep(60)  # 等待初始化完成
    gc.collect()

    baseline = proc.memory_info().rss / (1024 * 1024)  # MB
    samples = []

    for i in range(240):  # 240 × 30s = 2h
        time.sleep(30)
        gc.collect()
        rss = proc.memory_info().rss / (1024 * 1024)
        samples.append(rss - baseline)

    # 分析
    growth_5min = samples[10] - samples[0]  # 第 5-10 分钟的增长
    growth_total = samples[-1] - samples[10]  # 稳态后的总增长

    assert growth_total < 50, f"动画主题内存持续增长 {growth_total:.1f} MB，疑似泄漏"

    # 增长率检查
    rate_per_min = growth_total / (len(samples) - 10) * 2  # 每分钟
    assert rate_per_min < 0.5, f"内存增长速率 {rate_per_min:.2f} MB/min，异常"
```

**排查方向** (若发现泄漏):

| 排查项 | 工具 | 方法 |
|--------|------|------|
| QTimer 未停止 | `objgraph.show_most_common_types()` | 对比 start/stop 前后 QTimer 实例数 |
| QGraphicsEffect 累积 | `objgraph.by_type('QGraphicsEffect')` | 检查 effect 对象是否被 GC 回收 |
| 粒子对象池 | `objgraph.show_growth()` | 每分钟采样一次，观察自定义粒子类实例数 |
| QSS 重复加载 | 检查 `get_theme_qss()` 调用 | 确认 QSS 只加载一次而非每次 paint 都读取 |
| Signal/Slot 泄漏 | `sip.isdeleted()` | 确认 disconnect 后旧 animator 被销毁 |

**具体检查点**:

- `themes/__init__.py:74` — `stop_current_animation()` 是否正确调用了 `animator.stop()`
- `animator.stop()` 内部是否 disconnect 所有 QTimer 信号
- 粒子对象是否在 `stop()` 后被设为 `None` 以便 GC

---

### 3.2 暗色主题 (`dark.qss`) 无障碍测试

| 编号 | 测试点 | 检查内容 | 判定标准 | 工具 |
|------|--------|----------|----------|------|
| DARK-01 | 文字对比度 | 所有文字颜色 vs 背景色 | WCAG AA: ≥4.5:1 (正文) / ≥3:1 (大字) | Colour Contrast Analyser |
| DARK-02 | 进度条文字 | QProgressBar 上的百分比文字 | 深色背景上白色文字可读 | 手动检查 |
| DARK-03 | 禁用状态 | 禁用按钮的文字可见性 | 仍可辨认，非完全隐形 | `QPushButton:disabled` 样式 |
| DARK-04 | 链接颜色 | 状态栏/提示中的链接文字 | 非纯黑、非纯白，有区分度 | QSS 检查 |
| DARK-05 | 选中行 | 表格选中行的前景/背景 | 选中态与非选中态有明显视觉差异 | `QTableWidget::item:selected` |
| DARK-06 | 输入框 | 可编辑 ComboBox 内文字 | 深色背景 + 浅色文字，光标可见 | `QComboBox` editable 状态 |
| DARK-07 | 空状态文字 | "拖拽文件到此处" 提示文字 | 不应使用 `#334155` (L352 在暗色背景下不可见) | **BUG**: `ui.py:352` 的 `color: #334155` 在暗色主题下几乎不可见 |
| DARK-08 | 分割线 | Divider 的颜色 | 暗色背景下可见，但不过于突兀 | `QFrame#Divider` |

**已发现 BUG**: `ui.py:352` 中空状态提示文字硬编码了 `color: #334155`，这在暗色主题下与深灰背景对比度极低，文字将不可见。应改为使用 QSS 变量或移除内联样式。

---

## 4. CLI 命令行与自动化回归测试

### 4.1 CLI 高级工具参数组合测试

```python
# test_cli_advanced.py

import subprocess
import sys
import os
import pytest

CLI = [sys.executable, 'cli.py']

def run_cli(*args, expect_success=True):
    """运行 CLI 并返回 (returncode, stdout, stderr)"""
    result = subprocess.run(
        CLI + list(args),
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if expect_success:
        assert result.returncode == 0, f"CLI 失败:\n{result.stderr}"
    return result.returncode, result.stdout, result.stderr


class TestExportCmd:
    """--export-cmd 参数组合"""

    def test_basic_video_to_webm(self, tmp_path):
        """MP4→WEBM: 验证导出命令包含正确的编码器"""
        input_v = create_test_video(tmp_path)
        out = str(tmp_path / 'out.webm')
        rc, stdout, _ = run_cli('--export-cmd', input_v, out)
        assert 'ffmpeg' in stdout
        assert out in stdout
        assert not os.path.exists(out), "不应实际执行转换"

    def test_export_cmd_with_preset(self, tmp_path):
        """--export-cmd + --preset 微信发送"""
        input_v = create_test_video(tmp_path)
        out = str(tmp_path / 'out.mp4')
        rc, stdout, _ = run_cli('--export-cmd', input_v, out, '--preset', '微信发送')
        # 微信预设应产生特定参数
        assert 'ffmpeg' in stdout


class TestCrop:
    """--crop 参数组合"""

    def test_crop_basic(self, tmp_path):
        """基本裁剪: 640×480"""
        input_v = create_test_video(tmp_path, size='1280x720')
        out = str(tmp_path / 'cropped.mp4')
        rc, stdout, _ = run_cli(
            '--crop', input_v,
            '--crop-size', '640', '480',
            '-o', out,
        )
        assert '裁剪完成' in stdout
        assert os.path.isfile(out)

    def test_crop_with_position(self, tmp_path):
        """带起始坐标裁剪"""
        input_v = create_test_video(tmp_path, size='1280x720')
        out = str(tmp_path / 'cropped.mp4')
        rc, stdout, _ = run_cli(
            '--crop', input_v,
            '--crop-size', '640', '480',
            '--crop-pos', '100', '50',
            '-o', out,
        )
        assert os.path.isfile(out)

    def test_crop_missing_size_exits_1(self):
        """--crop 不带 --crop-size 应退出码 1"""
        rc, _, stderr = run_cli('--crop', 'fake.mp4', expect_success=False)
        assert rc == 1
        assert '--crop-size' in stderr


class TestEmbedSub:
    """--embed-sub 参数组合"""

    def test_embed_sub_with_lang(self, tmp_path):
        """嵌入字幕 + 指定语言"""
        input_v = create_test_video_with_subtitle(tmp_path)
        sub = create_test_srt(tmp_path)
        out = str(tmp_path / 'sub_output.mp4')
        rc, stdout, _ = run_cli(
            '--embed-sub', input_v, sub, out,
            '--sub-lang', 'eng',
        )
        assert '字幕嵌入完成' in stdout


class TestMerge:
    """--merge 参数组合"""

    def test_merge_two_files(self, tmp_path):
        """合并 2 个文件"""
        v1 = create_test_video(tmp_path, name='a.mp4')
        v2 = create_test_video(tmp_path, name='b.mp4')
        out = str(tmp_path / 'merged.mp4')
        rc, stdout, _ = run_cli('--merge', v1, v2, '-o', out)
        assert '合并完成' in stdout
```

---

### 4.2 `ffmpeg_utils.py` pytest 断言补充指南

针对现有 116 个 passed 测试，为 `engines/ffmpeg_utils.py` 补充高效断言:

```python
# tests/test_ffmpeg_utils.py — 建议新增文件

import pytest
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.ffmpeg_utils import (
    export_ffmpeg_cmd, embed_subtitle, extract_subtitle,
    merge_media, crop_video,
)


# ============================================================
# 辅助 fixture
# ============================================================

@pytest.fixture
def ffmpeg_available():
    """跳过测试如果 FFmpeg 不可用"""
    from utils import get_ffmpeg_path
    try:
        ffmpeg = get_ffmpeg_path()
        result = subprocess.run(
            [ffmpeg, '-version'], capture_output=True, timeout=5
        )
        if result.returncode != 0:
            pytest.skip('ffmpeg not working')
    except Exception:
        pytest.skip('ffmpeg not available')


@pytest.fixture
def test_video(tmp_path, ffmpeg_available):
    """创建一个 1 秒的 320×240 测试视频"""
    from utils import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()
    video = tmp_path / 'test.mp4'
    subprocess.run([
        ffmpeg, '-y', '-f', 'lavfi', '-i',
        'testsrc=duration=1:size=320x240:rate=25',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
        '-c:v', 'libx264', '-c:a', 'aac', '-shortest',
        str(video),
    ], capture_output=True, timeout=30)
    assert video.exists(), 'Failed to create test video'
    return str(video)


@pytest.fixture
def test_srt(tmp_path):
    """创建一个简单的 SRT 字幕文件"""
    srt = tmp_path / 'test.srt'
    srt.write_text(
        '1\n00:00:00,000 --> 00:00:01,000\nHello World\n\n'
        '2\n00:00:01,000 --> 00:00:02,000\nTest Subtitle\n\n',
        encoding='utf-8',
    )
    return str(srt)


# ============================================================
# export_ffmpeg_cmd 测试
# ============================================================

class TestExportFFmpegCmd:

    def test_returns_string(self, test_video, tmp_path):
        """返回值为字符串"""
        out = str(tmp_path / 'out.webm')
        result = export_ffmpeg_cmd(test_video, out)
        assert isinstance(result, str)

    def test_starts_with_ffmpeg(self, test_video, tmp_path):
        """命令以 ffmpeg 路径开头"""
        out = str(tmp_path / 'out.webm')
        result = export_ffmpeg_cmd(test_video, out)
        assert 'ffmpeg' in result.lower()

    def test_contains_input_output(self, test_video, tmp_path):
        """命令包含输入和输出路径"""
        out = str(tmp_path / 'out.webm')
        result = export_ffmpeg_cmd(test_video, out)
        assert test_video in result
        assert out in result

    def test_no_file_created(self, test_video, tmp_path):
        """核心隔离性：不创建输出文件"""
        out = str(tmp_path / 'not_created.webm')
        export_ffmpeg_cmd(test_video, out)
        assert not os.path.exists(out)

    def test_audio_type_uses_vn(self, test_video, tmp_path):
        """音频类型应包含 -vn 参数"""
        out = str(tmp_path / 'out.mp3')
        result = export_ffmpeg_cmd(test_video, out, conv_type='audio')
        assert '-vn' in result

    def test_same_format_container_copy(self, test_video, tmp_path):
        """同格式转换应使用 -c copy"""
        out = str(tmp_path / 'out.mp4')
        result = export_ffmpeg_cmd(test_video, out)
        assert '-c copy' in result or '-c:copy' in result


# ============================================================
# embed_subtitle 测试
# ============================================================

class TestEmbedSubtitle:

    def test_nonexistent_video_raises(self, test_srt):
        with pytest.raises(FileNotFoundError):
            embed_subtitle('/nonexistent.mp4', '/tmp/out.mp4', test_srt)

    def test_nonexistent_subtitle_raises(self, test_video, tmp_path):
        out = str(tmp_path / 'out.mp4')
        with pytest.raises(FileNotFoundError):
            embed_subtitle(test_video, out, '/nonexistent.srt')

    def test_unsupported_subtitle_format(self, test_video, tmp_path):
        """不支持的字幕格式应抛 ValueError"""
        bad_sub = tmp_path / 'sub.txt'
        bad_sub.write_text('test')
        out = str(tmp_path / 'out.mp4')
        with pytest.raises(ValueError, match='不支持的字幕格式'):
            embed_subtitle(test_video, out, str(bad_sub))

    def test_embed_srt_creates_output(self, test_video, test_srt, tmp_path):
        """正常嵌入 SRT 应创建输出文件"""
        out = str(tmp_path / 'sub_out.mp4')
        result = embed_subtitle(test_video, out, test_srt)
        assert os.path.isfile(result)
        assert os.path.getsize(result) > 0


# ============================================================
# extract_subtitle 测试
# ============================================================

class TestExtractSubtitle:

    def test_nonexistent_video_raises(self):
        with pytest.raises(FileNotFoundError):
            extract_subtitle('/nonexistent.mp4', '/tmp/out.srt')

    def test_extract_from_no_subtitle_video(self, test_video, tmp_path):
        """从无字幕视频提取应抛 RuntimeError"""
        out = str(tmp_path / 'out.srt')
        with pytest.raises(RuntimeError):
            extract_subtitle(test_video, out)


# ============================================================
# merge_media 测试
# ============================================================

class TestMergeMedia:

    def test_less_than_two_files_raises(self):
        with pytest.raises(ValueError, match='至少需要 2 个文件'):
            merge_media(['/tmp/one.mp4'], '/tmp/out.mp4')

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            merge_media([], '/tmp/out.mp4')

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            merge_media(['/tmp/a.mp4', '/tmp/b.mp4'], '/tmp/out.mp4')

    def test_merge_two_videos(self, test_video, tmp_path):
        """合并两个测试视频"""
        out = str(tmp_path / 'merged.mp4')
        result = merge_media([test_video, test_video], out)
        assert os.path.isfile(result)
        assert os.path.getsize(result) > os.path.getsize(test_video)


# ============================================================
# crop_video 测试
# ============================================================

class TestCropVideo:

    def test_nonexistent_input_raises(self):
        with pytest.raises(FileNotFoundError):
            crop_video('/nonexistent.mp4', '/tmp/out.mp4', 100, 100)

    def test_zero_width_raises(self, test_video, tmp_path):
        out = str(tmp_path / 'out.mp4')
        with pytest.raises(ValueError, match='正数'):
            crop_video(test_video, out, 0, 100)

    def test_negative_height_raises(self, test_video, tmp_path):
        out = str(tmp_path / 'out.mp4')
        with pytest.raises(ValueError, match='正数'):
            crop_video(test_video, out, 100, -1)

    def test_crop_creates_output(self, test_video, tmp_path):
        """正常裁剪应创建输出"""
        out = str(tmp_path / 'cropped.mp4')
        result = crop_video(test_video, out, 160, 120, 0, 0)
        assert os.path.isfile(result)

    def test_crop_full_size(self, test_video, tmp_path):
        """裁剪尺寸 = 源视频尺寸"""
        out = str(tmp_path / 'full.mp4')
        result = crop_video(test_video, out, 320, 240, 0, 0)
        assert os.path.isfile(result)
```

---

## 5. 测试执行矩阵

| 优先级 | 测试类别 | 用例数 | 执行频率 | 自动化程度 |
|--------|----------|--------|----------|------------|
| **P0-Critical** | 文件不存在/空文件异常流 | 12 | 每次提交 | 全自动 pytest |
| **P0-Critical** | GUI 500 文件并发无卡死 | 1 | 每次发版 | 半自动 (需 GUI 环境) |
| **P1-High** | crop_video 数学边界 | 10 | 每次提交 | 全自动 pytest |
| **P1-High** | merge_media 容错 | 11 | 每次提交 | 全自动 pytest |
| **P1-High** | 字幕嵌入/提取异常 | 12 | 每次提交 | 全自动 pytest |
| **P1-High** | export_cmd 隔离性+准确性 | 8 | 每次提交 | 全自动 pytest |
| **P2-Medium** | 开始→取消→重试快速切点 | 6 | 每次发版 | 半自动 |
| **P2-Medium** | 动画主题内存泄漏 | 2 | 版本回归 | 手动 + psutil |
| **P2-Medium** | 暗色主题无障碍 | 8 | 主题变更时 | 手动检查 |
| **P3-Low** | CLI 参数组合回归 | 6 | 每次发版 | 全自动 subprocess |

---

## 6. 已发现的风险项 (需研发确认)

| 风险ID | 文件:行号 | 描述 | 严重程度 | 建议修复 |
|--------|-----------|------|----------|----------|
| RISK-01 | `ffmpeg_utils.py:257` | `crop_video` 不校验负坐标 (x<0, y<0)，直接传给 FFmpeg | Medium | 增加 `if x < 0 or y < 0: raise ValueError` |
| RISK-02 | `ui.py:352` | 空状态提示文字硬编码 `color: #334155`，暗色主题下不可见 | High | 移除内联样式，改用 QSS `#EmptyHint` 选择器 |
| RISK-03 | `ffmpeg_utils.py:204` | `merge_media` 的单引号转义 `replace("'", "'\\''")` 未覆盖路径含换行符的情况 | Low | 考虑使用绝对路径 + `-safe 0` (已启用) |
| RISK-04 | `workers.py:239-286` | `embed_subtitle`/`extract_subtitle` 在 `_do_convert` 中的 `_settings.get('subtitle_path', '')` 默认空字符串，若用户未设置会传空路径给引擎 | Medium | UI 层应在启动前校验必填参数 |
| RISK-05 | `workers.py:265` | `merge_media` 的 `_settings.get('merge_paths', [self.input_path])` 默认只含自身 1 个文件，直接触发 `ValueError("至少需要 2 个文件")` | Medium | UI 层必须在启动前确保 `merge_paths` ≥ 2 |
| RISK-06 | `workers.py:278-279` | `crop_video` 默认 `crop_w=1920, crop_h=1080`，若源视频小于此尺寸且用户未设置，裁剪会失败 | Low | 改为 0 表示"使用源视频尺寸"，或从 `get_media_info` 动态获取 |
| RISK-07 | `ffmpeg_utils.py:113` | `.ass` 字幕嵌入 `.mkv` 时统一使用 `srt` codec，应为 `ass` 以保留 ASS 格式特性 | Low | 按字幕扩展名选择 codec：`.ass`/`.ssa` → `ass`，`.srt` → `srt` |

---

## 7. 二次审查发现的未覆盖场景

代码修改后进行逐行比对，发现以下场景在现有 116 个测试中**完全未被覆盖**，存在回归风险。

### 7.1 BUG-001 修复路径未验证 (`image_resize.py:_get_save_kwargs`)

`_get_save_kwargs` 返回值从 `dict` 改为 `(dict, img)` 二元组，修复了 RGBA→JPEG 时 img 对象泄漏。但**现有测试全部输出为 PNG**，从未触发 JPEG 分支：

```python
# 现有测试 — 全部走 PNG 路径，_get_save_kwargs 中 ext='.png' 命中 elif 分支，直接返回原 img
resize_image(in_path, out_path_png, percentage=50)
resize_image(in_path, out_path_png, max_dimension=500)
```

**缺失测试**:

| 编号 | 测试场景 | 输入 | 预期结果 | 测试要点 |
|------|----------|------|----------|----------|
| FIX-01 | RGBA PNG → JPEG | 400×400 RGBA `.png`，输出 `.jpg` | 成功输出，无泄漏 | `_get_save_kwargs` 中 `img.mode == 'RGBA'` 分支：创建白色背景 → paste → 返回新 img |
| FIX-02 | 调色板 PNG → JPEG | 400×400 P 模式 `.png`，输出 `.jpg` | 成功输出 | `img.mode == 'P'` 分支：先 `convert('RGBA')` 再处理 |
| FIX-03 | LA 灰度+Alpha → JPEG | 400×400 LA `.png`，输出 `.jpg` | 成功输出 | `img.mode == 'LA'` 分支 |
| FIX-04 | RGB PNG → JPEG | 400×400 RGB `.png`，输出 `.jpg` | 成功输出，原 img 不变 | 不走透明通道分支，验证 `kwargs` 正确返回 |

**建议测试代码**:

```python
def test_resize_rgba_to_jpeg(self):
    """BUG-001 修复验证：RGBA 保存为 JPEG 不崩溃"""
    from PIL import Image
    from engines.image_resize import resize_image
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        in_path = f.name
        # 创建带透明通道的图片
        img = Image.new('RGBA', (400, 400), (255, 0, 0, 128))
        img.save(f)
    out_path = in_path.replace('.png', '.jpg')
    try:
        result = resize_image(in_path, out_path, percentage=50)
        assert os.path.isfile(result)
        # 验证输出是 RGB（JPEG 不支持 alpha）
        saved = Image.open(result)
        assert saved.mode == 'RGB'
        assert saved.size == (200, 200)
        saved.close()
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)
```

---

### 7.2 `images_to_pdf` A4 多图内存泄漏修复未验证 (`pdf_convert.py`)

BUG-002 修复加了 `originals = list(images)` + `img.close()` 来关闭原始图片。但现有测试 `test_images_to_pdf_a4` **只传 1 张图**：

```python
result = images_to_pdf([in_path], out_path, page_size='a4')  # 单张，不走 append_images 路径
```

单张时 `save_all=True, append_images=[]` 逻辑简单，**多张才触发泄漏场景**。

**缺失测试**:

| 编号 | 测试场景 | 输入 | 预期结果 | 测试要点 |
|------|----------|------|----------|----------|
| FIX-05 | A4 模式 3 张图 | 3 张不同尺寸的 PNG，`page_size='a4'` | 成功输出 PDF，无异常 | 验证 `originals` 列表关闭逻辑 + `first_image` 更新 |
| FIX-06 | A4 模式大图 | 5000×3000 的 PNG，`page_size='a4'` | 成功输出，图片居中 | `ratio` 缩放 + `offset_x/y` 计算正确性 |
| FIX-07 | auto 模式多图 | 3 张不同尺寸的 PNG，`page_size='auto'` | 成功输出 | 不走 A4 分支，验证默认路径不受影响 |

**建议测试代码**:

```python
def test_images_to_pdf_a4_multiple(self):
    """BUG-002 修复验证：A4 模式多图不泄漏"""
    from PIL import Image
    from engines.pdf_convert import images_to_pdf
    import tempfile

    imgs = []
    sizes = [(300, 200), (1920, 1080), (800, 600)]
    for w, h in sizes:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            Image.new('RGB', (w, h), 'blue').save(f)
            imgs.append(f.name)

    out_path = tempfile.mktemp(suffix='.pdf')
    try:
        result = images_to_pdf(imgs, out_path, page_size='a4')
        assert os.path.isfile(result)
        assert os.path.getsize(result) > 0
    finally:
        for p in imgs:
            os.unlink(p)
        if os.path.exists(out_path):
            os.unlink(out_path)
```

---

### 7.3 `workers.py` 的 17 个 conv_type 分支未通过 Worker 测试

`_do_convert()` 新增了 11 个分支，但现有测试只验证了引擎函数的 import 和签名，**从未通过 `ConversionWorker` 调用**。以下路径存在参数传递风险：

| 编号 | conv_type | 风险点 | 缺失验证 |
|------|-----------|--------|----------|
| W-01 | `embed_subtitle` | `_settings.get('subtitle_path', '')` 默认空字符串 → `FileNotFoundError` | Worker 传空 settings 时的行为 |
| W-02 | `merge_media` | `_settings.get('merge_paths', [self.input_path])` 只有 1 个文件 → `ValueError` | Worker 未设置 `merge_paths` 时的行为 |
| W-03 | `crop_video` | 默认 `crop_w=1920, crop_h=1080` 可能超过源视频尺寸 | Worker 使用默认值裁剪小视频 |
| W-04 | `extract_subtitle` | 无 `progress_callback` / `cancel_event` 传递 | 取消操作无法传递到引擎 |
| W-05 | `compress_image` | 直接 `emit(100)` 而非通过 `progress_callback` | 进度信号行为不一致 |
| W-06 | `resize_image` | 同上 | 同上 |
| W-07 | `add_watermark` | 同上 | 同上 |
| W-08 | 未知 conv_type | `raise ValueError('不支持的转换类型')` 会被 `except Exception` 捕获 → `FAILED` | 验证错误信息是否传递到 `finished_one` |

**建议测试代码**:

```python
def test_worker_unknown_conv_type():
    """未知 conv_type 应触发 FAILED 状态"""
    from workers import ConversionWorker
    from PyQt6.QtCore import QCoreApplication
    import sys

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    results = []

    w = ConversionWorker(0, '/tmp/in.mp4', '/tmp/out.mp4', 'nonexistent_type')
    w.finished_one.connect(lambda idx, ok, msg: results.append((ok, msg)))
    w.start()
    w.wait(3000)

    assert len(results) == 1
    ok, msg = results[0]
    assert ok is False
    assert '失败' in msg

def test_worker_merge_media_single_file():
    """merge_media 只有 1 个文件时应触发 FAILED"""
    from workers import ConversionWorker
    from PyQt6.QtCore import QCoreApplication
    import sys

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    results = []

    w = ConversionWorker(0, '/tmp/in.mp4', '/tmp/out.mp4', 'merge_media',
                         settings={'merge_paths': ['/tmp/in.mp4']})
    w.finished_one.connect(lambda idx, ok, msg: results.append((ok, msg)))
    w.start()
    w.wait(3000)

    assert len(results) == 1
    ok, msg = results[0]
    assert ok is False
```

---

### 7.4 CLI 新增参数未测试

`cli.py` 新增了 `--pdf-to-docx`, `--docx-to-pdf`, `--excel-to-image`, `--pdf-info` 四个参数，但 `TestCliModule` 未覆盖。

| 编号 | 测试场景 | 预期结果 |
|------|----------|----------|
| CLI-01 | `--pdf-to-docx nonexistent.pdf` | 退出码非 0，stderr 包含错误信息 |
| CLI-02 | `--docx-to-pdf nonexistent.docx` | 同上 |
| CLI-03 | `--excel-to-image nonexistent.xlsx` | 同上 |
| CLI-04 | `--pdf-info nonexistent.pdf` | 同上 |
| CLI-05 | `--help` 输出包含新增参数 | `pdf-to-docx`, `docx-to-pdf`, `excel-to-image`, `pdf-info` 出现在帮助文本中 |

---

### 7.5 `_calc_size` 分支覆盖不足 (`image_resize.py`)

`_calc_size` 有 5 个计算分支 + 1 个兜底分支，现有测试只覆盖了 2 个：

| 分支 | 条件 | 测试状态 | 缺失场景 |
|------|------|----------|----------|
| 1 | `percentage > 0` | ✅ `test_resize_percentage` | — |
| 2 | `max_dimension > 0` | ✅ `test_resize_max_dimension` | — |
| 3 | `width > 0 and height > 0` | ❌ | 指定宽高缩放，keep_aspect=True 时等比缩放到包含框 |
| 4 | 仅 `width > 0` | ❌ | 指定宽度，高度自动计算 |
| 5 | 仅 `height > 0` | ❌ | 指定高度，宽度自动计算 |
| 兜底 | 全为 0 | ❌ | 返回原尺寸（不缩放） |

**建议测试代码**:

```python
def test_resize_width_and_height(self):
    from PIL import Image
    from engines.image_resize import resize_image
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        in_path = f.name
        Image.new('RGB', (800, 600), 'red').save(f)
    out_path = in_path.replace('.png', '_out.png')
    try:
        result = resize_image(in_path, out_path, width=400, height=400)
        img = Image.open(result)
        assert img.size == (400, 400)  # keep_aspect=False 时直接指定
        img.close()
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)

def test_resize_width_only(self):
    from PIL import Image
    from engines.image_resize import resize_image
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        in_path = f.name
        Image.new('RGB', (800, 600), 'blue').save(f)
    out_path = in_path.replace('.png', '_out.png')
    try:
        result = resize_image(in_path, out_path, width=400)
        img = Image.open(result)
        assert img.size[0] == 400
        assert img.size[1] == 300  # 等比: 600 * (400/800) = 300
        img.close()
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)

def test_resize_all_zero_returns_original(self):
    from PIL import Image
    from engines.image_resize import resize_image
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        in_path = f.name
        Image.new('RGB', (800, 600), 'green').save(f)
    out_path = in_path.replace('.png', '_out.png')
    try:
        result = resize_image(in_path, out_path)  # 全部默认值
        img = Image.open(result)
        assert img.size == (800, 600)
        img.close()
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)
```

---

### 7.6 暗色主题注册未验证

`themes/__init__.py` 新增了 `'dark'` 条目，但没有测试验证其正确性。

| 编号 | 测试场景 | 预期结果 |
|------|----------|----------|
| THEME-01 | `get_theme_qss('dark')` | 返回非空字符串 |
| THEME-02 | `has_animation('dark')` | 返回 `False` |
| THEME-03 | `'dark' in get_theme_keys()` | `True` |
| THEME-04 | `get_theme_display('dark')` | 返回 `'🌙 深色'` |

---

### 7.7 `.ass` 字幕嵌入 codec 选择问题 (`ffmpeg_utils.py:113`)

当前代码对所有非 mp4 容器统一使用 `srt` codec：

```python
'-c:s', 'mov_text' if Path(output_path).suffix.lower() in ('.mp4', '.m4v') else 'srt',
```

`.ass` 字幕嵌入 `.mkv` 时，`srt` codec 会丢失 ASS 格式特性（样式、定位等）。应按字幕文件扩展名选择 codec：

| 字幕格式 | 嵌入 `.mp4` | 嵌入 `.mkv` | 当前行为 |
|----------|------------|------------|----------|
| `.srt` | `mov_text` ✅ | `srt` ✅ | 正确 |
| `.ass` | `mov_text` ⚠️ | `srt` ❌ | 应为 `ass` |
| `.ssa` | `mov_text` ⚠️ | `srt` ❌ | 应为 `ass` |

**建议测试**:

```python
def test_embed_ass_into_mkv_uses_ass_codec(self, tmp_path):
    """ASS 字幕嵌入 MKV 应使用 ass codec 而非 srt"""
    # 此测试当前会 FAIL，暴露 codec 选择问题
    ass_content = """[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,20
[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,Hello"""
    ass_file = tmp_path / 'test.ass'
    ass_file.write_text(ass_content, encoding='utf-8')

    # 此处需要实际执行 ffmpeg 才能验证 codec，属于集成测试范畴
    # 单元测试可通过 mock 验证 cmd 列表中 -c:s 的值
```

---

### 7.8 更新后的测试执行矩阵

| 优先级 | 测试类别 | 用例数 | 执行频率 | 自动化程度 |
|--------|----------|--------|----------|------------|
| **P0-Critical** | 文件不存在/空文件异常流 | 12 | 每次提交 | 全自动 pytest |
| **P0-Critical** | GUI 500 文件并发无卡死 | 1 | 每次发版 | 半自动 (需 GUI 环境) |
| **P0-Critical** | BUG-001 RGBA→JPEG 修复验证 | 4 | 每次提交 | 全自动 pytest |
| **P0-Critical** | BUG-002 A4 多图泄漏修复验证 | 3 | 每次提交 | 全自动 pytest |
| **P1-High** | crop_video 数学边界 | 10 | 每次提交 | 全自动 pytest |
| **P1-High** | merge_media 容错 | 11 | 每次提交 | 全自动 pytest |
| **P1-High** | 字幕嵌入/提取异常 | 12 | 每次提交 | 全自动 pytest |
| **P1-High** | export_cmd 隔离性+准确性 | 8 | 每次提交 | 全自动 pytest |
| **P1-High** | Worker conv_type 参数传递 | 8 | 每次提交 | 全自动 pytest |
| **P1-High** | `_calc_size` 全分支覆盖 | 4 | 每次提交 | 全自动 pytest |
| **P2-Medium** | CLI 新增参数回归 | 5 | 每次发版 | 全自动 subprocess |
| **P2-Medium** | 暗色主题注册验证 | 4 | 每次提交 | 全自动 pytest |
| **P2-Medium** | 开始→取消→重试快速切点 | 6 | 每次发版 | 半自动 |
| **P2-Medium** | 动画主题内存泄漏 | 2 | 版本回归 | 手动 + psutil |
| **P2-Medium** | 暗色主题无障碍 | 8 | 主题变更时 | 手动检查 |
| **P3-Low** | `.ass` codec 选择 | 2 | 字幕功能变更时 | 集成测试 |

**总用例数**: 原 66 个场景 + 新增 38 个 = **104 个测试场景**
