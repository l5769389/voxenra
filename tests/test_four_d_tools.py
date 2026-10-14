"""4D slice cine and phase-scoped quantitative regions use actual phase pixels."""
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.model import DicomFolderScanSnapshot, RenderFailure
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
from test_four_d import _cross_series_four_d
from test_dicom_tags import qt_app
from test_four_d_qml import _find, _click
from test_measurement_qml import _visual_children
from test_mpr_voi_qml import settle


@pytest.fixture
def temporal(qt_app, tmp_path):
    records = _cross_series_four_d(tmp_path)
    catalog = SeriesCatalog()
    catalog.update(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records))
    owner = QObject()
    owner._settings_controller = SettingsController(owner, path=False)
    workspace = WorkspaceController(catalog, DicomImageProvider(), owner)
    worker = DicomRenderWorker(catalog, VolumeManager())
    failures, requests = [], []
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(failures.append)
    workspace.renderRequested.connect(requests.append)
    workspace.renderRequested.connect(worker.handleRenderRequest)
    workspace.createTab(records[0].series_instance_uid, '4D', '4d')
    tab = workspace.activeTab
    assert tab.currentPhaseIndex == 0 and not failures
    yield tab, requests, (worker, workspace)
    assert not failures
    workspace.shutdown()


def draw(tab, kind):
    tab.toolController.activateTool(kind)
    v = tab.activeViewport
    c = tab.voiController
    c.begin(v, .5, .5, .1)
    c.finish(v, 2.5, 1.5)
    if kind == 'segmentation':
        c.setThreshold(5)
    settle(c)
    assert c.selectedId in c.evaluations
    return c.selectedId


def test_measurement_location_switches_phase_before_exposing_regions(temporal):
    from test_workspace_persistence import draw_length

    tab, _, _ = temporal
    view = tab.activeViewport
    mid = draw_length(view)
    frame = view.measurementController.frame_key
    listing = tab.measurementResults
    key = listing.items[0]['key']
    first_region = draw(tab, 'voi')
    tab.setPhaseIndex(1)
    second_region = draw(tab, 'voi')
    controller = tab.voiController
    assert controller.evaluations[second_region].metrics['mean'] == 20

    listing.locate(key)
    settle(controller)

    assert tab.currentPhaseIndex == controller.phaseIndex == 0
    assert view.measurementController.selectedMeasurementId == mid
    assert view.measurementController.frame_key == frame
    assert all(v._voi_phase == 0 and (v._voi_volume.modality_pixels == 10).all()
               for v in tab.viewports_by_id.values())
    assert [r['id'] for r in controller.current_records] == [first_region]
    assert controller.evaluations[first_region].metrics['mean'] == 10
    tab.setPhaseIndex(1)
    settle(controller)
    assert [r['id'] for r in controller.current_records] == [second_region]
    assert controller.evaluations[second_region].metrics['mean'] == 20


def test_failed_measurement_phase_location_restores_current_region_source(temporal):
    from test_workspace_persistence import draw_length

    tab, requests, (worker, workspace) = temporal
    draw_length(tab.activeViewport)
    listing = tab.measurementResults
    key = listing.items[0]['key']
    tab.setPhaseIndex(1)
    region = draw(tab, 'voi')
    controller = tab.voiController
    workspace.renderRequested.disconnect(worker.handleRenderRequest)
    first = len(requests)
    listing.locate(key)
    assert not controller._phase_ready
    failed = requests[first]
    workspace.handleRenderFailure(RenderFailure(request_id=failed.request_id,
        viewport_id=failed.viewport_id, error=RuntimeError('measurement phase failure')))
    cursor = first + 1
    while cursor < len(requests):
        assert cursor - first < 20, 'Phase recovery did not settle'
        worker.handleRenderRequest(requests[cursor])
        cursor += 1
    settle(controller)
    assert tab.currentPhaseIndex == controller.phaseIndex == 1
    assert all((v._voi_volume.modality_pixels == 20).all()
               for v in tab.viewports_by_id.values())
    assert controller.evaluations[region].metrics['mean'] == 20
    assert not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids


def test_locating_displayed_measurement_supersedes_inflight_phase(temporal):
    from test_workspace_persistence import draw_length

    tab, requests, (worker, workspace) = temporal
    view = tab.activeViewport
    mid = draw_length(view)
    listing = tab.measurementResults
    key = listing.items[0]['key']
    workspace.renderRequested.disconnect(worker.handleRenderRequest)
    first = len(requests)
    tab.setPhaseIndex(1)
    # The old phase is still displayed, but locating it must supersede the
    # outstanding phase change instead of selecting a soon-to-disappear item.
    listing.locate(key)
    cursor = first
    while cursor < len(requests):
        assert cursor - first < 20, 'Measurement location did not settle'
        worker.handleRenderRequest(requests[cursor])
        cursor += 1
    assert tab.currentPhaseIndex == tab.voiController.phaseIndex == 0
    assert view.measurementController.selectedMeasurementId == mid
    assert all((v._voi_volume.modality_pixels == 10).all()
               for v in tab.viewports_by_id.values())


def test_phase_selection_after_measurement_location_wins(temporal):
    from test_workspace_persistence import draw_length

    tab, requests, (worker, workspace) = temporal
    draw_length(tab.activeViewport)
    listing = tab.measurementResults
    key = listing.items[0]['key']
    tab.setPhaseIndex(1)
    workspace.renderRequested.disconnect(worker.handleRenderRequest)
    first = len(requests)
    listing.locate(key)
    tab.setPhaseIndex(2)
    cursor = first
    while cursor < len(requests):
        assert cursor - first < 20, 'Phase selection did not settle'
        worker.handleRenderRequest(requests[cursor])
        cursor += 1
    assert tab.currentPhaseIndex == tab.voiController.phaseIndex == 2
    assert all((v._voi_volume.modality_pixels == 30).all()
               for v in tab.viewports_by_id.values())
    assert not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids


def test_current_phase_playback_scrolls_only_slices_and_modes_switch(temporal):
    tab, requests, _ = temporal
    view = tab.activeViewport
    view.setSliceIndex(view.sliceCount - 1)
    before = len(requests)
    tab.togglePlaybackMode('slice')
    tab._phase_timer.stop()
    assert tab.playing and tab.toolController.activeTool == 'slice-play'
    tab._handle_playback_timeout()
    assert view.sliceIndex == 0 and tab.currentPhaseIndex == 0
    assert len(requests) > before and all(r.phase_identifier == 0 for r in requests[before:])
    tab.togglePlaybackMode('phase')
    assert tab.playing and tab.playbackMode == 'slice'
    tab.togglePlaybackMode('slice')
    assert not tab.playing
    tab.togglePlaybackMode('phase')
    tab._phase_timer.stop()
    assert tab.playing and tab.toolController.activeTool == 'play'
    tab._handle_playback_timeout()
    assert tab.currentPhaseIndex == 1
    tab.togglePlaybackMode('slice')
    assert tab.playbackMode == 'phase'
    tab.pausePlayback()
    tab.togglePlaybackMode('slice')
    tab._phase_timer.stop()
    tab.setPhaseIndex(2)
    assert not tab.playing and tab.currentPhaseIndex == 2
    tab.mprLayout.setLayout('quad')
    tab.mprLayout.activate()
    tab.togglePlaybackMode('slice')
    assert not tab.playing
    tab.togglePlaybackMode('phase')
    assert tab.playing
    tab.pausePlayback()


def test_regions_are_isolated_per_phase_and_restore_with_workspace(temporal):
    tab, _, _ = temporal
    c = tab.voiController
    zero = draw(tab, 'segmentation')
    assert c.evaluations[zero].metrics['mean'] == pytest.approx(10)
    tab.setPhaseIndex(1)
    assert not c.items and not tab.activeViewport.voiMasks
    one = draw(tab, 'voi')
    assert c.evaluations[one].metrics['mean'] == pytest.approx(20)
    saved = tab_snapshot(tab)
    assert {r['phase'] for r in saved['edits']['voi']} == {0, 1}
    tab.setPhaseIndex(0)
    settle(c)
    assert [r['id'] for r in c.items] == [zero]
    assert c.evaluations[zero].metrics['mean'] == pytest.approx(10)
    c.clear('')
    assert not c.items and [r['id'] for r in c.records] == [one]
    apply_tab_snapshot(tab, saved)
    settle(c)
    assert tab.currentPhaseIndex == 1
    assert [r['id'] for r in c.items] == [one]
    assert c.evaluations[one].metrics['mean'] == pytest.approx(20)
    tab.setPhaseIndex(0)
    settle(c)
    assert [r['id'] for r in c.items] == [zero]


def test_late_quantitative_result_cannot_leak_into_another_phase(temporal):
    tab, _, _ = temporal
    c = tab.voiController
    zero = draw(tab, 'segmentation')
    revision = c._revision
    result = c.evaluations[zero]
    tab.setPhaseIndex(1)
    c._accept((revision, {zero: result}, ''))
    assert not c.items and zero not in c.evaluations
    assert not tab.activeViewport.voiOverlays and not tab.activeViewport.voiMasks


def test_four_d_buttons_and_consistent_footer_in_real_qml(temporal):
    tab, _, _ = temporal
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(280, 850)
    view.setInitialProperties(dict(toolController=tab.toolController, viewportController=tab.activeViewport,
        toolVisible=True, tabController=tab))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/RightPanel.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(60)
    try:
        footer = _find(view, 'toolResetBar')
        assert footer.height() == 40
        for tool in ('window', 'zoom', 'segmentation', 'voi', 'export'):
            _click(view, _find(view, 'primaryTool-' + tool))
            assert footer.height() == 40
            visible = [i.objectName() for i in _visual_children(view.rootObject()) if i.isVisible()]
            assert ('activeToolReset' in visible) == (tool in ('window', 'zoom'))
            if tool in ('segmentation', 'voi'):
                button = _find(view, 'voiClearAll')
                assert not button.isEnabled() and button.height() == 32
                assert button.property('baseBorderWidth') == 1
                assert _find(view, 'voiPhaseScope')
        for compact in (False, True):
            view.rootObject().setProperty('collapsed', compact)
            view.resize(52 if compact else 280, 850)
            QTest.qWait(40)
            prefix = 'compactTool-' if compact else 'primaryTool-'
            slice_button = _find(view, prefix + 'slice-play')
            phase_button = _find(view, prefix + 'play')
            _click(view, slice_button)
            assert tab.playing and tab.playbackMode == 'slice'
            assert slice_button.parentItem().property('iconName') == 'cine-stop'
            assert phase_button.parentItem().property('iconName') == 'cine-4d-play'
            assert not phase_button.isEnabled() and slice_button.isEnabled()
            _click(view, phase_button)
            assert tab.playing and tab.playbackMode == 'slice'
            _click(view, slice_button)
            assert not tab.playing and phase_button.isEnabled()
            _click(view, phase_button)
            assert tab.playing and tab.playbackMode == 'phase'
            assert phase_button.parentItem().property('iconName') == 'cine-4d-stop'
            assert not slice_button.isEnabled() and phase_button.isEnabled()
            _click(view, slice_button)
            assert tab.playing and tab.playbackMode == 'phase'
            _click(view, phase_button)
            assert not tab.playing and slice_button.isEnabled()
        assert not warnings, warnings
    finally:
        tab.pausePlayback()
        view.hide()
        delete(view)


def test_failed_phase_restores_region_and_source_pixels(temporal):
    tab, requests, (worker, workspace) = temporal
    c = tab.voiController
    zero = draw(tab, 'segmentation')
    workspace.renderRequested.disconnect(worker.handleRenderRequest)
    requests.clear()
    tab.setPhaseIndex(1)
    failed = requests.pop(0)
    assert not c._phase_ready and not tab.activeViewport.voiMasks
    tab.handleRenderFailure(RenderFailure(request_id=failed.request_id,
        viewport_id=failed.viewport_id, error=RuntimeError('injected phase failure')))
    # Drain outstanding phase-1 work and the recovery requests it releases.
    while requests:
        worker.handleRenderRequest(requests.pop(0))
    settle(c)
    assert tab.currentPhaseIndex == c.phaseIndex == 0
    assert c._phase_ready and not tab._active_mpr_requests
    assert [r['id'] for r in c.items] == [zero]
    assert c.evaluations[zero].metrics['mean'] == pytest.approx(10)
    assert tab.activeViewport.voiMasks


def test_four_d_optimized_volume_presets_and_regions_survive_restore(temporal):
    tab, _, _ = temporal
    region = draw(tab, 'segmentation')
    tab.mprLayout.setLayout('quad')
    volume = tab.mprLayout.volumeViewport
    assert volume.currentPresetId == 'aaa'
    assert len(volume.volumePresets) == 20
    windows = [(v.windowCenter, v.windowWidth) for v in tab.viewports_by_id.values()]
    volume.applyVolumePreset('cardiac')
    volume.applyWindowPreset(175, 450)
    volume.setZoom(1.4)
    display, camera = volume.display_state, volume.state
    tab.setPhaseIndex(1)
    assert volume.display_state == display and volume.state == camera
    assert not tab.voiController.items
    saved = tab_snapshot(tab)
    volume.reset_all_view_state()
    assert volume.currentPresetId == 'aaa'
    assert [(v.windowCenter, v.windowWidth) for v in tab.viewports_by_id.values()] == windows
    apply_tab_snapshot(tab, saved)
    assert volume.display_state == display and volume.state == camera
    tab.setPhaseIndex(0)
    settle(tab.voiController)
    assert tab.voiController.evaluations[region].metrics['mean'] == pytest.approx(10)
    assert volume.display_state == display
