from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
import pytest

from qt_dicom_viewer.ui.controller.edit_history_controller import EditHistoryController
from test_mpr_voi_controller import setup_voi, draw
from test_measurement_qml import qt_app
from test_mpr_voi_qml import settle


@pytest.fixture
def history(setup_voi):
    c, _, _ = setup_voi
    tab = QObject()
    tab._voi_controller = c
    tab.viewports_by_id = {}
    history = EditHistoryController(tab)
    yield history
    history.dispose()


def test_display_selection_results_and_cancel_do_not_scan_history(setup_voi, history, monkeypatch):
    c, view, tools = setup_voi
    draw(c, view); settle(c); QTest.qWait(20)
    assert len(history._undo) == 1
    import qt_dicom_viewer.ui.controller.edit_history_controller as module
    monkeypatch.setattr(module, 'edit_signature', lambda *a: pytest.fail('non-edit scanned history'))
    c.setFillOpacity(51); c.setDisplayMode('outline')
    c.setBrushDiameter(8); c.setBrushRelative(True); c.setBrushPercent(4)
    c.setEnabled(False); c.setEnabled(True)
    c._selected = ''; c.select(c.records[0]['id'])
    c.begin(view, 2, 2, .1); c.update(view, 1, 1); c.cancel()
    c._accept((c._revision, {}, ''))
    QTest.qWait(30)
    assert len(history._undo) == 1 and not history._timer.isActive()


def test_completed_edits_are_automatically_undoable_and_source_refresh_is_not(setup_voi, history):
    c, view, _ = setup_voi
    draw(c, view); settle(c); QTest.qWait(20)
    key = c.selectedId
    actions = [lambda: c.renameItem(key, 'Test segment'),
               lambda: c.setColor(key, '#ff8844'),
               lambda: c.toggleVisible(key),
               lambda: c.setThreshold(450),
               lambda: c.setDepth(2),
               lambda: c.remove(key)]
    for count, action in enumerate(actions, 2):
        action(); settle(c); QTest.qWait(20)
        assert len(history._undo) == count
    history.undo()
    assert c.records[0]['name'] == 'Test segment'
    assert c.records[0]['color'] == '#ff8844' and not c.records[0]['visible']
    assert c.records[0]['threshold'] == 450 and c.records[0]['region'].size[2] == 2
    count = len(history._undo)
    c.set_phase(1, ready=False); c.set_phase(None); c.set_source(view._voi_volume)
    settle(c); QTest.qWait(20)
    assert len(history._undo) == count
    history.redo()
    assert c.records == []


def test_failed_snapshot_preserves_redo_and_current_history(setup_voi, history, monkeypatch):
    c, view, _ = setup_voi
    draw(c, view); settle(c); QTest.qWait(20)
    history.undo()
    current, undo, redo = history._current, list(history._undo), list(history._redo)
    import qt_dicom_viewer.ui.controller.edit_history_controller as module
    def fail(*args):
        raise ValueError('document limit')
    monkeypatch.setattr(module, 'dumps', fail)
    draw(c, view)
    with pytest.raises(ValueError, match='document limit'):
        history.capture()
    assert history._current == current and history._undo == undo and history._redo == redo


def test_empty_segment_creation_undo_redo_keeps_identity_and_mask(setup_voi, history):
    c, _, _ = setup_voi
    c.newSegment(); QTest.qWait(25)
    key = c.selectedId
    assert len(c.records) == 1 and c.evaluations[key].metrics['count'] == 0
    history.undo()
    assert not c.records
    history.redo(); settle(c)
    assert len(c.records) == 1 and c.records[0]['id'] == key
    assert not c.records[0]['mask'].any()
