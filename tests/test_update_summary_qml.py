"""Update-summary rendering in a separate engine process from Qt Quit tests."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.app_updates import Installation, parse_release
from qt_dicom_viewer.i18n import message
from test_app_updates import release_payload
from test_pacs_qml import scene
from test_tag_qml import find, click
from test_dicom_tags import qt_app


@pytest.mark.parametrize('theme', ['dark', 'graphite', 'light'])
def test_summary_language_scroll_layout_and_release_link(scene, tmp_path, monkeypatch, theme):
    window, app, warnings = scene
    updater = app.updateController
    updater._cache = tmp_path / 'updates'
    updater._installation = Installation('macos', tmp_path / 'Voxenra.app')
    notes = '''## 更新摘要
- 操作偏好：自定义鼠标拖动、滚轮方向与工具快捷键，支持冲突检查。
- 界面与隐私：增加界面缩放、新视图隐藏身份信息和最近工作区清理。
- 工作区：优化首次使用入口、恢复工作区与最近工作区导航。
- 分割：支持轮廓、填充与透明度设置，改善画笔、橡皮及撤销重做的流畅度。
- 性能：降低体数据加载与解码缓存的内存占用。
- 校准：缺少有效像素间距时限制毫米测量，避免显示不可靠的定量结果。

## Update summary
- Controls: customize mouse dragging, wheel direction and tool shortcuts with conflict checks.
- Appearance and privacy: adjust interface scale, hide identity in new views and clear recent workspaces.
- Workspace: improve first-use navigation, workspace restoration and access to recent workspaces.
- Segmentation: control outlines, fill and opacity, with smoother painting, erasing, undo and redo.
- Performance: reduce memory use during volume loading and in the decoding cache.
- Calibration: prevent unreliable millimeter measurements when valid pixel spacing is missing.

## Validation
- Internal build records should not appear in the update summary.
'''
    updater._release = parse_release(dict(release_payload('2.0.0'), body=notes), '1.7.0', 'macos')
    app.settingsController.setValue('appearance', 'theme', theme)
    updater._set_state('available', message('updates.available', version='2.0.0'))
    updater.show()
    QTest.qWait(60)
    text = find(window, 'applicationReleaseNotes')
    scroll = find(window, 'applicationReleaseNotesScroll')
    flickable = scroll.property('contentItem')
    for locale in ['zh-CN', 'en-US', 'zh-CN']:
        app.languageController.selectLanguage(locale)
        for width, height in [(1440, 900), (1280, 720)]:
            window.resize(width, height)
            QTest.qWait(80)
            displayed = text.property('text')
            assert displayed == updater.releaseNotes
            assert ('操作偏好' in displayed) == (locale == 'zh-CN')
            assert ('Controls:' in displayed) == (locale == 'en-US')
            assert 'Internal build' not in displayed
            assert displayed.count('• ') == 6
            assert abs(flickable.property('contentY')) < 1
            assert text.width() <= scroll.width()
            first = text.mapToScene(QPointF())
            top = scroll.mapToScene(QPointF())
            assert first.y() >= top.y() - 1
            for name in ['applicationReleaseNotesLink', 'applicationUpdateAction', 'applicationUpdateCancel']:
                control = find(window, name)
                p = control.mapToScene(QPointF(control.width(), control.height()))
                assert p.x() <= window.width() and p.y() <= window.height()
            output = Path('build/update-summary')
            output.mkdir(parents=True, exist_ok=True)
            assert window.grabWindow().save(str(output / f'{theme}-{locale}-{width}.png'))
    # A long legacy summary remains scrollable; reopening starts at the first
    # item instead of retaining the previous reading position/caret offset.
    updater._release = parse_release(dict(release_payload('2.0.0'), body='## 新增与改进\n' +
                                         '\n'.join('- ' + '长说明' * 80 for _ in range(6))), '1.7.0', 'macos')
    updater.changed.emit()
    QTest.qWait(60)
    assert flickable.property('contentHeight') > flickable.property('height')
    flickable.setProperty('contentY', 60)
    click(window, find(window, 'applicationUpdateCancel'))
    updater.show()
    QTest.qWait(60)
    assert abs(flickable.property('contentY')) < 1
    urls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.update_controller.QDesktopServices.openUrl',
                        lambda url: urls.append(url.toString()) or True)
    click(window, find(window, 'applicationReleaseNotesLink'))
    assert urls == ['https://github.com/l5769389/voxenra/releases/tag/v2.0.0']
    assert not warnings, warnings
