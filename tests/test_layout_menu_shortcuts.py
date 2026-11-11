"""Layout shortcuts must act on the options in the foreground layout picker."""
import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest

from voxplane.model import DicomFolderScanSnapshot
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_four_d import _cross_series_four_d
from test_mpr_volume_tools_qml import item_window
from test_tag_qml import click, find


@pytest.mark.parametrize('kind', ['2d', 'mpr', '4d', 'comparempr'])
def test_layout_keys_follow_the_visible_presets(sidebar_scene, kind, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    if kind == 'comparempr':
        ws.createMprCompareTab(*(r.series_instance_uid for r in records[:2]))
    elif kind == '4d':
        images = _cross_series_four_d(tmp_path / 'temporal', phase_count=2)
        app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, images))
        ws.createTab(images[0].series_instance_uid, '4D', kind)
    else:
        ws.createTab(records[0].series_instance_uid, 'Layout keys', kind)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    window.requestActivate()
    wait_until(window.isActive)
    QTest.keyClick(window, Qt.Key_G)
    wait_until(lambda: window.property('activeReadingMenu') == 'mpr-layout')
    QTest.keyClick(window, Qt.Key_3)
    if kind == 'comparempr':
        assert tab.pairPlane == 'coronal' and find(window, 'compareMprLayout-coronal').property('checked')
    elif kind == '2d':
        assert tab.twoDLayout.layout == '1x2'
        QTest.keyClick(window, Qt.Key_9)
        assert tab.twoDLayout.layout == 'top-2'
        assert find(window, 'twoDLayout-top-2').property('hint') == '9'
        assert not find(window, 'twoDLayout-left-2').property('hint')
    else:
        assert tab.mprLayout.layout == 'columns' and find(window, 'mprLayout-columns').property('checked')
    # Selecting another menu releases the digits, and G restores the picker.
    QTest.keyClick(window, Qt.Key_Z)
    QTest.keyClick(window, Qt.Key_4)
    assert ws.activeViewport.zoom == 4
    QTest.keyClick(window, Qt.Key_G)
    assert app.shortcutController.assign('list-1', 'F8')
    QTest.keyClick(window, Qt.Key_F8)
    if kind == 'comparempr':
        assert tab.pairPlane == ''
    elif kind == '2d':
        assert tab.twoDLayout.layout == '1x1'
    else:
        assert tab.mprLayout.layout == 'right'
    assert not warnings, warnings


def test_compact_layout_picker_releases_keys_on_escape(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Layout keys', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    window.requestActivate()
    click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_G)
    popup = window.findChild(QObject, 'compactVolumePanel')
    wait_until(lambda: popup.property('opened'))
    surface = item_window(popup.property('contentItem'))
    QTest.keyClick(surface, Qt.Key_4)
    wait_until(lambda: ws.activeTab.twoDLayout.layout == '2x2')
    assert find(surface, 'twoDLayout-2x2').property('checked')
    QTest.keyClick(surface, Qt.Key_Escape)
    wait_until(lambda: not popup.property('visible'))
    QTest.keyClick(window, Qt.Key_2)
    assert ws.activeTab.twoDLayout.layout == '2x2'
    assert not warnings, warnings
