"""Recalculation recovery must retain geometry without presenting stale values."""
import pytest
from PySide6.QtTest import QTest

from test_water_qa_controller import qt_app, qa_view, wait_qa
from test_water_qa_qml import qa_workspace, qa_control
from test_service_panel_qml import _find, _click


def test_failed_recalculation_keeps_layout_and_can_retry_after_group_switch(qa_workspace, qt_app, monkeypatch):
    window, view, warnings = qa_workspace
    qa = view.qaController
    view._tool_controller.selectService('service:qa'); wait_qa(qt_app, qa)
    saved = qa.currentResult
    button = qa_control(window, 'recalculateQa')
    assert button.isVisible() and button.isEnabled()
    jobs = []
    monkeypatch.setattr(qa, '_submit', lambda *args: jobs.append(args))
    _click(window, button); QTest.qWait(30)
    assert qa.displayResult == saved and not qa.currentResult
    assert not button.isEnabled()
    qa.analyze()  # Duplicate invocations do not continually replace pending work.
    assert len(jobs) == 1
    assert _find(window, 'waterQaMetric-water_ct_hu').property('text') == '—'
    token, key, *_ = jobs[-1]
    qa._receive_result(token, key, None, 'temporary failure')
    qa.setActiveGroup('noise'); qa.setActiveGroup('uniformity')
    QTest.qWait(30)
    assert qa.error == 'temporary failure'
    assert button.isVisible() and button.isEnabled()
    _click(window, qa_control(window, 'recalculateQa'))
    assert len(jobs) == 2 and qa.status == 'calculating'
    assert qa.displayResult == saved
    token, key, *_ = jobs[-1]
    qa._receive_result(token, key, qa._records[repr(qa._key)]['result'], '')
    QTest.qWait(30)
    assert qa.currentResult == saved and button.isEnabled()
    assert _find(window, 'waterQaMetric-water_ct_hu').property('text') != '—'
    assert not warnings, warnings


@pytest.mark.parametrize('group', ['uniformity', 'noise', 'air'])
def test_initial_failure_is_not_lost_when_switching_group(qa_workspace, qt_app, monkeypatch, group):
    window, view, warnings = qa_workspace
    qa = view.qaController
    jobs = []
    monkeypatch.setattr(qa, '_submit', lambda *args: jobs.append(args))
    view._tool_controller.selectService('service:qa')
    token, key, *_ = jobs[-1]
    qa._receive_result(token, key, None, 'temporary failure')
    qa.setActiveGroup('noise'); qa.setActiveGroup(group)
    QTest.qWait(20)
    assert qa.status == 'error' and qa.error == 'temporary failure'
    button = qa_control(window, 'recalculateQa')
    assert button.isEnabled()
    _click(window, button)
    assert len(jobs) == 2 and qa.status == 'calculating'
    assert not warnings, warnings


def test_retry_recovers_failed_auto_air_without_restoring_user_deleted_circles(qa_view, qt_app, monkeypatch):
    from test_water_qa_controller import deliver_frame, water_render, pump_until
    from test_qa_resize_air import air_image
    from voxplane.ui.controller.viewport.controller import water_qa_controller as module
    view, _ = qa_view
    deliver_frame(view, water_render(view, pixels=air_image()))
    qa = view.qaController
    qa.activate(); wait_qa(qt_app, qa)
    original = module.find_external_air_roi
    def fail(*args):
        raise RuntimeError('temporary air failure')
    monkeypatch.setattr(module, 'find_external_air_roi', fail)
    qa.setActiveGroup('air')
    pump_until(qt_app, lambda: qa.status == 'error')
    monkeypatch.setattr(module, 'find_external_air_roi', original)
    qa.analyze(); wait_qa(qt_app, qa)
    assert len(qa.roiItems) == 1
    assert qa.deleteRoi(qa.roiItems[0]['key'])
    qa.analyze(); wait_qa(qt_app, qa)
    assert not qa.roiItems  # Explicit deletion still wins over auto placement.
