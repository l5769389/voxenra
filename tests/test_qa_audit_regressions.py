"""Regressions for QA undo policy and geometry-backed diameter controls."""
import pytest
from test_dicom_tags import qt_app, wait_until
from test_qa_edit_history import qa_work
from test_water_qa_controller import water_render, deliver_frame, wait_qa


@pytest.mark.parametrize('perform_undo', [False, True])
def test_qa_auto_calculation_continues_after_undo(qa_work, perform_undo):
    _, _, view, qa, history = qa_work
    assert qa.enabled and not qa._restored
    qa.deleteRoi('left')
    history.capture()
    if perform_undo:
        history.undo()
    deliver_frame(view, water_render(view, index=1))
    assert qa.status in ('calculating', 'ready'), 'An undo must not disable automatic QA for unseen slices'
    wait_until(lambda: qa.status == 'ready')


def test_single_noise_circle_size_matches_parameter(qa_work, qt_app):
    _, _, _, qa, _ = qa_work
    qa.setActiveGroup('noise')
    qa.setActiveDiameterMm(80)
    wait_qa(qt_app, qa)
    roi = next(r for r in qa._result.rois if r.group == 'noise')
    qa.select_at(roi.column, roi.row)
    qa.begin_drag(roi.column+roi.radius_mm, roi.row)
    assert qa._resize_handle
    qa.end_drag(roi.column+roi.radius_mm+4, roi.row)
    actual = next(r.radius_mm*2 for r in qa._result.rois if r.group == 'noise')
    shown = qa.activeDiameterMm
    assert shown == pytest.approx(actual), 'The sole circle and current group diameter disagree'


def test_group_diameter_can_restore_size_after_handle_edit(qa_work, qt_app):
    _, _, _, qa, _ = qa_work
    qa.setActiveGroup('noise')
    qa.setActiveDiameterMm(80)
    wait_qa(qt_app, qa)
    desired = qa.activeDiameterMm
    roi = next(r for r in qa._result.rois if r.group == 'noise')
    qa.select_at(roi.column, roi.row)
    qa.begin_drag(roi.column+roi.radius_mm, roi.row)
    qa.end_drag(roi.column+roi.radius_mm+4, roi.row)
    qa.setActiveDiameterMm(desired)
    wait_qa(qt_app, qa)
    actual = next(r.radius_mm*2 for r in qa._result.rois if r.group == 'noise')
    assert actual == pytest.approx(desired), 'Re-entering the displayed diameter must apply it'


def test_mixed_group_diameter_reapply_preserves_other_groups(qa_work, qt_app):
    _, _, _, qa, history = qa_work
    desired = qa.activeDiameterMm
    before = qa.currentResult
    roi = next(r for r in qa._result.rois if r.key == 'center')
    qa.select_at(roi.column, roi.row)
    qa.begin_drag(roi.column+roi.radius_mm, roi.row)
    qa.end_drag(roi.column+roi.radius_mm-2, roi.row)
    history.capture()
    assert qa.activeDiameterMixed
    mixed = qa.currentResult
    qa.setActiveDiameterMm(desired)
    wait_qa(qt_app, qa)
    history.capture()
    assert not qa.activeDiameterMixed
    assert all(r.radius_mm*2 == pytest.approx(desired) for r in qa._result.rois if r.group == 'uniformity')
    assert [r for r in qa.currentResult['rois'] if r['group'] == 'noise'] == [r for r in before['rois'] if r['group'] == 'noise']
    history.undo()
    assert qa.currentResult == mixed and qa.activeDiameterMixed
    history.redo()
    assert not qa.activeDiameterMixed


def test_workspace_protection_survives_undo_and_reset_undo(qa_work):
    _, _, view, qa, history = qa_work
    qa.restore_state(qa.persistent_state())
    history.reset()
    qa.deleteRoi('left'); history.capture()
    history.undo()
    qa.reset(); history.capture()
    history.undo()
    deliver_frame(view, water_render(view, index=1))
    assert qa.enabled and qa.status == 'empty'
    qa.analyze()
    wait_until(lambda: qa.status == 'ready')


def test_same_diameter_retry_keeps_explicit_resize(qa_work, qt_app, monkeypatch):
    from voxplane.ui.controller.viewport.controller import water_qa_controller as module
    _, _, _, qa, _ = qa_work
    qa.setActiveGroup('noise')
    qa.setActiveDiameterMm(80)
    wait_qa(qt_app, qa)
    roi = next(r for r in qa._result.rois if r.group == 'noise')
    qa.select_at(roi.column, roi.row)
    qa.begin_drag(roi.column+roi.radius_mm, roi.row)
    qa.end_drag(roi.column+roi.radius_mm+4, roi.row)
    original = module.measure_qa_rois
    def fail(*args, **kwargs):
        raise RuntimeError('temporary measurement failure')
    monkeypatch.setattr(module, 'measure_qa_rois', fail)
    qa.setActiveDiameterMm(80)
    wait_until(lambda: qa.status == 'error')
    monkeypatch.setattr(module, 'measure_qa_rois', original)
    qa.analyze()
    wait_qa(qt_app, qa)
    assert next(r.radius_mm*2 for r in qa._result.rois if r.group == 'noise') == 80
