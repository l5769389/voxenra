import pytest
from PySide6.QtCore import QObject, QPointF
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click


def test_home_first_use_and_direct_actions(scene, monkeypatch):
    window, app, warnings = scene
    home = find(window, 'workspaceEmptyState')
    assert home.isVisible()
    assert find(window, 'homeOpenImport').isVisible()
    assert find(window, 'homeQuickStart').isVisible()
    assert find(window, 'homeOpenWorkspace').isVisible()
    assert not window.findChild(QObject, 'homeRecentSection').property('visible')
    calls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.workspace_document_controller.QFileDialog.getOpenFileName',
                        lambda *args: calls.append(args) or ('', ''))
    click(window, find(window, 'homeOpenWorkspace'))
    assert len(calls) == 1
    click(window, find(window, 'homeQuickStart'))
    wait_until(lambda: app.workspaceController.activeTabType == 'manual')
    assert app.workspaceController.manualController.chapterId == 'quick-start'
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
@pytest.mark.parametrize('theme', ['dark', 'graphite', 'light'])
def test_home_recent_layout_and_open(scene, tmp_path, locale, theme):
    window, app, warnings = scene
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'theme', theme)
    window.resize(1000, 700)
    doc = app.workspaceDocumentController
    for i in range(5):
        assert doc.save_to(tmp_path / (f'{i}-' + 'A long workspace name ' * 5 + '.voxworkspace'))
        wait_until(lambda: not doc.busy)
    wait_until(lambda: find(window, 'homeRecentSection').isVisible())
    QTest.qWait(80)
    home = find(window, 'workspaceEmptyState')
    row = find(window, 'homeRecentOpen-0')
    assert row.width() > 100
    pos = row.mapToItem(home, QPointF(0, 0))
    assert pos.x() >= 0 and pos.x() + row.width() <= home.width() + 1
    assert find(window, 'homeRecentName-0').property('truncated')
    chosen = doc.recentWorkspaces[0]['path']
    click(window, row)
    wait_until(lambda: not doc.busy)
    assert doc.path == chosen and not doc.isError
    click(window, find(window, 'homeRecentRemove-0'))
    assert len(doc.recentWorkspaces) == 4
    assert not warnings, warnings
