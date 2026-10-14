"""A failed VOI calculation must put its reason inside the visible tool area."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import descendants
from test_mpr_voi_controller import draw


@pytest.mark.parametrize('mode', ['voi', 'segmentation'])
def test_calculation_error_is_visible_without_scrolling(sidebar_scene, monkeypatch, mode):
    from qt_dicom_viewer.ui.controller.tab import mpr_voi_controller as module
    window, app, records, warnings = sidebar_scene
    window.resize(1000, 600)
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'VOI error', 'mpr')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    tab = workspace.activeTab
    tab.toolController.activateTool(mode)
    original = module.evaluate_voi
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(True)
        raise MemoryError()
    monkeypatch.setattr(module, 'evaluate_voi', fail)
    c = tab.voiController
    draw(c, tab.activeViewport)
    wait_until(lambda: bool(attempts) and not c._running)
    assert not c.busy and c.error
    QTest.qWait(50)
    message = next(item for item in descendants(window.contentItem())
                   if item.isVisible() and item.property('text') == c.error)
    flick = next(item for item in descendants(window.contentItem())
                 if item.objectName() == 'toolDetailFlickable')
    start = message.mapToItem(flick, QPointF())
    end = message.mapToItem(flick, QPointF(message.width(), message.height()))
    assert 0 <= start.y() < end.y() <= flick.height()
    assert 0 <= start.x() < end.x() <= flick.width()
    key = c.records[0]['id']
    monkeypatch.setattr(module, 'evaluate_voi', original)
    if mode == 'voi':
        c.setDiameter(c.selected['diameter'] + 1)
    else:
        c.setThreshold(400)
    wait_until(lambda: key in c.evaluations and not c.busy)
    assert not c.error and c.records[0]['id'] == key
    assert not warnings, warnings


def test_new_error_revealed_after_scrolling_to_threshold(sidebar_scene, monkeypatch):
    from qt_dicom_viewer.ui.controller.tab import mpr_voi_controller as module
    window, app, records, warnings = sidebar_scene
    window.resize(1000, 600)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Scrolled VOI error', 'mpr')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    tab.toolController.activateTool('segmentation')
    c = tab.voiController
    draw(c, tab.activeViewport)
    wait_until(lambda: not c.busy)
    QTest.qWait(50)
    flick = next(item for item in descendants(window.contentItem()) if item.objectName() == 'toolDetailFlickable')
    flick.setProperty('contentY', max(0, flick.property('contentHeight') - flick.height()))
    QTest.qWait(30)
    assert flick.property('contentY') > 0
    def fail(*args, **kwargs):
        raise MemoryError()
    monkeypatch.setattr(module, 'evaluate_voi', fail)
    c.setThreshold(c.selected['threshold'] + 1)
    wait_until(lambda: bool(c.error) and not c.busy)
    QTest.qWait(50)
    message = next(item for item in descendants(window.contentItem()) if item.objectName() == 'voiCalculationError')
    start = message.mapToItem(flick, QPointF())
    end = message.mapToItem(flick, QPointF(message.width(), message.height()))

    assert 0 <= start.y() < end.y() <= flick.height()
