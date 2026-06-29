<p align="center">
  <h1 align="center">✨ 流光</h1>
  <p align="center">格式流转，光影随行 — 一站式多媒体格式转换工具</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" />
  <img src="https://img.shields.io/badge/PyQt6-6.5+-green?logo=qt" />
  <img src="https://img.shields.io/badge/FFmpeg-6.0+-red?logo=ffmpeg" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" />
  <img src="https://img.shields.io/badge/Version-1.2.0-brightgreen" />
</p>

---

## 📖 简介

**流光** 是一款基于 PyQt6 的桌面格式转换工具，支持视频、音频、图片、文档、表格等 30+ 格式的互转。内置 FFmpeg 和 Pillow 引擎，提供高质量转换、批量处理、实时预览、GPU 硬件加速、主题切换等功能。

## 📥 下载安装

### 方式一：便携版（推荐 · 解压即用）

1. 下载 `流光-Portable-v1.2.0.zip`
2. 解压到任意目录
3. 双击 `流光.exe` 即可运行，无需安装

**目录结构：**
```
流光-Portable-v1.2.0/
├── 流光.exe          主程序（含所有 Python 依赖）
├── bin/
│   └── ffmpeg.exe    视频/音频转换引擎（已内置）
├── icon.ico          程序图标
└── 使用说明.txt
```

**系统要求：** Windows 10/11 64 位，无需安装 Python 或任何运行时。

### 方式二：安装版（开始菜单 + 卸载支持）

1. 下载 `流光-Setup-v1.2.0.exe`
2. 双击运行安装程序
3. 按向导完成安装（可选创建桌面快捷方式、关联文件类型）
4. 从开始菜单或桌面启动「流光」

**安装版特性：**
- 自动注册开始菜单快捷方式
- 可选桌面快捷方式
- 可选关联视频/音频/图片文件类型
- 控制面板可卸载

### 方式三：从源码运行

```bash
# 克隆仓库
git clone https://github.com/CHEN-DIAN94/All-round-Conversion-Tool.git
cd All-round-Conversion-Tool

# 安装依赖
pip install -e .

# 运行 GUI
python main.py

# 运行 CLI
python cli.py --help
```

**前置要求：**
- Python 3.10+
- FFmpeg 6.0+（放入 `bin/` 目录或加入 PATH）
- Poppler（PDF 转图片需要，[下载地址](https://github.com/osber/poppler-windows/releases)）

---

## ✨ 核心功能

### 🔄 格式转换
| 类别 | 支持格式 |
|------|----------|
| **视频** | MP4, AVI, MKV, MOV, WMV, WEBM, FLV, GIF |
| **音频** | MP3, WAV, FLAC, AAC, OGG, WMA, M4A |
| **图片** | JPG, PNG, BMP, GIF, TIFF, WEBP, ICO, HEIC |
| **文档** | PDF ↔ DOCX |
| **表格** | Excel → PNG/JPG |

### 🛠 实用工具
- **视频压缩** — CRF / 目标大小 / 分辨率缩放
- **视频转 GIF** — 两步法调色板，帧率/尺寸/颜色数可调
- **图片压缩** — 固定质量或目标文件大小
- **图片缩放** — 像素 / 百分比 / 最大边长
- **图片水印** — 文字/图片水印，5 个位置可选
- **PDF 合并/拆分** — 按页数或范围拆分
- **PDF ↔ 图片** — PDF 每页导出 / 图片合并为 PDF
- **音频提取** — 从视频提取音轨
- **媒体裁剪** — 按时间范围裁剪视频/音频
- **视频画面裁剪** — 按尺寸/位置裁剪画面区域
- **音视频合并** — 多个音视频文件合并为一个
- **字幕嵌入/提取** — 外挂字幕嵌入视频 / 从视频提取字幕
- **导出 FFmpeg 命令** — 生成命令不执行，方便调试和脚本化
- **媒体信息** — 查看详细编码/码率/分辨率信息

### ⚡ GPU 硬件加速
- 自动检测 NVIDIA NVENC / Intel QSV / AMD AMF
- 智能并发会话管理（消费级显卡会话数限制）
- 满载时自动回退软编码，稳定不崩溃
- 编码器/解码器自动选择最优方案

### 🆕 v1.2.0 新增功能

- **📂 文件夹批量添加** — 选择文件夹递归收集所有受支持的文件，按当前类别自动过滤（快捷键 `Ctrl+Shift+O`）
- **👁 输出文件名实时预览** — 命名模板输入框旁实时显示最终文件名样例，所见即所得
- **✅ 转换完成后操作** — 一键设置转换完成后自动「打开输出目录 / 删除原文件 / 关机」
- **🔍 FFmpeg 可用性检测** — 启动时检测 FFmpeg，不可用时转换按钮禁用并友好提示
- **💾 磁盘空间检查** — 转换前检查输出目录剩余空间，<100MB 时警告
- **🔒 单实例运行** — 防止多开，第二次启动会自动激活已有窗口并提到前台

### 🎨 主题系统
6 款精心设计的主题，含 2 个动画主题：

| 主题 | 风格 | 动画 |
|------|------|------|
| 🌌 星空 | 深蓝紫渐变 | — |
| 🌃 赛博朋克 | 青蓝/品红霓虹 | — |
| ⬜ 极简白 | 纯白 macOS 风 | — |
| 💖 可爱 | 粉紫渐变 | 心形粒子 + 呼吸光晕 |
| 🔥 温暖 | 琥珀暖橙 | 萤火虫粒子 + 温暖光晕 |
| 🌑 暗色 | 深色护眼 | — |

### 📋 其他功能
- **转换预设** — 内置「微信发送」「剪辑存档」「网页上传」预设
- **文件预览** — 选中文件即时预览（图片直接显示，视频提取封面）
- **批量处理** — 拖拽添加，最多 500 个文件同时转换
- **实时进度** — 每文件进度条 + 总体进度 + ETA 预估
- **失败重试** — 一键重试所有失败文件
- **转换历史** — 记录每次转换，支持搜索和导出
- **CLI 模式** — 命令行批量处理，可脚本化

---

## 💻 CLI 用法

```bash
# 列出预设和格式
python cli.py --list-presets
python cli.py --list-formats

# 格式转换
python cli.py input.mp4 -f webm
python cli.py input.mp4 -f gif --preset 微信发送

# 视频压缩
python cli.py --compress-video input.mp4 --video-crf 28

# 视频转 GIF
python cli.py --video-to-gif input.mp4 --gif-fps 15 --gif-width 320

# 图片处理
python cli.py --compress input.jpg --target-size 200
python cli.py --resize input.jpg --resize-width 800
python cli.py --watermark input.jpg "© 2026" -o output.jpg

# PDF 工具
python cli.py --merge-pdf a.pdf b.pdf -o merged.pdf
python cli.py --split-pdf input.pdf --pages-per-file 5 -o output_dir
python cli.py --pdf-to-images input.pdf -o output_dir
python cli.py --images-to-pdf a.jpg b.jpg -o output.pdf

# 媒体工具
python cli.py --extract-audio input.mp4 --audio-format flac
python cli.py --trim input.mp4 00:01:00 00:02:30 -o trimmed.mp4
python cli.py --info input.mp4

# FFmpeg 高级工具
python cli.py --export-cmd input.mp4 output.webm         # 导出 ffmpeg 命令（不执行）
python cli.py --embed-sub input.mp4 sub.srt output.mp4    # 嵌入字幕
python cli.py --embed-sub input.mp4 sub.srt output.mp4 --sub-lang eng  # 指定语言
python cli.py --extract-sub input.mp4 output.srt          # 提取字幕
python cli.py --merge a.mp4 b.mp4 c.mp4 -o merged.mp4    # 合并音视频
python cli.py --crop input.mp4 --crop-size 640 480 --crop-pos 100 50  # 裁剪画面
```

---

## ⌨️ 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+O` | 添加文件 |
| `Ctrl+Shift+O` | 添加文件夹 |
| `Delete` | 移除选中文件 |
| `Ctrl+A` | 全选文件 |
| `Ctrl+Enter` | 开始转换 |
| `Esc` | 取消转换 |
| `Ctrl+E` | 导出 FFmpeg 命令 |
| `F5` | 刷新文件列表 |

---

## 📦 自行打包

### 一键发布脚本（推荐）

```powershell
# 自动完成：PyInstaller 打包 → ZIP 便携版 → Inno Setup 安装程序
powershell -ExecutionPolicy Bypass -File build_release.ps1
```

产物位置：
- `dist\流光.exe` — 主程序
- `dist\流光-Portable-v1.2.0.zip` — 便携版
- `Output\流光-Setup-v1.2.0.exe` — 安装版（需 Inno Setup）

### 仅打包 PyInstaller exe

```bash
# 准备：将 ffmpeg.exe 放入 bin/ 目录
venv\Scripts\python.exe -m PyInstaller 流光.spec --noconfirm
# 产物：dist\流光.exe
```

### 仅生成 Inno Setup 安装程序

1. 下载安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)
2. 命令行编译：
   ```bash
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" 流光-installer.iss
   ```
3. 产物：`Output\流光-Setup-v1.2.0.exe`

---

## 📁 项目结构

```
流光/
├── main.py                  # GUI 入口（含崩溃日志 / Windows dump / 监控启动）
├── cli.py                   # CLI 入口
├── ui.py                    # 主窗口（Mixin 组合 + 单实例锁）
├── ui_file_table.py         # 文件表格管理 Mixin（含文件夹添加）
├── ui_conversion.py         # 转换控制 Mixin（含 FFmpeg 检测 / 磁盘空间检查 / 转换后操作）
├── ui_settings.py           # 设置/主题/布局 Mixin（含文件名预览）
├── widgets.py               # 自定义组件（表格/预览/设置面板）
├── formats.py               # 格式定义与映射
├── utils.py                 # 工具函数（subprocess 封装 + 磁盘空间检查）
├── workers.py               # 工作线程（QThread + BatchOrchestrator）
├── constants.py             # 全局常量 + FileStatus
├── monitor.py               # 运行时监控（Qt 崩溃信号重定向 / faulthandler）
├── history.py               # 转换历史（JSON 持久化）
├── presets.py               # 转换预设管理
├── logging_config.py        # 全局日志配置（按日轮转）
├── build_release.ps1        # 一键发布打包脚本
├── 流光.spec                # PyInstaller 打包配置
├── 流光-installer.iss       # Inno Setup 安装程序脚本
├── engines/
│   ├── ffmpeg_core.py       # 视频/音频转换 + 进度监控
│   ├── image_engine.py      # 图片格式转换
│   ├── document_engine.py   # PDF ↔ DOCX
│   ├── gif_engine.py        # 视频转 GIF（两步法调色板）
│   ├── video_compress.py    # 视频压缩
│   ├── compress_engine.py   # 图片压缩
│   ├── image_resize.py      # 图片缩放
│   ├── watermark_engine.py  # 文字/图片水印
│   ├── pdf_tools.py         # PDF 合并/拆分
│   ├── pdf_convert.py       # PDF ↔ 图片
│   ├── gpu_scheduler.py     # GPU 硬件加速智能调度
│   └── ...
├── themes/                  # 6 款主题（含动画）
└── tests/                   # 单元测试
```

---

## 🧪 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_format_handlers.py -v

# 生成覆盖率报告
python -m pytest tests/ --cov=. --cov-report=html
```

---

## 🔧 内部架构亮点

| 模块 | 说明 |
|------|------|
| **单实例锁** (`ui.py`) | 基于 `QLocalServer` / `QLocalSocket` 实现进程间通信，第二个实例启动时自动激活已有窗口并提到前台 |
| **FFmpeg 检测** (`ui_conversion.py`) | 启动时检测 FFmpeg 可用性并设置标志，转换前校验，避免转换中途失败 |
| **磁盘空间检查** (`utils.py`) | 转换前调用 `shutil.disk_usage` 检查输出目录剩余空间，<100MB 时警告 |
| **任务派发注册表** (`execution_registry.py`) | 集中定义 task key → 执行器映射，替代大型 if/elif 链 |
| **强类型任务模型** (`task_models.py`) | `TaskSpec` / `ExecutionResult` dataclass，提升可维护性 |
| **GPU 智能调度** (`gpu_scheduler.py`) | 自动检测 GPU 类型，管理并发会话限制，满载自动回退软编码 |
| **运行时监控** (`monitor.py`) | 重定向 Qt 消息到日志、追踪 QThread 异常、faulthandler 段错误捕获 |
| **统一日志框架** (`logging_config.py`) | 按日滚动日志文件，控制台 + 文件双 handler |
| **UI Mixin 架构** | `ui.py` 组合 3 个 Mixin，职责清晰 |

---

## 📝 更新日志

### v1.2.0（2026-06-29）
- 🆕 文件夹批量添加（递归收集 + 类别过滤）
- 🆕 输出文件名实时预览
- 🆕 转换完成后操作（打开目录/删除原文件/关机）
- 🆕 FFmpeg 可用性检测 + 磁盘空间检查
- 🆕 单实例运行（防多开 + 自动激活已有窗口）
- 🆕 一键发布打包脚本 `build_release.ps1`
- 🆕 Inno Setup 安装程序脚本 `流光-installer.iss`
- 🛠 修复 UI 控件被压缩成细线的问题
- 🛠 修复高级设置展开后挤压主界面的问题（改为弹窗）

### v1.1.0
- GPU 硬件加速（NVENC/QSV/AMF 自动检测）
- 运行时监控系统
- 6 款主题（含 2 个动画主题）
- 转换历史记录 + 失败重试
- CLI 命令行模式

### v1.0.0
- 首个正式版本
- 视频/音频/图片/文档/表格格式转换
- 批量处理 + 实时进度
- 实用工具集（压缩/转GIF/水印/PDF工具等）

---

<p align="center">
  <sub>流光 v1.2.0 — 格式流转，光影随行</sub>
</p>
