"""
presets.py — 转换预设管理系统

提供：
- PresetManager — 管理 JSON 文件中的转换预设
- 默认预设：微信发送、剪辑存档、网页上传
- 场景预设：Discord、YouTube 上传、iPhone 播放、存档原始、网页嵌入
- 每个预设映射到 AdvancedSettingsPanel 的参数

预设参数 keys（与 widgets.AdvancedSettingsPanel.DEFAULTS 一致）：
    video_crf, video_preset, audio_bitrate, audio_sample_rate,
    image_quality, image_resize
"""


__all__ = ['PresetManager']

import json
import os
import threading
from pathlib import Path
from typing import Optional

from logging_config import get_logger

logger = get_logger(__name__)

_PRESETS_FILE = Path(__file__).resolve().parent / 'presets.json'

# 默认预设（项目内置，不可删除）
_DEFAULT_PRESETS = {
    '微信发送': {
        'description': '小体积优先，适合微信发送（限制 25MB）',
        'video_crf': 30,
        'video_preset': 'fast',
        'audio_bitrate': '128k',
        'audio_sample_rate': 44100,
        'image_quality': 75,
        'image_resize': 80,
    },
    '剪辑存档': {
        'description': '最高画质，适合后期剪辑和长期存档',
        'video_crf': 16,
        'video_preset': 'slow',
        'audio_bitrate': '320k',
        'audio_sample_rate': 48000,
        'image_quality': 100,
        'image_resize': 100,
    },
    '网页上传': {
        'description': '平衡画质与体积，适合网页上传',
        'video_crf': 23,
        'video_preset': 'medium',
        'audio_bitrate': '192k',
        'audio_sample_rate': 44100,
        'image_quality': 85,
        'image_resize': 100,
    },
    # ---- 场景预设（对标 HandBrake 设备预设） ----
    'Discord': {
        'description': '50MB 以内，Discord 文件上传限制',
        'video_crf': 23,
        'video_preset': 'medium',
        'audio_bitrate': '128k',
        'audio_sample_rate': 44100,
        'max_width': 1920,
        'image_quality': 85,
        'image_resize': 100,
    },
    'YouTube 上传': {
        'description': '高质量，适合 YouTube 上传',
        'video_crf': 18,
        'video_preset': 'slow',
        'audio_bitrate': '256k',
        'audio_sample_rate': 48000,
        'image_quality': 95,
        'image_resize': 100,
    },
    'iPhone 播放': {
        'description': 'iPhone 原生播放兼容（H.264 High Profile）',
        'video_crf': 22,
        'video_preset': 'medium',
        'audio_bitrate': '192k',
        'audio_sample_rate': 44100,
        'video_profile': 'high',
        'video_level': '4.1',
        'image_quality': 90,
        'image_resize': 100,
    },
    '存档原始': {
        'description': '无损复制，保留所有流（不重编码）',
        'copy_codecs': True,
        'video_crf': 0,
        'video_preset': 'copy',
        'audio_bitrate': '0k',
        'image_quality': 100,
        'image_resize': 100,
    },
    '网页嵌入': {
        'description': 'WebM 格式，10MB 以内，网页嵌入友好',
        'video_crf': 26,
        'video_preset': 'fast',
        'audio_bitrate': '96k',
        'audio_sample_rate': 44100,
        'max_width': 1280,
        'image_quality': 75,
        'image_resize': 80,
    },
}


class PresetManager:
    """
    管理转换预设的加载、保存和查询。

    预设存储结构（presets.json）::

        {
            "presets": {
                "预设名": {
                    "description": "...",
                    "video_crf": 23,
                    ...
                }
            }
        }

    内置默认预设始终可用，不可被用户删除或覆盖。
    """

    def __init__(self, presets_path: Optional[str] = None):
        self._path = Path(presets_path) if presets_path else _PRESETS_FILE
        self._lock = threading.Lock()
        self._user_presets: dict = {}
        # 加载用户自定义预设
        self.load()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """从 JSON 文件加载用户自定义预设。文件不存在则跳过。"""
        with self._lock:
            if not self._path.exists():
                self._user_presets = {}
                return
            try:
                data = json.loads(self._path.read_text(encoding='utf-8'))
                self._user_presets = data.get('presets', {})
                logger.info('已加载 %d 个用户预设', len(self._user_presets))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning('预设文件加载失败: %s', exc)
                self._user_presets = {}

    def save(self) -> None:
        """将用户自定义预设写入 JSON 文件。"""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                data = {'presets': self._user_presets}
                self._path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                logger.info('已保存 %d 个用户预设', len(self._user_presets))
            except OSError as exc:
                logger.error('预设文件保存失败: %s', exc)

    def get_preset(self, name: str) -> Optional[dict]:
        """
        按名称获取预设参数（包含 description）。

        优先查用户自定义，再查内置默认。

        Returns:
            预设字典（含 description），未找到返回 None。
        """
        with self._lock:
            if name in self._user_presets:
                return self._user_presets[name].copy()
            if name in _DEFAULT_PRESETS:
                return _DEFAULT_PRESETS[name].copy()
            return None

    def list_presets(self) -> dict:
        """
        列出所有可用预设。

        Returns:
            dict[str, dict]  —  key=预设名, value=预设参数 dict
            内置默认在前，用户自定义在后（同名时用户覆盖内置）。
        """
        with self._lock:
            merged = {}
            # 内置默认
            for name, params in _DEFAULT_PRESETS.items():
                merged[name] = params.copy()
            # 用户自定义（可能覆盖同名内置）
            for name, params in self._user_presets.items():
                merged[name] = params.copy()
            return merged

    def add_preset(self, name: str, params: dict) -> None:
        """
        添加或更新用户自定义预设。

        Args:
            name: 预设名称
            params: 参数字典（可包含 description）
        """
        with self._lock:
            self._user_presets[name] = params.copy()
        logger.info('添加/更新预设: %s', name)

    def delete_preset(self, name: str) -> bool:
        """
        删除用户自定义预设。

        内置默认预设不可删除。

        Returns:
            True 如果删除成功，False 如果是内置预设或不存在。
        """
        with self._lock:
            if name in _DEFAULT_PRESETS:
                logger.warning('内置预设不可删除: %s', name)
                return False
            if name not in self._user_presets:
                return False
            del self._user_presets[name]
            logger.info('已删除预设: %s', name)
            return True
