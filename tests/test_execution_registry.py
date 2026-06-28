"""
tests/test_execution_registry.py — 执行注册表与任务契约测试
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution_registry import TASK_PARAM_ALIASES, TASK_REGISTRY
from task_models import ExecutionResult, TaskSpec


class TestTaskRegistry:
    def test_registry_contains_expected_task_keys(self):
        expected = {
            'video', 'audio', 'image',
            'pdf_to_docx', 'docx_to_pdf', 'excel_to_image',
            'embed_subtitle', 'extract_subtitle', 'extract_audio',
            'merge_media', 'crop_video', 'trim_media',
            'compress_video', 'compress_image', 'resize_image',
            'add_watermark', 'video_to_gif',
        }
        assert expected.issubset(set(TASK_REGISTRY.keys()))

    def test_registry_values_are_callable(self):
        for key, runner in TASK_REGISTRY.items():
            assert callable(runner), key


class TestTaskParamAliases:
    def test_crop_video_alias_contract(self):
        assert TASK_PARAM_ALIASES['crop_video'] == {
            'width': 'crop_w',
            'height': 'crop_h',
            'x': 'crop_x',
            'y': 'crop_y',
        }

    def test_embed_subtitle_alias_contract(self):
        assert TASK_PARAM_ALIASES['embed_subtitle'] == {
            'subtitle_path': 'subtitle_path',
            'language': 'language',
        }

    def test_resize_image_alias_contract(self):
        assert TASK_PARAM_ALIASES['resize_image'] == {
            'width': 'width',
            'height': 'height',
            'percentage': 'percentage',
            'max_dimension': 'max_dimension',
            'quality': 'image_quality',
        }

    def test_compress_video_alias_contract(self):
        assert TASK_PARAM_ALIASES['compress_video'] == {
            'crf': 'crf',
            'scale_width': 'scale_width',
            'target_size_mb': 'target_size_mb',
        }


class TestTaskModels:
    def test_task_spec_defaults(self):
        task = TaskSpec(key='video', input_path='in.mp4', output_path='out.mp4')
        assert task.params == {}

    def test_execution_result_defaults(self):
        result = ExecutionResult()
        assert result.output_path is None
        assert result.progress_complete is False
