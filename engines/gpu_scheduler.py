"""
engines.gpu_scheduler — GPU 硬件加速智能调度器

自动检测 GPU 能力，管理并发会话，故障自动回退软编码。

支持：
- NVIDIA NVENC (通过 nvidia-smi 探测)
- Intel QSV (通过 ffmpeg -hwaccels 探测)
- AMD AMF (通过 ffmpeg -hwaccels 探测)
- 自动回退 libx264
"""

__all__ = ['GpuScheduler', 'GpuBackend', 'GpuInfo']

import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from utils import get_ffmpeg_path, CREATE_NO_WINDOW
from logging_config import get_logger

logger = get_logger(__name__)


class GpuBackend(Enum):
    """GPU 后端类型。"""
    NVIDIA = 'nvidia'
    INTEL = 'intel'
    AMD = 'amd'
    NONE = 'none'


@dataclass(frozen=True)
class GpuInfo:
    """GPU 信息快照。"""
    backend: GpuBackend
    encoder: str           # 如 "h264_nvenc"
    decoder: str           # 如 "h264_cuvid"
    max_sessions: int      # NVENC: 消费级 2-3，专业卡 -1（无限）
    vram_mb: int           # 显存容量（影响能承受的分辨率）
    is_available: bool     # 是否可用
    gpu_name: str = ''     # GPU 名称（用于 UI 显示）


class GpuScheduler:
    """
    GPU 编码器的智能调度。

    功能：
    1. 自动检测 GPU 类型和能力
    2. 并发会话控制（NVENC 消费级有会话数限制）
    3. 满载时自动回退软编码
    4. 线程安全
    """

    def __init__(self):
        self._gpu_info: Optional[GpuInfo] = None
        self._active_sessions = 0
        self._lock = threading.Lock()
        self._probed = False

    @property
    def gpu_info(self) -> Optional[GpuInfo]:
        """获取 GPU 信息（首次访问时自动探测）。"""
        if not self._probed:
            self.probe_gpu()
        return self._gpu_info

    def probe_gpu(self, ffmpeg_path: Optional[str] = None) -> GpuInfo:
        """
        三层探测 GPU 能力。

        Layer 1: nvidia-smi（NVIDIA GPU）
        Layer 2: ffmpeg -hwaccels（Intel QSV / AMD AMF）
        Layer 3: 回退到软编码
        """
        if ffmpeg_path is None:
            ffmpeg_path = get_ffmpeg_path()

        # ---- Layer 1: NVIDIA ----
        nvidia_info = self._probe_nvidia()
        if nvidia_info:
            self._gpu_info = nvidia_info
            self._probed = True
            logger.info('检测到 NVIDIA GPU: %s, 编码器: %s',
                       nvidia_info.gpu_name, nvidia_info.encoder)
            return nvidia_info

        # ---- Layer 2: 通过 ffmpeg 探测硬件加速器 ----
        hw_info = self._probe_ffmpeg_hwaccels(ffmpeg_path)
        if hw_info:
            self._gpu_info = hw_info
            self._probed = True
            logger.info('检测到硬件加速: %s, 编码器: %s',
                       hw_info.backend.value, hw_info.encoder)
            return hw_info

        # ---- Layer 3: 无 GPU，回退软编码 ----
        fallback = GpuInfo(
            backend=GpuBackend.NONE,
            encoder='libx264',
            decoder='',
            max_sessions=-1,
            vram_mb=0,
            is_available=False,
            gpu_name='无 GPU（使用软件编码）',
        )
        self._gpu_info = fallback
        self._probed = True
        logger.info('未检测到 GPU，使用软件编码 libx264')
        return fallback

    def _probe_nvidia(self) -> Optional[GpuInfo]:
        """通过 nvidia-smi 探测 NVIDIA GPU。"""
        try:
            out = subprocess.check_output(
                ['nvidia-smi', '--query-gpu=name,memory.total',
                 '--format=csv,noheader,nounits'],
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
                stderr=subprocess.DEVNULL,
            )
            line = out.decode('utf-8', errors='replace').strip()
            if not line:
                return None
            parts = line.split(', ')
            if len(parts) < 2:
                return None
            name = parts[0].strip()
            vram = int(parts[1].strip())

            # 判断是否专业卡（无并发限制）
            name_upper = name.upper()
            is_pro = any(k in name_upper for k in (
                'QUADRO', 'RTX A', 'TESLA', 'A100', 'H100', 'A6000', 'A5000',
            ))

            return GpuInfo(
                backend=GpuBackend.NVIDIA,
                encoder='h264_nvenc',
                decoder='h264_cuvid',
                max_sessions=-1 if is_pro else 3,
                vram_mb=vram,
                is_available=True,
                gpu_name=name,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            return None

    def _probe_ffmpeg_hwaccels(self, ffmpeg_path: str) -> Optional[GpuInfo]:
        """通过 ffmpeg -hwaccels 探测 Intel QSV / AMD AMF。"""
        try:
            out = subprocess.check_output(
                [ffmpeg_path, '-hide_banner', '-hwaccels'],
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
                stderr=subprocess.DEVNULL,
            )
            hwaccels = out.decode('utf-8', errors='replace').lower()

            # Intel QSV
            if 'qsv' in hwaccels:
                return GpuInfo(
                    backend=GpuBackend.INTEL,
                    encoder='h264_qsv',
                    decoder='h264_qsv',
                    max_sessions=-1,  # QSV 无硬性会话限制
                    vram_mb=0,
                    is_available=True,
                    gpu_name='Intel QSV',
                )

            # AMD AMF
            if 'amf' in hwaccels or 'd3d11va' in hwaccels:
                return GpuInfo(
                    backend=GpuBackend.AMD,
                    encoder='h264_amf',
                    decoder='h264_amf',
                    max_sessions=-1,
                    vram_mb=0,
                    is_available=True,
                    gpu_name='AMD AMF',
                )

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        return None

    def acquire_encoder(self) -> tuple[str, list[str]]:
        """
        获取编码器名称和额外的 ffmpeg 参数。

        Returns:
            (encoder_name, extra_args)
            如果 GPU 并发已满，自动回退到 libx264。
        """
        gpu = self._gpu_info
        if not gpu or gpu.backend == GpuBackend.NONE:
            return 'libx264', []

        with self._lock:
            if gpu.max_sessions > 0 and self._active_sessions >= gpu.max_sessions:
                logger.info('GPU 并发已满 (%d/%d)，回退到 libx264',
                           self._active_sessions, gpu.max_sessions)
                return 'libx264', []
            self._active_sessions += 1

        extra_args = []
        if gpu.backend == GpuBackend.NVIDIA:
            extra_args = ['-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda']
        elif gpu.backend == GpuBackend.INTEL:
            extra_args = ['-hwaccel', 'qsv']
        elif gpu.backend == GpuBackend.AMD:
            extra_args = ['-hwaccel', 'd3d11va']

        return gpu.encoder, extra_args

    def release_encoder(self) -> None:
        """释放一个 GPU 编码会话。"""
        with self._lock:
            self._active_sessions = max(0, self._active_sessions - 1)

    @property
    def active_sessions(self) -> int:
        """当前活跃的 GPU 编码会话数。"""
        with self._lock:
            return self._active_sessions

    @property
    def is_gpu_available(self) -> bool:
        """GPU 是否可用。"""
        info = self.gpu_info
        return info is not None and info.is_available

    def get_display_name(self) -> str:
        """获取用于 UI 显示的 GPU 名称。"""
        info = self.gpu_info
        if info and info.is_available:
            return f'🎮 {info.gpu_name} ({info.encoder})'
        return '🖥️ 软件编码 (libx264)'
