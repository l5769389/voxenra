"""Recording failures keep editing work intact and offer a visible recovery path."""
import sys

import pytest
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_mpr_voi_controller import setup_voi
from test_segmentation_edit_history import history
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from qt_dicom_viewer.i18n.messages import builtin, localize


@pytest.mark.parametrize('operation', ['signature', 'snapshot'])
def test_memory_failure_preserves_edit_and_history_until_retry(setup_voi, history, monkeypatch, operation):
    import qt_dicom_viewer.ui.controller.edit_history_controller as module
    c, _, _ = setup_voi
    c.newSegment(); QTest.qWait(25)
    history.undo()
    current, undo, redo = history._current, list(history._undo), list(history._redo)
    original = module.edit_signature if operation == 'signature' else module.dumps
    name = 'edit_signature' if operation == 'signature' else 'dumps'
    uncaught = []
    monkeypatch.setattr(sys, 'excepthook', lambda kind, value, tb: uncaught.append(value))
    def fail(*args):
        raise MemoryError()
    monkeypatch.setattr(module, name, fail)
    c.newSegment(); QTest.qWait(25)
    key = c.records[0]['id']
    assert not uncaught
    assert history.error and '内存不足' in history.error
    assert not history.canUndo and not history.canRedo
    assert history._current == current and history._undo == undo and history._redo == redo
    history.redo()
    assert [r['id'] for r in c.records] == [key]
    monkeypatch.setattr(module, name, original)
    history.capture()
    assert not history.error and history.canUndo and not history.canRedo
    history.undo()
    assert c.records == []
    history.redo()
    assert [r['id'] for r in c.records] == [key]


@pytest.mark.parametrize('theme,size', [('dark', (1440, 900)), ('graphite', (1000, 600)), ('light', (1000, 600))])
def test_history_error_visible_in_window_and_retry_restores_undo(sidebar_scene, monkeypatch, theme, size):
    import qt_dicom_viewer.ui.controller.edit_history_controller as module
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    window.resize(*size)
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'History recovery', 'mpr')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    tab = workspace.activeTab
    original = module.dumps
    def fail(*args):
        raise MemoryError()
    monkeypatch.setattr(module, 'dumps', fail)
    tab.voiController.newSegment(); QTest.qWait(40)
    message = find(window, 'historyErrorMessage')
    assert message.isVisible() and '内存不足' in message.property('text')
    assert len(tab.voiController.records) == 1 and not tab.historyController.canUndo
    app.languageController.selectLanguage('en-US'); QTest.qWait(30)
    assert 'memory' in message.property('text').lower()
    assert '撤销' not in message.property('text')
    from PySide6.QtCore import QPointF
    for item in (message, find(window, 'retryHistoryCapture')):
        start = item.mapToScene(QPointF())
        end = item.mapToScene(QPointF(item.width(), item.height()))
        assert 0 <= start.x() < end.x() <= window.width()
        assert 0 <= start.y() < end.y() <= window.height()
    monkeypatch.setattr(module, 'dumps', original)
    click(window, find(window, 'retryHistoryCapture'))
    assert tab.historyController.canUndo and not tab.historyController.error
    assert not message.isVisible()
    tab.historyController.undo()
    assert tab.voiController.records == []
    assert not warnings, warnings


def test_render_memory_failure_has_reason_and_retry_keeps_measurements(qt_app, tmp_path, monkeypatch):
    from test_workspace_persistence import populated_app, draw_length
    app, _ = populated_app(tmp_path)
    try:
        view = app.workspaceController.activeViewport
        mid = draw_length(view)
        loader = app.render_service._worker._stack_loader
        original = loader.load_a_dicom
        def fail(*args, **kwargs):
            raise MemoryError()
        monkeypatch.setattr(loader, 'load_a_dicom', fail)
        view.request_first_loader()
        wait_until(lambda: view.loadState == 'error')
        assert '内存不足' in view.errorMessage
        assert not view.render_pending and not app.render_service._active
        assert mid in view._measure_controller._measurements
        app.languageController.selectLanguage('en-US')
        assert 'memory' in view.errorMessage.lower()
        monkeypatch.setattr(loader, 'load_a_dicom', original)
        view.request_first_loader()
        wait_until(lambda: view.loadState == 'ready')
        assert mid in view._measure_controller._measurements
    finally:
        app.shutdown()
