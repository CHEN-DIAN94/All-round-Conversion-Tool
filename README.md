<p align="center">
  <h1 align="center">✨ 流光</h1>
  <p align="center">格式流转，光影随行 — 一站式多媒体格式转换工具</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" />
  <img src="https://img.shields.io/badge/PyQt6-6.5+-green?logo=qt" />
  <img src="https://img.shields.io/badge/FFmpeg-6.0+-red?logo=ffmpeg" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" />
  <img src="https://img.shields.io/badge/Tests-108%20passed-brightgreen" />
</p>

---

## 📖 简介

**流光** 是一款基于 PyQt6 的桌面格式转换工具，支持视频、音频、图片、文档、表格等 30+ 格式的互转。内置 FFmpeg 和 Pillow 引擎，提供高质量转换、批量处理、实时预览、主题切换等功能。

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
- **媒体信息** — 查看详细编码/码率/分辨率信息

### 🎨 主题系统
5 款精心设计的主题，含 2 个动画主题：

| 主题 | 风格 | 动画 |
|------|------|------|
| 🌌 星空 | 深蓝紫渐变 | — |
| 🌃 赛博朋克 | 青蓝/品红霓虹 | — |
| ⬜ 极简白 | 纯白 macOS 风 | — |
| 💖 可爱 | 粉紫渐变 | 心形粒子 + 呼吸光晕 |
| 🔥 温暖 | 琥珀暖橙 | 萤火虫粒子 + 温暖光晕 |

### 📋 其他功能
- **转换预设** — 内置「微信发送」「剪辑存档」「网页上传」预设
- **文件预览** — 选中文件即时预览（图片直接显示，视频提取封面）
- **批量处理** — 拖拽添加，最多 500 个文件同时转换
- **实时进度** — 每文件进度条 + 总体进度 + ETA 预估
- **失败重试** — 一键重试所有失败文件
- **转换历史** — 记录每次转换，支持搜索和导出
- **CLI 模式** — 命令行批量处理，可脚本化

## 🚀 快速开始

### 方式一：直接运行 exe
下载 `流光.exe`，双击运行。

### 方式二：从源码运行
```bash
# 克隆仓库
git clone https://github.com/CHEN-DIAN94/All-round-Conversion-Tool.git
cd All-round-Conversion-Tool

# 安装依赖
pip install -e ".[dev]"

# 运行 GUI
python main.py

# 运行 CLI
python cli.py --help
```

### 前置要求
- Python 3.10+
- FFmpeg（视频/音频转换需要，放入 `bin/` 目录或添加到 PATH）
- Poppler（PDF 转图片需要，[下载地址](https://github.com/osber/poppler-windows/releases)）

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
```

## 📁 项目结构

```
流光/
├── main.py              # GUI 入口
├── cli.py               # CLI 入口
├── ui.py                # 主窗口
├── widgets.py           # 自定义组件（表格/预览/设置面板）
├── formats.py           # 格式定义与映射
├── utils.py             # 工具函数
├── workers.py           # 工作线程（QThread）
├── constants.py         # 全局常量
├── presets.py           # 转换预设
├── history.py           # 转换历史
├── logging_config.py    # 日志配置
├── engines/
│   ├── ffmpeg_core.py   # 视频/音频转换
│   ├── image_engine.py  # 图片转换
│   ├── document_engine.py # 文档转换
│   ├── excel_engine.py  # 表格转图片
│   ├── gif_engine.py    # 视频转 GIF
│   ├── video_compress.py # 视频压缩
│   ├── compress_engine.py # 图片压缩
│   ├── image_resize.py  # 图片缩放
│   ├── watermark_engine.py # 图片水印
│   ├── pdf_tools.py     # PDF 合并/拆分
│   ├── pdf_convert.py   # PDF ↔ 图片
│   ├── format_handlers.py # 格式特殊处理
│   ├── codec_compat.py  # 编码兼容性矩阵
│   └── _common.py       # 共享工具
├── themes/
│   ├── __init__.py      # 主题注册表
│   ├── starfield.qss    # 🌌 星空
│   ├── cyberpunk.qss    # 🌃 赛博朋克
│   ├── minimal.qss      # ⬜ 极简白
│   ├── cute.qss         # 💖 可爱（动画）
│   ├── cute_anim.py
│   ├── warm.qss         # 🔥 温暖（动画）
│   └── warm_anim.py
└── tests/
    ├── test_codec_compat.py
    ├── test_format_handlers.py
    ├── test_media_utils.py
    ├── test_presets.py
    ├── test_new_engines.py
    └── test_new_features.py
```

## 🧪 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_format_handlers.py -v
```

## 📦 打包

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包为 exe
pyinstaller 流光.spec --distpath . --noconfirm
```

---

<p align="center">
  <sub>流光 — 格式流转，光影随行</sub>
</p>
