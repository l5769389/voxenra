"""Cine navigation uses real image requests and respects render backpressure."""
import pytest
from voxplane.model import RenderFailure
from test_compare_2d import comparison
from test_pet_fusion import paired_series
from test_dicom_tags import qt_app, wait_until
from test_two_d_layout import open_scene


def settle(tab, view):
    wait_until(lambda: not view.render_pending and not tab._active_mpr_requests
               and not tab._dirty_mpr_viewport_ids and view.loadState == 'ready')


@pytest.mark.parametrize('mode', ['stack', 'axial', 'coronal', 'sagittal'])
def test_2d_playback_wraps_waits_for_frames_and_stops_on_view_switch(comparison, mode):
    app, records = comparison
    tab, layout = open_scene(app, records)
    layout.setMode(0, mode)
    view = tab.activeViewport
    settle(tab, view)
    view.setSliceIndex(view.sliceCount - 1)
    settle(tab, view)
    assert tab.playbackAvailable
    requests = []
    tab.renderRequested.connect(requests.append)
    tab.setPlaying(True)
    tab._phase_timer.stop()  # Deterministic ticks, real asynchronous render worker.
    tab._handle_playback_timeout()
    assert len(requests) == 1
    tab._handle_playback_timeout()
    assert len(requests) == 1
    settle(tab, view)
    assert view.sliceIndex == 0
    tab._handle_playback_timeout()
    settle(tab, view)
    assert view.sliceIndex == 1
    tab.pausePlayback()
    assert not tab._phase_timer.isActive()
    tab._handle_playback_timeout()
    assert view.sliceIndex == 1
    tab.setPlaying(True)
    layout.setMode(0, 'axial' if mode == 'stack' else 'stack')
    assert not tab.playing
    assert not tab._phase_timer.isActive()


def test_mpr_playback_moves_linked_position_and_stops_on_tab_switch(comparison):
    app, records = comparison
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'MPR', 'mpr')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    tab = workspace.activeTab
    view = next(v for v in tab.viewports_by_id.values() if v.viewportType == 'axial')
    tab.activateViewport(view.viewportId)
    settle(tab, view)
    view.setSliceIndex(view.sliceCount - 1)
    settle(tab, view)
    center = tab._target_mpr_state.frame.center_patient
    requests = []
    tab.renderRequested.connect(requests.append)
    tab.setPlaying(True)
    tab._phase_timer.stop()
    tab._handle_playback_timeout()
    assert len(requests) == 3
    tab._handle_playback_timeout()
    assert len(requests) == 3
    settle(tab, view)
    assert view.sliceIndex == 0
    assert tab._target_mpr_state.frame.center_patient != center
    assert all(v._plane_geometry.frame.center_patient == tab._target_mpr_state.frame.center_patient
               for v in tab.viewports_by_id.values())
    workspace.createTab(records[0].series_instance_uid, '2D', '2d')
    assert not tab.playing
    assert not tab._phase_timer.isActive()


def test_single_slice_and_failed_render_cannot_keep_playing(comparison):
    app, records = comparison
    tab, layout = open_scene(app, records)
    view = tab.activeViewport
    tab.setPlaying(True)
    tab._phase_timer.stop()
    tab._handle_playback_timeout()
    tab.handleRenderFailure(RenderFailure(request_id=view._latest_request_id, viewport_id=view.viewportId, error=RuntimeError('decode failed')))
    assert not tab.playing
    assert not view.render_pending
    assert not tab.playbackAvailable
    layout.loadSeries(0, records[2].series_instance_uid)
    settle(tab, tab.activeViewport)
    assert tab.activeViewport.sliceCount == 1
    tab.setPlaying(True)
    assert not tab.playing


@pytest.mark.parametrize('tab_type', ['2d', 'mpr'])
def test_slice_playback_buttons_in_expanded_and_compact_qml(comparison, tab_type, tmp_path):
    from pathlib import Path
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest
    from shiboken6 import delete
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    from test_four_d_qml import _find, _click
    from test_measurement_qml import _visual_children
    app, records = comparison
    app.workspaceController.createTab(records[0].series_instance_uid, tab_type, tab_type)
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
    tab = app.workspaceController.activeTab
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setInitialProperties(dict(toolController=tab.toolController, toolVisible=True,
                                   viewportController=tab.activeViewport, tabController=tab))
    view.resize(280, 760)
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
                                        'src/voxplane/qml/sections/RightPanel.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(30)
    try:
        _click(view, _find(view, 'primaryTool-play'))
        assert tab.playing
        assert _find(view, 'primaryTool-play').parentItem().property('iconName') == 'cine-stop'
        _find(view, 'slicePlaybackPanel')
        assert not any(i.objectName() == 'phaseGrid' and i.isVisible() for i in _visual_children(view.rootObject()))
        _click(view, _find(view, 'phasePlaybackButton'))
        assert not tab.playing
        view.rootObject().setProperty('collapsed', True)
        view.resize(52, 760)
        QTest.qWait(30)
        play = _find(view, 'compactTool-play')
        _click(view, play)
        assert tab.playing
        assert play.parentItem().property('iconName') == 'cine-stop'
        _click(view, play)
        assert not tab.playing
        assert play.parentItem().property('iconName') == 'cine-play'
        view.grabWindow().save(str(tmp_path / f'{tab_type}-compact.png'))
        assert not warnings, warnings
    finally:
        tab.pausePlayback()
        view.hide()
        delete(view)


def test_pet_mpr_playback_waits_for_transactional_batch(qt_app, paired_series):
    from voxplane.ui.controller.workspace_controller import WorkspaceController
    from voxplane.ui.dicom_image_provider import DicomImageProvider
    from voxplane.service.render_serivce import RenderService
    from voxplane.core.volume_manager import VolumeManager
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    service = RenderService(catalog, VolumeManager())
    workspace.renderRequested.connect(service.submit)
    service.rendered.connect(workspace.handleRenderResult)
    service.failed.connect(workspace.handleRenderFailure)
    try:
        workspace.createTab(pet.series_instance_uid, 'PET MPR', 'mpr')
        tab = workspace.activeTab
        wait_until(lambda: tab.ready)
        view = tab.activeViewport
        assert tab.playbackAvailable
        requests = []
        tab.renderRequested.connect(requests.append)
        tab.setPlaying(True)
        tab._phase_timer.stop()
        tab._handle_playback_timeout()
        assert len(requests) == 1
        tab._handle_playback_timeout()
        assert len(requests) == 1
        wait_until(lambda: tab._requested == tab._committed_request)
        tab.pausePlayback()
        assert not tab.playing
    finally:
        workspace.shutdown()
        service.shutdown()
