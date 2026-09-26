from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtCore import QObject, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app
from test_pacs_qml import scene
from test_tag_qml import find, click


@pytest.mark.parametrize('theme,locale', [('dark', 'zh-CN'), ('graphite', 'zh-CN'), ('light', 'en-US')])
def test_feedback_entry_draft_preview_and_channels(scene, theme, locale, monkeypatch):
    window, app, warnings = scene
    window.resize(1280, 720)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    urls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.feedback_controller.QDesktopServices.openUrl',
                        lambda url: urls.append(url.toString()) or True)
    app.workspaceController.openSettings()
    QTest.qWait(100)
    click(window, find(window, 'settingsFeedback'))
    QTest.qWait(80)
    assert not find(window, 'feedbackGitHub').isEnabled()
    subject = find(window, 'feedbackSubject')
    subject.setProperty('text', 'Window display & layout')
    description = find(window, 'feedbackDescription')
    description.setProperty('text', 'Steps: open an image.\nExpected: a visible viewport.')
    click(window, find(window, 'feedbackDetails'))
    info = find(window, 'feedbackSystemInfo')
    assert info.property('text') == app.feedbackController.systemInfo
    assert f'Theme: {theme}' in info.property('text')
    assert f'Language: {locale}' in info.property('text')
    for name in ('feedbackCopy', 'feedbackEmail', 'feedbackGitHub'):
        item = find(window, name)
        p = item.mapToScene(QPointF(item.width(), item.height()))
        assert p.x() <= window.width() and p.y() <= window.height()
    destination = Path('build/feedback-preview'); destination.mkdir(parents=True, exist_ok=True)
    QTest.qWait(100)
    assert window.grabWindow().save(str(destination / f'{theme}-{locale}.png'))
    click(window, find(window, 'feedbackCopy'))
    assert 'Version:' in QGuiApplication.clipboard().text()
    click(window, find(window, 'feedbackGitHub'))
    assert urls[-1].startswith('https://github.com/l5769389/voxenra/issues/new?')
    click(window, find(window, 'feedbackIncludeInfo'))
    click(window, find(window, 'feedbackEmail'))
    assert urls[-1].startswith('mailto:5769389@qq.com?')
    assert 'Version:' not in parse_qs(urlsplit(urls[-1]).query)['body'][0]
    click(window, find(window, 'feedbackDialogClose'))
    assert not window.findChild(QObject, 'feedbackDialog').property('visible')
    app.workspaceController.openManual('settings')
    QTest.qWait(100)
    click(window, find(window, 'manualFeedback'))
    assert find(window, 'feedbackSubject').property('text') == 'Window display & layout'
    click(window, find(window, 'feedbackDialogClose'))
    QGuiApplication.clipboard().clear()
    assert not warnings, warnings
