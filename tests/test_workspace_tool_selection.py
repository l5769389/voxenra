"""Workspace selections are state, never commands or calculation requests."""
import pytest
from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app


@pytest.mark.parametrize('tool,secondary', [
    ('measure', 'measure:curve'), ('measure', 'measure:freehand'),
    ('annotate', 'annotate:text'), ('service', 'service:mtf'),
    ('service', 'service:fwhm'), ('service', 'service:qa'), ('play', ''), ('export', '')])
def test_selection_roundtrip_without_actions(qt_app, tool, secondary):
    original = ToolController(tab_type=TabType.TWO_D, modality='CT')
    original.activateTool(tool)
    if secondary:
        original.selectInteraction(secondary)
    restored = ToolController(tab_type=TabType.TWO_D, modality='CT')
    actions, notifications = [], []
    restored.commandRequested.connect(actions.append)
    restored.serviceSelected.connect(actions.append)
    restored.resetRequested.connect(actions.append)
    restored.activeToolChanged.connect(lambda: notifications.append((restored.restoring_selection, restored.activeInteraction)))
    restored.restore_selection(original.persistent_selection())
    assert restored.persistent_selection() == original.persistent_selection()
    assert not actions
    assert notifications == [(True, secondary)]
    assert not restored.restoring_selection


def test_legacy_unavailable_and_command_tools(qt_app):
    tools = ToolController(tab_type=TabType.TWO_D, modality='CT')
    actions = []
    tools.commandRequested.connect(actions.append)
    tools.restore_selection(legacy_tool='measure')
    assert tools.activeInteraction == 'measure:length'
    before = tools.persistent_selection()
    for value in ('reset', 'volume-bed', 'delete', None, []):
        tools.restore_selection(dict(version=1, tool=value))
        assert tools.persistent_selection() == before
    tools.restore_selection(dict(version=1, tool='measure', interaction='service:qa', panel='export'))
    assert tools.activeInteraction == 'measure:length' and tools.activePanel == 'measure'
    assert not actions
    mr = ToolController(tab_type=TabType.TWO_D, modality='MR')
    mr.restore_selection(dict(version=1, tool='service', service='service:qa'))
    assert mr.activeTool == 'window'


@pytest.mark.parametrize('tool,secondary', [('measure', 'measure:curve'), ('service', 'service:fwhm'), ('service', 'service:qa'), ('play', '')])
def test_workspace_reopens_selected_tool_without_analysis_or_playback(qt_app, tmp_path, monkeypatch, tool, secondary):
    app, _ = populated_app(tmp_path)
    try:
        tab = app.workspaceController.activeTab
        tools = tab.toolController
        # QA activation must not run during selection restoration, even when no saved result exists.
        qa_type = type(tab.activeViewport._qa_controller)
        calls = []
        monkeypatch.setattr(qa_type, 'activate', lambda self: calls.append('qa'))
        tools.activateTool(tool)
        if secondary:
            tools.selectInteraction(secondary)
        if tool == 'play':
            tab.setPlaying(True)
            assert tab.playing
        saved = tools.persistent_selection()
        manager = app.workspaceDocumentController
        path = tmp_path / 'tools.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        tab.pausePlayback()
        calls.clear()
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        restored = app.workspaceController.activeTab
        assert restored.toolController.persistent_selection() == saved
        assert not restored.playing and not restored._phase_timer.isActive()
        assert not calls
        assert not manager.dirty
        restored.toolController.activateTool('measure')
        restored.toolController.selectInteraction('measure:ellipse')
        assert manager.dirty
    finally:
        app.shutdown()
