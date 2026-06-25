"""
cli.py — 命令行接口

支持通过命令行进行批量转换，可脚本化调用。
用法: python cli.py input.mp4 -o output.webm --preset 微信发送
"""

import argparse
import os
import sys
from pathlib import Path

# 确保项目路径在 sys.path 中
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)


def main():
    parser = argparse.ArgumentParser(
        prog='converter',
        description='流光 — 命令行模式',
    )
    parser.add_argument('input', nargs='*', help='输入文件路径（支持多个）')
    parser.add_argument('-o', '--output', help='输出路径（单文件）或输出目录（多文件）')
    parser.add_argument('-f', '--format', help='输出格式（如 mp4, jpg, pdf）')
    parser.add_argument('-p', '--preset', help='使用预设（如 微信发送, 剪辑存档, 网页上传）')
    parser.add_argument('--list-presets', action='store_true', help='列出所有预设')
    parser.add_argument('--list-formats', action='store_true', help='列出支持的格式')
    parser.add_argument('--info', help='显示媒体文件信息')
    parser.add_argument('--extract-audio', help='从视频提取音频（输入视频路径）')
    parser.add_argument('--audio-format', default='mp3', help='提取音频的格式（默认 mp3）')
    parser.add_argument('--trim', nargs=3, metavar=('INPUT', 'START', 'END'),
                        help='裁剪媒体（INPUT START END，如 video.mp4 00:01:00 00:02:00）')
    parser.add_argument('--merge-pdf', nargs='+', help='合并多个 PDF')
    parser.add_argument('--split-pdf', help='拆分 PDF（输入路径）')
    parser.add_argument('--pages-per-file', type=int, default=1, help='拆分时每个文件的页数')
    parser.add_argument('--watermark', nargs=2, metavar=('INPUT', 'TEXT'),
                        help='给图片添加文字水印')
    parser.add_argument('--compress', help='压缩图片（输入路径）')
    parser.add_argument('--quality', type=int, default=80, help='压缩质量（1-100）')
    parser.add_argument('--target-size', type=int, help='目标文件大小（KB）')
    parser.add_argument('--compress-video', help='压缩视频（输入路径）')
    parser.add_argument('--video-crf', type=int, default=28, help='视频压缩 CRF（0-51，默认 28）')
    parser.add_argument('--video-width', type=int, help='视频缩放宽度（如 1280, 720）')
    parser.add_argument('--resize', help='缩放图片（输入路径）')
    parser.add_argument('--resize-width', type=int, help='目标宽度（像素）')
    parser.add_argument('--resize-height', type=int, help='目标高度（像素）')
    parser.add_argument('--resize-percent', type=float, help='缩放百分比（如 50）')
    parser.add_argument('--pdf-to-images', help='PDF 转图片（输入路径）')
    parser.add_argument('--pdf-dpi', type=int, default=200, help='PDF 转图片 DPI（默认 200）')
    parser.add_argument('--images-to-pdf', nargs='+', help='图片转 PDF（输入路径列表）')
    parser.add_argument('--video-to-gif', help='视频转 GIF（输入路径）')
    parser.add_argument('--gif-fps', type=int, default=12, help='GIF 帧率（默认 12）')
    parser.add_argument('--gif-width', type=int, default=480, help='GIF 宽度（默认 480）')
    parser.add_argument('--gif-colors', type=int, default=256, help='GIF 颜色数（1-256，默认 256）')
    parser.add_argument('--export-cmd', nargs=2, metavar=('INPUT', 'OUTPUT'),
                        help='导出 ffmpeg 命令（不执行）')
    parser.add_argument('--embed-sub', nargs=3, metavar=('VIDEO', 'SUBTITLE', 'OUTPUT'),
                        help='嵌入字幕到视频')
    parser.add_argument('--sub-lang', default='chi', help='字幕语言代码（默认 chi）')
    parser.add_argument('--extract-sub', nargs=2, metavar=('VIDEO', 'OUTPUT'),
                        help='从视频提取字幕')
    parser.add_argument('--merge', nargs='+', help='合并多个音视频文件')
    parser.add_argument('--crop', help='裁剪视频画面（输入路径）')
    parser.add_argument('--crop-size', nargs=2, type=int, metavar=('WIDTH', 'HEIGHT'),
                        help='裁剪尺寸')
    parser.add_argument('--crop-pos', nargs=2, type=int, default=[0, 0], metavar=('X', 'Y'),
                        help='裁剪起始位置（默认 0,0）')
    parser.add_argument('-v', '--verbose', action='store_true', help='详细输出')
    parser.add_argument('--version', action='version', version='流光 v1.1.0')

    args = parser.parse_args()

    # 列出预设
    if args.list_presets:
        from presets import PresetManager
        pm = PresetManager()
        for name, data in pm.list_presets().items():
            desc = data.get('description', '')
            print(f'  {name}: {desc}')
        return

    # 列出格式
    if args.list_formats:
        from formats import FORMAT_CATEGORIES
        for cat_key, title, items in FORMAT_CATEGORIES:
            print(f'\n{title}:')
            for label, ext, desc in items:
                print(f'  {ext:8s} {desc}')
        return

    # 媒体信息
    if args.info:
        from engines import get_media_info
        info = get_media_info(args.info)
        for k, v in info.items():
            print(f'  {k}: {v}')
        return

    # 提取音频
    if args.extract_audio:
        from engines import extract_audio
        output = args.output or _change_ext(args.extract_audio, f'.{args.audio_format}')
        result = extract_audio(args.extract_audio, output, format=args.audio_format)
        print(f'✅ 音频已提取: {result}')
        return

    # 裁剪
    if args.trim:
        from engines import trim_media
        inp, start, end = args.trim
        output = args.output or _add_suffix(inp, '_trimmed')
        result = trim_media(inp, output, start, end)
        print(f'✅ 裁剪完成: {result}')
        return

    # 合并 PDF
    if args.merge_pdf:
        from engines.pdf_tools import merge_pdfs
        output = args.output or 'merged.pdf'
        result = merge_pdfs(args.merge_pdf, output)
        print(f'✅ PDF 合并完成: {result}')
        return

    # 拆分 PDF
    if args.split_pdf:
        from engines.pdf_tools import split_pdf
        output_dir = args.output or 'split_output'
        results = split_pdf(args.split_pdf, output_dir, args.pages_per_file)
        print(f'✅ PDF 拆分完成: {len(results)} 个文件')
        for r in results:
            print(f'  {r}')
        return

    # 水印
    if args.watermark:
        from engines.watermark_engine import add_watermark
        inp, text = args.watermark
        output = args.output or _add_suffix(inp, '_wm')
        result = add_watermark(inp, output, text=text)
        print(f'✅ 水印已添加: {result}')
        return

    # 压缩
    if args.compress:
        from engines.compress_engine import compress_image
        output = args.output or _add_suffix(args.compress, '_compressed')
        result = compress_image(
            args.compress, output,
            target_size_kb=args.target_size or 0,
            quality=args.quality,
        )
        size_before = os.path.getsize(args.compress) / 1024
        size_after = os.path.getsize(result) / 1024
        ratio = (1 - size_after / size_before) * 100 if size_before > 0 else 0
        print(f'✅ 压缩完成: {result}')
        print(f'  {size_before:.0f} KB → {size_after:.0f} KB (减少 {ratio:.1f}%)')
        return

    # 视频压缩
    if args.compress_video:
        from engines.video_compress import compress_video
        output = args.output or _add_suffix(args.compress_video, '_compressed')
        result = compress_video(
            args.compress_video, output,
            crf=args.video_crf, scale_width=args.video_width or 0,
        )
        size_before = os.path.getsize(args.compress_video) / (1024*1024)
        size_after = os.path.getsize(result) / (1024*1024)
        ratio = (1 - size_after / size_before) * 100 if size_before > 0 else 0
        print(f'✅ 视频压缩完成: {result}')
        print(f'  {size_before:.1f} MB → {size_after:.1f} MB (减少 {ratio:.1f}%)')
        return

    # 图片缩放
    if args.resize:
        from engines.image_resize import resize_image
        output = args.output or _add_suffix(args.resize, '_resized')
        result = resize_image(
            args.resize, output,
            width=args.resize_width or 0,
            height=args.resize_height or 0,
            percentage=args.resize_percent or 0,
        )
        print(f'✅ 图片缩放完成: {result}')
        return

    # PDF 转图片
    if args.pdf_to_images:
        from engines.pdf_convert import pdf_to_images
        output_dir = args.output or 'pdf_images'
        results = pdf_to_images(args.pdf_to_images, output_dir, dpi=args.pdf_dpi)
        print(f'✅ PDF 转图片完成: {len(results)} 页')
        for r in results:
            print(f'  {r}')
        return

    # 图片转 PDF
    if args.images_to_pdf:
        from engines.pdf_convert import images_to_pdf
        output = args.output or 'output.pdf'
        result = images_to_pdf(args.images_to_pdf, output)
        print(f'✅ 图片转 PDF 完成: {result}')
        return

    # 视频转 GIF
    if args.video_to_gif:
        from engines.gif_engine import convert_video_to_gif
        output = args.output or _change_ext(args.video_to_gif, '.gif')
        result = convert_video_to_gif(
            args.video_to_gif, output,
            fps=args.gif_fps, width=args.gif_width, colors=args.gif_colors,
        )
        size_mb = os.path.getsize(result) / (1024*1024)
        print(f'✅ 视频转 GIF 完成: {result} ({size_mb:.1f} MB)')
        return

    # 导出 ffmpeg 命令
    if args.export_cmd:
        from engines.ffmpeg_utils import export_ffmpeg_cmd
        inp, out = args.export_cmd
        cmd = export_ffmpeg_cmd(inp, out, params={})
        print(f'FFmpeg 命令:\n{cmd}')
        return

    # 嵌入字幕
    if args.embed_sub:
        from engines.ffmpeg_utils import embed_subtitle
        video, sub, out = args.embed_sub
        result = embed_subtitle(video, out, sub, language=args.sub_lang)
        print(f'✅ 字幕嵌入完成: {result}')
        return

    # 提取字幕
    if args.extract_sub:
        from engines.ffmpeg_utils import extract_subtitle
        video, out = args.extract_sub
        result = extract_subtitle(video, out)
        print(f'✅ 字幕提取完成: {result}')
        return

    # 合并音视频
    if args.merge:
        from engines.ffmpeg_utils import merge_media
        output = args.output or _add_suffix(args.merge[0], '_merged')
        result = merge_media(args.merge, output)
        print(f'✅ 合并完成: {result}')
        return

    # 裁剪视频
    if args.crop:
        if not args.crop_size:
            print('错误: 裁剪需要指定 --crop-size WIDTH HEIGHT', file=sys.stderr)
            sys.exit(1)
        from engines.ffmpeg_utils import crop_video
        output = args.output or _add_suffix(args.crop, '_cropped')
        w, h = args.crop_size
        x, y = args.crop_pos
        result = crop_video(args.crop, output, w, h, x, y)
        print(f'✅ 裁剪完成: {result}')
        return

    # 常规转换
    if not args.input:
        parser.print_help()
        sys.exit(0)

    if not args.format:
        print('错误: 请指定输出格式 (-f) 或使用其他功能选项', file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    from presets import PresetManager
    from utils import map_format_to_category
    from engines import convert_video, convert_audio, convert_image

    # 加载预设参数
    params = {}
    if args.preset:
        pm = PresetManager()
        preset = pm.get_preset(args.preset)
        if preset:
            params = preset
            if args.verbose:
                print(f'使用预设: {args.preset}')
        else:
            print(f'警告: 预设 "{args.preset}" 不存在', file=sys.stderr)

    output_ext = f'.{args.format.lstrip(".")}'
    inputs = args.input

    for inp in inputs:
        if not os.path.isfile(inp):
            print(f'跳过: 文件不存在 {inp}', file=sys.stderr)
            continue

        # 生成输出路径
        if args.output and len(inputs) == 1:
            output = args.output
        elif args.output:
            output = os.path.join(args.output, Path(inp).stem + output_ext)
        else:
            output = str(Path(inp).with_suffix(output_ext))

        # 确定转换类型
        input_ext = Path(inp).suffix.lower()
        category = map_format_to_category(input_ext.lstrip('.'))

        try:
            if category == 'video':
                result = convert_video(inp, output, params=params)
            elif category == 'audio':
                result = convert_audio(inp, output, params=params)
            elif category == 'image':
                result = convert_image(inp, output, params=params)
            else:
                print(f'跳过: 不支持的转换 {input_ext} → {output_ext}', file=sys.stderr)
                continue

            if args.verbose:
                size = os.path.getsize(result) / 1024
                print(f'✅ {inp} → {result} ({size:.0f} KB)')
            else:
                print(f'✅ {result}')

        except Exception as e:
            print(f'❌ {inp}: {e}', file=sys.stderr)


def _change_ext(path: str, new_ext: str) -> str:
    return str(Path(path).with_suffix(new_ext))


def _add_suffix(path: str, suffix: str) -> str:
    p = Path(path)
    return str(p.with_stem(p.stem + suffix))


if __name__ == '__main__':
    main()
