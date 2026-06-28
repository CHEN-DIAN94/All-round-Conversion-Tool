# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('themes', 'themes'),
        ('widgets.py', '.'),
    ],
    hiddenimports=[
        # PyQt6 完整模块
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        'PyQt6.sip',
        # 项目模块
        'engines', 'engines._common', 'engines.ffmpeg_core', 'engines.image_engine',
        'engines.excel_engine', 'engines.document_engine', 'engines.format_handlers',
        'engines.codec_compat', 'engines.gif_engine', 'engines.compress_engine',
        'engines.watermark_engine', 'engines.pdf_tools', 'engines.video_compress',
        'engines.image_resize', 'engines.pdf_convert', 'engines.ffmpeg_utils',
        'formats', 'widgets', 'constants', 'presets', 'history',
        'logging_config', 'themes', 'themes.cute_anim', 'themes.warm_anim',
        'cli', 'utils', 'workers',
        'ui', 'ui_file_table', 'ui_conversion', 'ui_settings',
        # 第三方库
        'pillow_heif', 'pypdf',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
        'openpyxl', 'pdf2docx', 'docx2pdf',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='流光',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
