"""
tests.test_presets — 预设管理系统测试

覆盖：
- PresetManager 初始化和默认预设加载
- get_preset / list_presets 查询
- add_preset / delete_preset 操作
- load / save 持久化
- 内置预设不可删除
"""

import json
import os
import sys
import tempfile

import pytest

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from presets import PresetManager, _DEFAULT_PRESETS


@pytest.fixture
def tmp_presets_path(tmp_path):
    """返回一个临时目录下的预设文件路径。"""
    return str(tmp_path / 'presets.json')


@pytest.fixture
def manager(tmp_presets_path):
    """创建一个使用临时路径的 PresetManager。"""
    return PresetManager(presets_path=tmp_presets_path)


class TestDefaultPresets:
    """内置默认预设测试"""

    def test_default_presets_exist(self):
        """内置默认预设应包含三个预设"""
        assert len(_DEFAULT_PRESETS) == 3

    def test_wechat_preset_exists(self):
        """微信发送预设应存在"""
        assert '微信发送' in _DEFAULT_PRESETS

    def test_archive_preset_exists(self):
        """剪辑存档预设应存在"""
        assert '剪辑存档' in _DEFAULT_PRESETS

    def test_web_preset_exists(self):
        """网页上传预设应存在"""
        assert '网页上传' in _DEFAULT_PRESETS

    def test_wechat_small_size(self):
        """微信发送预设应有较高的 CRF（较小文件）"""
        assert _DEFAULT_PRESETS['微信发送']['video_crf'] >= 28

    def test_archive_high_quality(self):
        """剪辑存档预设应有较低的 CRF（高质量）"""
        assert _DEFAULT_PRESETS['剪辑存档']['video_crf'] <= 18

    def test_all_presets_have_required_keys(self):
        """所有预设应包含必要的参数键"""
        required = {'video_crf', 'video_preset', 'audio_bitrate'}
        for name, preset in _DEFAULT_PRESETS.items():
            for key in required:
                assert key in preset, f'预设 {name} 缺少键 {key}'


class TestPresetManagerInit:
    """PresetManager 初始化测试"""

    def test_init_empty_file(self, manager):
        """空文件初始化后用户预设应为空"""
        assert manager._user_presets == {}

    def test_init_loads_existing(self, tmp_presets_path):
        """已有文件应被加载"""
        data = {'presets': {'test': {'video_crf': 20}}}
        with open(tmp_presets_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        mgr = PresetManager(presets_path=tmp_presets_path)
        assert 'test' in mgr._user_presets

    def test_init_invalid_json(self, tmp_presets_path):
        """无效 JSON 文件应跳过加载"""
        with open(tmp_presets_path, 'w', encoding='utf-8') as f:
            f.write('not valid json')

        mgr = PresetManager(presets_path=tmp_presets_path)
        assert mgr._user_presets == {}


class TestGetPreset:
    """get_preset 查询测试"""

    def test_get_default_preset(self, manager):
        """应能获取内置默认预设"""
        preset = manager.get_preset('微信发送')
        assert preset is not None
        assert 'video_crf' in preset

    def test_get_user_preset(self, manager):
        """应能获取用户自定义预设"""
        manager.add_preset('custom', {'video_crf': 25})
        preset = manager.get_preset('custom')
        assert preset is not None
        assert preset['video_crf'] == 25

    def test_get_nonexistent(self, manager):
        """不存在的预设应返回 None"""
        assert manager.get_preset('nonexistent') is None

    def test_get_returns_copy(self, manager):
        """返回的应是副本，修改不影响原数据"""
        preset1 = manager.get_preset('微信发送')
        preset1['video_crf'] = 999
        preset2 = manager.get_preset('微信发送')
        assert preset2['video_crf'] != 999


class TestListPresets:
    """list_presets 测试"""

    def test_lists_defaults(self, manager):
        """应列出所有内置默认预设"""
        presets = manager.list_presets()
        assert '微信发送' in presets
        assert '剪辑存档' in presets
        assert '网页上传' in presets

    def test_lists_user_presets(self, manager):
        """应列出用户自定义预设"""
        manager.add_preset('my_preset', {'video_crf': 30})
        presets = manager.list_presets()
        assert 'my_preset' in presets

    def test_user_overrides_default(self, manager):
        """同名用户预设应覆盖内置预设"""
        manager.add_preset('微信发送', {'video_crf': 99})
        presets = manager.list_presets()
        assert presets['微信发送']['video_crf'] == 99


class TestAddDeletePreset:
    """add_preset / delete_preset 测试"""

    def test_add_preset(self, manager):
        """应能添加新预设"""
        manager.add_preset('new', {'video_crf': 22})
        assert 'new' in manager._user_presets

    def test_delete_user_preset(self, manager):
        """应能删除用户预设"""
        manager.add_preset('temp', {'video_crf': 22})
        assert manager.delete_preset('temp') is True
        assert manager.get_preset('temp') is None

    def test_cannot_delete_default(self, manager):
        """不能删除内置默认预设"""
        assert manager.delete_preset('微信发送') is False

    def test_delete_nonexistent(self, manager):
        """删除不存在的预设应返回 False"""
        assert manager.delete_preset('nonexistent') is False


class TestSaveLoad:
    """持久化 save / load 测试"""

    def test_save_creates_file(self, manager, tmp_presets_path):
        """save 应创建 JSON 文件"""
        manager.add_preset('saved', {'video_crf': 20})
        manager.save()

        assert os.path.isfile(tmp_presets_path)

    def test_save_load_roundtrip(self, manager, tmp_presets_path):
        """保存后重新加载应保留数据"""
        manager.add_preset('roundtrip', {'video_crf': 19, 'description': 'test'})
        manager.save()

        mgr2 = PresetManager(presets_path=tmp_presets_path)
        preset = mgr2.get_preset('roundtrip')
        assert preset is not None
        assert preset['video_crf'] == 19
        assert preset['description'] == 'test'

    def test_save_multiple_presets(self, manager, tmp_presets_path):
        """应能保存多个预设"""
        for i in range(5):
            manager.add_preset(f'preset_{i}', {'video_crf': 20 + i})
        manager.save()

        mgr2 = PresetManager(presets_path=tmp_presets_path)
        for i in range(5):
            assert mgr2.get_preset(f'preset_{i}') is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
