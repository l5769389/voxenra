"""Cine state boundaries across loading, queued phases, layouts and restoration."""
import pytest
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
from test_dicom_tags import qt_app
from test_four_d_qml import _controller
from test_four_d import _ready_four_d_tab, _finish_requests
from test_four_d_tools import temporal, draw
from test_compare_2d import comparison
from test_two_d_layout import open_scene
from test_slice_playback import settle
from test_series_sidebar import sidebar_scene


def test_four_d_cannot_play_without_loaded_frames(qt_app):
    tab = _controller()
    try:
        assert not tab.playbackAvailable
        tab.togglePlaybackMode('phase')
        assert not tab.playing and not tab._phase_timer.isActive()
        assert tab.toolController._locked_tool is None
    finally:
        tab.dispose()


def test_stop_discards_queued_phase_and_slice_cine_waits_for_commit(qt_app):
    tab, requests, frame = _ready_four_d_tab()
    try:
        tab.setPlaying(True)
        tab._phase_timer.stop()
        tab._handle_playback_timeout()
        tab.setPhaseIndex(2)
        assert tab._rendering_phase_index == 1 and tab._pending_phase_index == 2
        tab.pausePlayback()
        assert tab._pending_phase_index is None
        assert not tab.slicePlaybackAvailable
        tab.togglePlaybackMode('slice')
        assert not tab.playing
        _finish_requests(tab, requests, frame)
        assert tab.currentPhaseIndex == 1  # Finish only the already submitted frame.
        assert not tab.playing and not requests
        assert tab.slicePlaybackAvailable
        tab.togglePlaybackMode('slice')
        assert tab.playing
    finally:
        tab.dispose()


@pytest.mark.parametrize('mode', ['slice', 'phase'])
def test_restore_retains_mode_but_never_restarts_timer(temporal, mode):
    tab, _, _ = temporal
    tab.togglePlaybackMode(mode)
    saved = tab_snapshot(tab)
    tab.pausePlayback()
    tab.togglePlaybackMode('phase' if mode == 'slice' else 'slice')
    apply_tab_snapshot(tab, saved)
    assert not tab.playing and not tab._phase_timer.isActive()
    assert tab.playbackMode == mode
    assert tab.toolController._locked_tool is None
    assert tab.mprLayout.volumeTools._locked_tool is None


@pytest.mark.parametrize('mode', ['slice', 'phase'])
@pytest.mark.parametrize('action', ['focus', 'layout', 'viewport', 'close'])
def test_four_d_layout_and_tool_combinations(temporal, mode, action, monkeypatch):
    tab, _, (_, workspace) = temporal
    tab.mprLayout.setLayout('quad')
    region = draw(tab, 'segmentation')
    tab.togglePlaybackMode(mode)
    tab._phase_timer.stop()
    original = tab.toolController.activeTool
    for tool in ('window', 'segmentation', 'voi', 'reset', 'mpr-layout'):
        tab.toolController.activateTool(tool)
        assert tab.toolController.activeTool == original
    if action == 'focus':
        tab.focusSingleViewport(tab.activeViewport.viewportId)
        assert tab.playing  # Same slice; only its display size changes.
        tab.focusSingleViewport('')
        assert tab.playing
    elif action == 'layout':
        tab.mprLayout.setLayout('rows')
        assert tab.playing and tab.activeViewport.viewportType != 'volume'
    elif action == 'viewport':
        tab.mprLayout.activate()
        assert not tab.playing and tab.toolController._locked_tool is None
        assert tab.mprLayout.volumeTools._locked_tool is None
    else:
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Close)
        workspace.closeTab(tab.tab_config.tab_id)
        assert not tab.playing and not tab._phase_timer.isActive()
    assert any(r['id'] == region for r in tab.voiController.records)


@pytest.mark.parametrize('mode', ['stack', 'axial', 'coronal', 'sagittal'])
def test_2d_empty_cell_and_hidden_cell_stop_playback(comparison, mode):
    app, records = comparison
    tab, layout = open_scene(app, records)
    layout.setLayout('1x2')
    layout.setMode(0, mode)
    settle(tab, tab.activeViewport)
    tab.setPlaying(True)
    layout.activateCell(1)
    assert not tab.playing and tab.activeViewport is None
    layout.loadSeries(1, records[0].series_instance_uid)
    settle(tab, tab.activeViewport)
    tab.setPlaying(True)
    layout.setLayout('1x1')
    assert not tab.playing and layout.activeCell == 0
    assert tab.toolController._locked_tool is None


@pytest.mark.parametrize('tab_type', ['2d', 'mpr'])
def test_mr_playback_preserves_window_and_stops_on_restore(comparison, tmp_path, tab_type):
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from test_mr import write_mr_series
    from test_dicom_tags import wait_until
    app, _ = comparison
    series = write_mr_series(tmp_path / 'mr')
    snapshot = DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series])
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    workspace = app.workspaceController
    workspace.createTab(series.series_instance_uid, 'MR', tab_type)
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    tab = workspace.activeTab
    view = tab.activeViewport
    settle(tab, view)
    view.applyWindowPreset(100, 300)
    settle(tab, view)
    window = view.current_window
    saved = tab_snapshot(tab)
    view.setSliceIndex(view.sliceCount - 1)
    settle(tab, view)
    tab.setPlaying(True)
    tab._phase_timer.stop()
    assert tab.playing
    tab._handle_playback_timeout()
    settle(tab, view)
    assert view.sliceIndex == 0 and view.current_window == window
    tab.setFps(12)
    assert tab.playing
    apply_tab_snapshot(tab, saved)
    assert not tab.playing and not tab._phase_timer.isActive()
    assert tab.toolController._locked_tool is None


@pytest.mark.parametrize('mode', ['slice', 'phase'])
def test_restored_fps_matches_timer_interval(temporal, mode):
    tab, _, _ = temporal
    tab.setFps(12)
    tab.togglePlaybackMode(mode)
    saved = tab_snapshot(tab)
    tab.pausePlayback()
    tab.setFps(2)
    apply_tab_snapshot(tab, saved)
    tab.setPlaying(True)
    assert tab.playing and tab.fps == 12
    assert tab._phase_timer.interval() == round(1000 / 12)


def test_window_transfer_stops_playback_and_releases_tools(sidebar_scene):
    from test_tab_windows import open_tabs, detached
    from test_dicom_tags import wait_until
    _, app, records, warnings = sidebar_scene
    tab = open_tabs(app, records[:1])[0]
    tab.setPlaying(True)
    assert tab.playing
    session, _ = detached(app, tab)
    assert not tab.playing and tab.toolController._locked_tool is None
    tab.setPlaying(True)
    assert tab.playing
    app.windowManager.moveToMain(tab.tab_config.tab_id)
    wait_until(lambda: session.windowId not in app.windowManager.sessions)
    assert not tab.playing and not tab._phase_timer.isActive()
    assert tab.toolController._locked_tool is None
    assert not warnings, warnings


@pytest.mark.parametrize('mode', ['slice', 'phase'])
def test_play_shortcut_toggles_current_four_d_mode(temporal, mode):
    from qt_dicom_viewer.ui.controller.shortcut_controller import ShortcutController
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    tab, _, _ = temporal
    shortcuts = ShortcutController(SettingsController(path=False))
    tab.togglePlaybackMode(mode)
    assert tab.playing
    assert shortcuts.activate('play', tab.toolController, tab)
    assert not tab.playing and not tab._phase_timer.isActive()
    assert shortcuts.activate('play', tab.toolController, tab)
    assert tab.playing and tab.playbackMode == mode
    assert tab.toolController.activeTool == ('slice-play' if mode == 'slice' else 'play')


def test_four_d_play_shortcut_uses_phase_on_reference_viewport(temporal):
    from qt_dicom_viewer.ui.controller.shortcut_controller import ShortcutController
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    tab, _, _ = temporal
    shortcuts = ShortcutController(SettingsController(path=False))
    tab.mprLayout.setLayout('quad')
    tab.togglePlaybackMode('slice')
    assert tab.playing
    tab.mprLayout.activate()
    assert not tab.playing and tab.activeViewport.viewportType == 'volume'
    assert shortcuts.activate('play', tab.activeToolController, tab)
    assert tab.playing and tab.playbackMode == 'phase'
    assert shortcuts.activate('play', tab.activeToolController, tab)
    assert not tab.playing
