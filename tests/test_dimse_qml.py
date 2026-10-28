from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_pacs_qml import scene, screenshot
from test_dimse import peer, STUDY, SERIES
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import find, click, type_text, descendants


def reveal(window, item):
    scroll = find(window, 'pacsProfileScroll')
    flick = next(i for i in descendants(scroll) if i.property('contentY') is not None)
    flick.setProperty('contentY', 0)
    QTest.qWait(20)
    y = item.mapToItem(scroll, QPointF()).y()
    flick.setProperty('contentY', max(0, min(y - 25, flick.property('contentHeight') - flick.height())))
    QTest.qWait(30)


def test_dimse_configuration_query_import_and_persistence(scene, peer, tmp_path):
    window, app, warnings = scene
    pacs = app.pacsController
    window.resize(1000, 600)
    click(window, find(window, 'sidebarSettings'))
    click(window, find(window, 'pacsAddProfile'))
    type_text(window, find(window, 'pacsProfileName'), 'DIMSE Local')
    combo = find(window, 'pacsProfileProtocol')
    click(window, combo)
    QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(50)
    assert not any(i.isVisible() for i in descendants(window.contentItem())
                   if i.objectName() in ('pacsProfileUrl', 'pacsProfileAuth'))
    for name, value in [('Host', '127.0.0.1'), ('Port', str(peer.port)), ('CalledAe', 'LABPACS'),
                        ('CallingAe', 'VOXENRA'), ('ListenHost', '127.0.0.1'),
                        ('ListenPort', str(peer.destination))]:
        item = find(window, 'pacsProfile' + name)
        reveal(window, item)
        type_text(window, item, value)
    for name in ('pacsTestDraft', 'pacsSaveProfile', 'pacsCancelProfile'):
        item = find(window, name)
        point = item.mapToScene(item.boundingRect().center())
        assert 0 < point.x() < window.width() and 0 < point.y() < window.height()
    click(window, find(window, 'pacsTestDraft'))
    wait_until(lambda: not pacs.busy)
    assert 'C-ECHO' in pacs.message and not pacs.isError
    screenshot(window, tmp_path, 'dimse-small-dialog')
    click(window, find(window, 'pacsSaveProfile'))
    QTest.qWait(50)
    profile = pacs.profiles[0]
    assert profile['protocol'] == 'dimse' and profile['port'] == peer.port
    assert profile['listen_port'] == peer.destination
    click(window, find(window, 'pacsEdit-' + profile['id']))
    assert find(window, 'pacsProfileCalledAe').property('text') == 'LABPACS'
    click(window, find(window, 'pacsCancelProfile'))
    click(window, find(window, 'sidebarPacs'))
    click(window, find(window, 'pacsQueryStudies'))
    wait_until(lambda: not pacs.busy)
    click(window, find(window, 'pacsStudy-' + STUDY))
    wait_until(lambda: not pacs.busy)
    click(window, find(window, 'pacsSeries-' + SERIES))
    click(window, find(window, 'pacsImportSelected'))
    wait_until(lambda: not pacs.busy)
    assert not pacs.isError, pacs.message
    assert app.workspaceController.activeTabType == '2d'
    assert app._series_catalog.get_series(SERIES).dicom_file_count == 3
    assert not warnings, warnings
