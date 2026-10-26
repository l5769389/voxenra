import pytest
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length
from test_water_qa_controller import water_render, deliver_frame


@pytest.fixture
def qa_work(qt_app, tmp_path):
    app, _ = populated_app(tmp_path)
    tab = app.workspaceController.activeTab
    view = tab.activeViewport
    deliver_frame(view, water_render(view))
    qa = view.qaController
    qa.activate()
    wait_until(lambda: qa.status == 'ready')
    tab.historyController.reset()
    try:
        yield app, tab, view, qa, tab.historyController
    finally:
        app.shutdown()


def test_move_copy_delete_regenerate_undo_redo(qa_work):
    app, tab, view, qa, history = qa_work
    original = qa.currentResult
    center = qa.roiItems[0]
    qa.begin_drag(center['column'], center['row'])
    qa.end_drag(center['column']+3, center['row']+2)
    history.capture()
    moved = qa.currentResult
    assert history.canUndo and moved != original
    qa.copyRoi('center'); history.capture()
    copied = qa.currentResult
    qa.deleteRoi('center'); history.capture()
    deleted = qa.currentResult
    qa.regenerateRois()
    wait_until(lambda: qa.status == 'ready'); history.capture()
    assert len(qa.roiItems) == 5
    for expected in (deleted, copied, moved, original):
        history.undo()
        assert qa.currentResult == expected
    for expected in (moved, copied, deleted):
        history.redo()
        assert qa.currentResult == expected


def test_navigation_does_not_add_history_and_measurements_interleave(qa_work):
    app, tab, view, qa, history = qa_work
    qa.deleteRoi('left'); history.capture()
    changed = qa.currentResult
    first = water_render(view)
    deliver_frame(view, water_render(view, index=1))
    wait_until(lambda: qa.status == 'ready')
    history.capture()
    assert len(history._undo) == 1
    deliver_frame(view, first)
    assert qa.currentResult == changed
    draw_length(view); history.capture()
    history.undo()
    assert not view._measure_controller._measurements and qa.currentResult == changed
    history.undo()
    assert len(qa.roiItems) == 5
    history.redo()
    assert qa.currentResult == changed


def test_parameters_reset_and_late_results_cannot_overwrite_undo(qa_work, monkeypatch):
    app, tab, view, qa, history = qa_work
    original = qa.currentResult
    qa.setRoiDiameterMm(30)
    wait_until(lambda: qa.status == 'ready'); history.capture()
    resized = qa.currentResult
    assert history.canUndo
    history.undo(); assert qa.currentResult == original
    history.redo(); assert qa.currentResult == resized
    qa.reset(); history.capture()
    assert not qa.enabled
    history.undo(); assert qa.currentResult == resized and qa.enabled
    jobs = []
    monkeypatch.setattr(qa, '_submit', lambda *args: jobs.append(args))
    qa.regenerateRois()
    history.undo()
    expected = qa.currentResult
    token, key, *_ = jobs[-1]
    qa._receive_result(token, key, qa._result, '')
    assert qa.currentResult == expected


def test_failed_regeneration_preserves_last_successful_record(qa_work, monkeypatch):
    _, _, _, qa, history = qa_work
    qa.deleteRoi('left'); history.capture()
    saved = qa.persistent_state()['records']
    jobs=[]
    monkeypatch.setattr(qa, '_submit', lambda *args: jobs.append(args))
    qa.regenerateRois()
    assert qa.persistent_state()['records'] == saved
    token, key, *_ = jobs[-1]
    qa._receive_result(token, key, None, 'failed')
    assert qa.status == 'error' and qa.persistent_state()['records'] == saved
    history.undo()
    assert len(qa.roiItems) == 5


def test_measurement_undo_does_not_cancel_automatic_slice_analysis(qa_work, monkeypatch):
    _, _, view, qa, history = qa_work
    draw_length(view); history.capture()
    jobs=[]
    monkeypatch.setattr(qa, '_submit', lambda *args: jobs.append(args))
    deliver_frame(view, water_render(view, index=1))
    assert qa.status == 'calculating'
    token = qa._token
    history.undo()
    assert not view._measure_controller._measurements
    assert qa._token == token and qa.status == 'calculating'


def test_fallback_circles_support_delete_move_and_redo(qa_work):
    import numpy as np
    _, _, view, qa, history = qa_work
    deliver_frame(view, water_render(view, pixels=np.full((128,128),40,dtype=np.float32)))
    wait_until(lambda: qa.status == 'ready')
    assert qa.currentResult['phantom'] is None
    history.reset()
    original=qa.currentResult
    qa.deleteRoi('center'); history.capture()
    deleted=qa.currentResult
    roi=qa.roiItems[0]
    qa.begin_drag(roi['column'],roi['row'])
    qa.end_drag(roi['column']+5,roi['row']+3); history.capture()
    moved=qa.currentResult
    assert moved != deleted
    history.undo(); assert qa.currentResult == deleted
    history.undo(); assert qa.currentResult == original
    history.redo(); assert qa.currentResult == deleted
    history.redo(); assert qa.currentResult == moved
