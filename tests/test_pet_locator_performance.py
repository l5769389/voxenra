"""Locator transactions, pixel reuse, and explicit modality-window gestures."""
from threading import Event
from time import monotonic

import numpy as np
import pytest
from PySide6.QtCore import QPointF

from test_pet_fusion import paired_series
from test_pet_volume import fusion_scene
from test_measurement_qml import qt_app
from test_dicom_tags import wait_until
from qt_dicom_viewer.model import RenderFailure
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.service.render_serivce import RenderService
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider


@pytest.mark.parametrize("role", ["ct", "pet", "fusion", "mip"])
def test_rotation_takes_precedence_over_pet_locator(fusion_scene, role):
    _, tab, _, requests = fusion_scene
    view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == role)
    view.setViewportSize(400, 400)
    tab.toolController.activateTool("rotate")
    point = view.crosshairImagePosition
    original = tab._target_mpr_state
    before_requests = len(requests)
    assert not view.captureLocatorPress(200, 200, 1, True, point.x(), point.y(), .1, .1)
    view.beginInteraction(200, 200, 1, True, point.x(), point.y(), .1, .1)
    for current in (QPointF(300, 200), QPointF(270, 270)):
        view.updateInteraction(QPointF(200, 200), current, QPointF(),
                               current - QPointF(200, 200), True, point.x(), point.y())
    view.endInteraction(270, 270, True, point.x(), point.y())
    assert view.rotationDegrees == pytest.approx(45)
    assert view._locator_drag is None
    assert tab._target_mpr_state == original
    assert len(requests) == before_requests


def test_pet_mip_tap_in_rotation_mode_keeps_patient_location(fusion_scene):
    _, tab, _, _ = fusion_scene
    view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "mip")
    tab.toolController.activateTool("rotate")
    original = tab._target_mpr_state
    view.selectMeasurementAt(True, 0, 0, .1, .1)
    assert tab._target_mpr_state == original


@pytest.mark.parametrize("tool", ["ct-window", "pet-window"])
@pytest.mark.parametrize("role", ["ct", "pet", "fusion", "mip"])
def test_window_tool_changes_only_eligible_modality(fusion_scene, tool, role):
    workspace, tab, renderer, requests = fusion_scene
    view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == role)
    tab.toolController.activateTool(tool)
    ct, pet = tab._ct_window, tab.pet_display.target.window
    # Explicitly miss the locator and exercise the ordinary drag dispatch.
    view.beginInteraction(100, 100, 1, True, .1, .1, .001, .001)
    view.updateInteraction(QPointF(100, 100), QPointF(140, 120), QPointF(40, 20), QPointF(40, 20), True, .3, .2)
    view.endInteraction(140, 120, True, .3, .2)
    eligible = role in (("ct", "fusion") if tool == "ct-window" else ("pet", "fusion", "mip"))
    assert (tab._ct_window != ct) == (eligible and tool == "ct-window")
    assert (tab.pet_display.target.window != pet) == (eligible and tool == "pet-window")
    workspace.handleRenderResult(renderer.render(requests[-1]))
    # Reset the selected tool must not reset the other modality or palette.
    tab.setCtWindow(300, 800)
    tab.pet_display.set_upper(2)
    tab.setFusionColorMap("hotMetal")
    ct, pet = tab._ct_window, tab.pet_display.target
    tab.toolController.resetActiveTool()
    assert tab.fusionColorMap == "hotMetal"
    if tool == "ct-window":
        assert tab._ct_window == tab._last_result.ct_volume.default_window
        assert tab.pet_display.target == pet
    else:
        assert tab._ct_window == ct and tab.pet_display.target == tab.pet_display.baseline


def test_switching_window_tool_ends_old_operation(fusion_scene):
    _, tab, _, _ = fusion_scene
    view = tab.activeViewport
    view.beginInteraction(100, 100, 1, True, .1, .1, .001, .001)
    assert view._active_drag_operation is not None
    tab.toolController.activateTool("pet-window")
    ct, pet = tab._ct_window, tab.pet_display.target
    view.updateInteraction(QPointF(100, 100), QPointF(140, 120), QPointF(40, 20), QPointF(40, 20), True, .3, .2)
    view.endInteraction(140, 120, True, .3, .2)
    assert tab._ct_window == ct and tab.pet_display.target == pet


def test_same_plane_locator_reuses_pixels_textures_roi_and_mip(fusion_scene, monkeypatch):
    workspace, tab, renderer, requests = fusion_scene
    # Populate the provider as well as the viewport controllers.
    workspace.handleRenderResult(renderer.render(requests[-1]))
    original = tab._last_result
    sources = {v.viewportId: v.imageSource for v in tab.viewports_by_id.values()}
    image_keys = {key: image.cacheKey() for key, image in workspace._image_provider._images.items()}
    calls = {"samples": 0, "mip": 0, "roi": 0, "validate": 0}
    def count(obj, name, key):
        method = getattr(obj, name)
        def wrapper(*args, **kwargs):
            calls[key] += 1
            return method(*args, **kwargs)
        monkeypatch.setattr(obj, name, wrapper)
    count(renderer.reslicer, "_sample_plane", "samples")
    count(renderer, "_full_mip", "mip")
    count(renderer.volumes, "get_or_build", "validate")
    for v in tab.viewports_by_id.values():
        count(v.measurementController, "refresh_roi_metrics", "roi")
    tab.begin_locator_drag()
    center = np.array(original.state.frame.center_patient)
    for offset in (.1, .2, .3, .4):
        tab.move_center(tuple(center + [offset, offset, 0]))
        tab._submit_locator()  # Force deterministic samples without wall-clock waits.
        result = renderer.render(requests[-1])
        workspace.handleRenderResult(result)
        for before, after in zip(original.frames, result.frames):
            assert after.image is before.image and after.modality_pixel is before.modality_pixel
            assert after.content_key == before.content_key
    assert calls == {"samples": 0, "mip": 0, "roi": 0, "validate": 2}
    assert {v.viewportId: v.imageSource for v in tab.viewports_by_id.values()} == sources
    assert {key: image.cacheKey() for key, image in workspace._image_provider._images.items()} == image_keys
    tab.finish_locator_drag()
    workspace.handleRenderResult(renderer.render(requests[-1]))
    assert calls["validate"] == 4  # final always rechecks both source fingerprints
    # A real sub-voxel plane change must sample new, quantitatively correct pixels.
    tab.move_center(tuple(center + [0, 0, .37]))
    result = renderer.render(requests[-1])
    workspace.handleRenderResult(result)
    assert calls["samples"] == 2 and calls["mip"] == 0
    assert calls["roi"] == 2  # PET and fusion, never unchanged MIP
    for frame in result.frames[:3]:
        volume = result.ct_volume if frame.viewport_id == result.frames[0].viewport_id else result.pet_volume
        expected = renderer.reslicer._sample_plane(volume, frame.plane_geometry)
        np.testing.assert_allclose(frame.modality_pixel, expected, equal_nan=True)
    assert result.frames[-1].image is original.frames[-1].image


@pytest.mark.parametrize("role", ["ct", "pet", "fusion", "mip"])
def test_slow_worker_never_delays_or_rewinds_locator(qt_app, paired_series, monkeypatch, role):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    service = RenderService(catalog, VolumeManager())
    workspace.renderRequested.connect(service.submit)
    service.rendered.connect(workspace.handleRenderResult)
    service.failed.connect(workspace.handleRenderFailure)
    entered, release, entered_second, release_second = Event(), Event(), Event(), Event()
    render = service._worker._pet_reconstructor.render
    reads = []
    def held(request):
        if getattr(request, "interaction_kind", "") == "locator":
            reads.append(request)
            if len(reads) == 1:
                entered.set()
                assert release.wait(10)
            elif len(reads) == 2:
                entered_second.set()
                assert release_second.wait(10)
        return render(request)
    monkeypatch.setattr(service._worker._pet_reconstructor, "render", held)
    try:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        tab = workspace.activeTab
        # Cold volume loading on a shared Windows runner is setup, not locator
        # latency. Keep the 33 ms interaction assertion below independent of it.
        wait_until(lambda: tab.ready, timeout=10_000)
        view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == role)
        point = view.crosshairImagePosition
        view.beginInteraction(0, 0, 1, True, point.x(), point.y(), .01, .01)
        view.updateRegistrationDrag(point.x()+.6, point.y()+.6)
        wait_until(entered.is_set)
        starts = []
        for i in range(80):
            start = monotonic()
            view.updateRegistrationDrag(point.x()+.6+i*.002, point.y()+.6)
            starts.append((monotonic()-start)*1000)
        target = tab._target_mpr_state
        for linked in tab.viewports_by_id.values():
            if linked.viewportRole != "mip":
                assert linked._mpr_state == target
        assert np.percentile(starts, 95) < 33
        wait_until(lambda: bool(service._pending))
        assert len(service._pending) == 1 and len(reads) == 1
        release.set()
        wait_until(entered_second.is_set)
        wait_until(lambda: tab._presented_revision == reads[0].revision)
        assert tab._target_mpr_state == target
        view.endInteraction(0, 0, True, point.x()+.85, point.y()+.6)
        final = tab._target_mpr_state
        release_second.set()
        wait_until(lambda: tab._requested == tab._committed_request)
        assert tab._target_mpr_state == final
        assert tab._committed_request.interaction_final and not tab._committed_request.preview
    finally:
        release.set()
        release_second.set()
        service.shutdown()
        workspace.shutdown()


@pytest.mark.parametrize("change", ["tool", "plane", "close", "failure"])
def test_locator_context_end_and_failure_rollback(fusion_scene, change):
    workspace, tab, renderer, requests = fusion_scene
    original = tab._last_result
    view, center = tab.activeViewport, tab.activeViewport.crosshairImagePosition
    view.beginInteraction(0, 0, 1, True, center.x(), center.y(), .01, .01)
    view.updateRegistrationDrag(center.x()+.3, center.y()+.3)
    stale = renderer.render(requests[-1])
    if change == "tool":
        tab.toolController.activateTool("pet-window")
        assert requests[-1].interaction_final
        workspace.handleRenderResult(renderer.render(requests[-1]))
    elif change == "plane": tab.setPlane("coronal")
    elif change == "close": workspace.closeTab(tab._tab_config.tab_id)
    else:
        view.endInteraction(0, 0, True, center.x()+.5, center.y()+.5)
        workspace.handleRenderFailure(RenderFailure(request_id=requests[-1].request_id,
            viewport_id=requests[-1].viewport_id, error=ValueError("source changed")))
        assert tab._target_mpr_state == original.state and "source changed" in tab.warning
    assert not tab.accepts_render_result(stale)
    assert not tab._locator_timer.isActive() and not tab._locator_dragging
    assert view._locator_drag is None


def test_locator_submissions_are_throttled_and_release_flushes(fusion_scene, monkeypatch):
    _, tab, _, requests = fusion_scene
    import qt_dicom_viewer.ui.controller.tab.pet_workspace_controller as module
    clock = [100.]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    submitted = []
    tab.renderRequested.connect(lambda request: submitted.append((clock[0], request)))
    tab.begin_locator_drag()
    center = np.array(tab._target_mpr_state.frame.center_patient)
    for i in range(100):
        clock[0] = 100+i*.001
        tab.move_center(tuple(center+[i*.001, 0, 0]))
    times = [t for t, _ in submitted]
    assert len(times) == 4
    assert all(b-a >= .033 for a, b in zip(times, times[1:]))
    clock[0] += .001
    tab.finish_locator_drag()
    assert len(submitted) == 5 and requests[-1].interaction_final
    assert requests[-1].state == tab._target_mpr_state
    assert not tab._locator_timer.isActive()


def test_registration_status_only_describes_actual_edits(fusion_scene):
    _, tab, _, _ = fusion_scene
    assert tab.registrationStatus == ""
    tab.setRegistrationActive(True)
    assert tab.registrationStatus == ""
    tab.begin_registration_drag()
    tab.setRegistrationParameter(0, 1.)
    assert tab.registrationStatus == "配准调整中"
    assert all("registration" not in v.overlayInfo for v in tab.viewports_by_id.values())
    tab.finishRegistrationPreview()
    assert tab.registrationStatus == "已手动调整"
    tab.resetRegistration()
    assert tab.registrationStatus == ""
