"""
formats.py — 格式定义、映射表和文件辅助函数

从 ui.py 提取的纯数据定义，供 ui.py 和 widgets.py 共同使用。
"""

import os

from workers import FileStatus


# 类别键列表（多处引用，统一定义）
CATEGORY_KEYS = ['video', 'audio', 'image', 'document', 'spreadsheet']

# 格式映射表：类别 → (显示名称, 格式列表)
FORMAT_CATEGORIES = [
    ('video',   '视频', [
        ('MP4 (.mp4)',  '.mp4',  '通用兼容格式'),
        ('AVI (.avi)',  '.avi',  '老式 Windows 视频'),
        ('MKV (.mkv)',  '.mkv',  '高清多轨封装'),
        ('MOV (.mov)',  '.mov',  '苹果 QuickTime 格式'),
        ('WMV (.wmv)',  '.wmv',  'Windows 媒体视频'),
        ('WEBM (.webm)', '.webm','网页流媒体格式'),
        ('FLV (.flv)',  '.flv',  'Flash 视频格式'),
        ('GIF (.gif)',  '.gif',  '动态图片/视频'),
    ]),
    ('audio',   '音频', [
        ('MP3 (.mp3)',  '.mp3',  '通用音乐格式'),
        ('WAV (.wav)',  '.wav',  '无损原始音频'),
        ('FLAC (.flac)','.flac', '开源无损压缩'),
        ('AAC (.aac)',  '.aac',  '高级音频编码'),
        ('OGG (.ogg)',  '.ogg',  '开源音频格式'),
        ('WMA (.wma)',  '.wma',  'Windows 媒体音频'),
        ('M4A (.m4a)',  '.m4a',  'AAC 封装格式'),
    ]),
    ('image',   '图片', [
        ('JPEG (.jpg)', '.jpg', '通用照片格式（有损）'),
        ('PNG (.png)',  '.png', '无损透明图片'),
        ('BMP (.bmp)',  '.bmp', '无压缩位图'),
        ('GIF (.gif)',  '.gif', '动态图片格式'),
        ('TIFF (.tiff)','.tiff','高精度印刷格式'),
        ('WEBP (.webp)','.webp','网页高效图片'),
        ('ICO (.ico)',  '.ico', 'Windows 图标格式'),
    ]),
    ('document', '文档', [
        ('PDF (.pdf)',  '.pdf', '便携式文档格式（由 DOCX 转入）'),
        ('DOCX (.docx)','.docx','Word 文档格式（由 PDF 转入）'),
    ]),
    ('spreadsheet', '表格', [
        ('PNG (.png)',  '.png', '无损高清图片（推荐）'),
        ('JPEG (.jpg)', '.jpg', '通用照片格式（有损压缩）'),
    ]),
]

# 快速查找：类别 key → (显示名称, [(标签, 扩展名, 说明)])
FORMAT_BY_KEY = {k: (title, items) for k, title, items in FORMAT_CATEGORIES}

# 每个类别下所有可用的输出扩展名（自动从 FORMAT_CATEGORIES 推导）
CATEGORY_EXTS: dict[str, set[str]] = {}
for cat_key, _, items in FORMAT_CATEGORIES:
    CATEGORY_EXTS[cat_key] = {ext for _, ext, _ in items}

# 转换类型映射：(输入类别, 输出扩展名) → worker 使用的 conv_type（自动推导）
CONVERSION_MAP: dict[tuple[str, str], str] = {}
# 视频/音频/图片类别：同类别内任意输出都用类别名作为 conv_type
for cat_key in ('video', 'audio', 'image'):
    for ext in CATEGORY_EXTS.get(cat_key, set()):
        CONVERSION_MAP[(cat_key, ext)] = cat_key


# 表格列索引
COL_FILE_NAME = 0
COL_FILE_SIZE = 1
COL_PROGRESS = 2
COL_STATUS = 3
COL_COUNT = 4

# 状态颜色
STATUS_COLORS = {
    FileStatus.WAITING: '#64748B',
    FileStatus.CONVERTING: '#0EA5E9',
    FileStatus.SUCCESS: '#10B981',
    FileStatus.FAILED: '#EF4444',
    FileStatus.CANCELLED: '#F59E0B',
}


def _is_legacy_doc(file_path: str) -> bool:
    """检测是否为旧版 .doc 格式（OLE2 二进制格式，docx2pdf 不支持）。"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
            # OLE2 二进制格式的魔数: D0 CF 11 E0 A1 B1 1A E1
            return header[:4] == b'\xd0\xcf\x11\xe0'
    except (OSError, IOError):
        return False


def _collect_files_from_paths(paths: list[str]) -> list[str]:
    """从路径列表中收集所有文件，递归展开目录。

    防御：限制最大文件数 500，防止恶意/异常目录树导致卡死。
    """
    MAX_FILES = 500
    result = []
    seen: set[str] = set()

    for p in paths:
        if os.path.isfile(p):
            abs_p = os.path.abspath(p)
            if abs_p not in seen:
                seen.add(abs_p)
                result.append(p)
                if len(result) >= MAX_FILES:
                    break
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    fp = os.path.join(root, f)
                    abs_fp = os.path.abspath(fp)
                    if abs_fp not in seen:
                        seen.add(abs_fp)
                        result.append(fp)
                        if len(result) >= MAX_FILES:
                            return result

    return result
