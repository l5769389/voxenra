from dataclasses import replace
from threading import Event

import pytest

from test_pet_2d import _pet_dataset, _write_dataset, _pet_render_result, _pet_viewport
from test_measurement_qml import qt_app
from test_dicom_tags import wait_until
from voxplane.model import StackRenderRequest, RenderFailure, WindowLevel
from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.volume_manager import VolumeManager
from voxplane.application.series_catalog import SeriesCatalog
from voxplane.service.render_serivce import RenderService
from test_pet_fusion import paired_series
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.core.pet_reconstruction import PetReconstructor
import numpy as np


def test_stack_decode_cache_reused_for_unit_and_window(tmp_path, monkeypatch):
    path = _write_dataset(_pet_dataset(), tmp_path / "pet.dcm")
    loader = DicomLoader()
    decode = loader.to_modality_pixels
    count = []
    def counted(dataset):
        count.append(dataset.SOPInstanceUID)
        return decode(dataset)
    monkeypatch.setattr(loader, "to_modality_pixels", counted)
    request = StackRenderRequest(request_id="a", viewport_id="v", series_uid="s", slice_index=0,
                                  window=None, inverted=False)
    loader.load_a_dicom(path, request)
    result = loader.load_a_dicom(path, replace(request, value_unit="kbqml", window=WindowLevel(1, 2)))
    assert len(count) == 1
    assert result.pixel_value_meta.unit == "kBq/ml"


def test_pet_stack_stale_success_failure_and_pending_reset():
    viewport, _ = _pet_viewport()
    initial = _pet_render_result()
    viewport.handleRenderResult(initial)
    requests = []
    viewport.renderRequested.connect(requests.append)
    viewport.setPetUnit("kbqml")
    old = requests[-1]
    viewport.setPetUnit("source")
    latest = requests[-1]
    viewport.handleRenderResult(replace(initial, response_id=old.request_id))
    viewport.handleRenderFailure(RenderFailure(request_id=old.request_id, viewport_id=viewport.viewportId,
                                               error=ValueError("old")))
    assert viewport.petUnitPending and viewport.petActiveUnitId == "suvbw"
    viewport.handleRenderFailure(RenderFailure(request_id=latest.request_id, viewport_id=viewport.viewportId,
                                               error=ValueError("new")))
    assert not viewport.petUnitPending
    assert viewport.petActiveUnitId == "suvbw"
    assert viewport.petControlUpperOptions == [5., 10., 20., 30., 40.]
    assert viewport._modality_pixel is initial.modality_pixel
    viewport.setPetControlUpper(30.00001)
    assert 30.00001 in viewport.petControlUpperOptions


@pytest.mark.parametrize("fail_first", [False, True])
def test_render_queue_has_only_running_and_latest_request(qt_app, monkeypatch, fail_first):
    entered, release = Event(), Event()
    service = RenderService(SeriesCatalog(), VolumeManager())
    completed, failed, reads = [], [], []
    service.rendered.connect(completed.append)
    service.failed.connect(failed.append)
    def render(request):
        reads.append(request.request_id)
        if request.request_id == "first":
            entered.set()
            assert release.wait(3)
            if fail_first:
                service._worker.render_failed.emit(RenderFailure(request_id=request.request_id,
                    viewport_id=request.viewport_id, error=ValueError("obsolete")))
                return
        service._worker.render_finished.emit(replace(_pet_render_result(),
            response_id=request.request_id, viewport_id=request.viewport_id))
    monkeypatch.setattr(service._worker, "_handle_stack_request", render)
    request = StackRenderRequest(request_id="first", viewport_id="v", series_uid="s", slice_index=0,
                                  window=None, inverted=False)
    try:
        service.submit(request)
        wait_until(entered.is_set)
        for i in range(100):
            service.submit(replace(request, request_id=str(i)))
        assert len(service._pending) == 1
        release.set()
        wait_until(lambda: len(completed) == 1)
        assert reads == ["first", "99"]
        assert completed[0].response_id == "99"
        assert not failed
    finally:
        release.set()
        service.shutdown()


def test_registration_presents_completed_preview_with_a_newer_transform_queued(qt_app, paired_series, monkeypatch):
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    service = RenderService(catalog, VolumeManager())
    workspace.renderRequested.connect(service.submit)
    service.rendered.connect(workspace.handleRenderResult)
    service.failed.connect(workspace.handleRenderFailure)
    entered, release, second_entered, second_release = Event(), Event(), Event(), Event()
    render = service._worker._pet_reconstructor.render
    reads = []

    def held_render(request):
        if request.preview:
            reads.append(request)
            if len(reads) == 1:
                entered.set()
                assert release.wait(10)
            elif len(reads) == 2:
                second_entered.set()
                assert second_release.wait(10)
        return render(request)

    monkeypatch.setattr(service._worker._pet_reconstructor, "render", held_render)
    try:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        tab = next(iter(workspace._tab_dict.values()))
        wait_until(lambda: tab.ready)
        committed = tab._committed_request
        fusion = tab.activeViewport
        old_image = provider._images[fusion.viewportId].copy()
        tab.setRegistrationActive(True)
        fusion.beginInteraction(0, 0, 1, True, 1., 1., .01, .01)
        fusion.updateRegistrationDrag(1.5, 1.)
        wait_until(entered.is_set)
        # Continuous movement coalesces to the latest transform, but must not
        # starve presentation of the completed first transform.
        for column in (1.6, 1.7, 1.8, 1.9, 2.):
            fusion.updateRegistrationDrag(column, 1.)
        target = tab.matrix.copy()
        latest = tab._requested
        release.set()
        wait_until(second_entered.is_set)
        wait_until(lambda: tab._presented_revision == reads[0].revision)
        assert provider._images[fusion.viewportId] != old_image
        np.testing.assert_array_equal(tab.matrix, target)
        assert tab._committed_request is committed
        assert reads[1] == latest
        assert len(reads) == 2
        second_release.set()
        fusion.endInteraction(0, 0, True, 2.2, 1.)
        wait_until(lambda: tab._committed_request == tab._requested)
        assert not tab._committed_request.preview
        assert tab.matrix[0, 3] == pytest.approx(1.2 * fusion._plane_geometry.column_spacing)
        assert all(not getattr(v, "_mip_result", None) or not v._mip_result.preview
                   for v in tab.viewports_by_id.values())
    finally:
        release.set()
        second_release.set()
        service.shutdown()
        workspace.shutdown()


@pytest.mark.parametrize("change", ["plane", "unit", "color", "window", "opacity", "gesture"])
def test_registration_preview_cannot_overwrite_a_new_context(qt_app, paired_series, change):
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    requests = []
    workspace.renderRequested.connect(requests.append)
    renderer = PetReconstructor(catalog, VolumeManager())
    try:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        tab = next(iter(workspace._tab_dict.values()))
        workspace.handleRenderResult(renderer.render(requests[-1]))
        tab.setRegistrationActive(True)
        tab.setRegistrationParameter(0, 1.)
        stale = renderer.render(requests[-1])
        if change == "plane": tab.setPlane("coronal")
        elif change == "unit": tab.petController.setPetUnit("kbqml")
        elif change == "color": tab.setFusionColorMap("hotMetal")
        elif change == "window": tab.setCtWindow(40, 400)
        elif change == "opacity": tab.setOpacity(.75)
        else:
            tab.begin_registration_drag()
            tab.setRegistrationParameter(0, 2.)
        images = provider._images.copy()
        assert not tab.accepts_render_result(stale)
        workspace.handleRenderResult(stale)
        assert provider._images == images
        assert tab._committed_request.revision == 1
    finally:
        workspace.shutdown()


def test_failed_registration_refinement_restores_pixels_geometry_and_mip(qt_app, paired_series):
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    requests = []
    workspace.renderRequested.connect(requests.append)
    renderer = PetReconstructor(catalog, VolumeManager())
    try:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        tab = next(iter(workspace._tab_dict.values()))
        original = renderer.render(requests[-1])
        workspace.handleRenderResult(original)
        original_images = provider._images.copy()
        tab.setRegistrationActive(True)
        tab.setRegistrationParameter(0, 1.)
        workspace.handleRenderResult(renderer.render(requests[-1]))
        assert provider._images != original_images
        tab.finishRegistrationPreview()
        workspace.handleRenderFailure(RenderFailure(request_id=requests[-1].request_id,
            viewport_id=requests[-1].viewport_id, error=ValueError("refinement failed")))
        np.testing.assert_array_equal(tab.matrix, np.eye(4))
        assert provider._images == original_images
        for frame in original.frames:
            viewport = tab.viewports_by_id[frame.viewport_id]
            assert viewport._modality_pixel is frame.modality_pixel
            if viewport.viewportRole == "mip": assert not viewport._mip_result.preview
            else: assert viewport._plane_geometry == frame.plane_geometry
    finally:
        workspace.shutdown()


def test_new_registration_gesture_interrupts_full_mip_without_rolling_back(qt_app, paired_series, monkeypatch):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    service = RenderService(catalog, VolumeManager())
    workspace.renderRequested.connect(service.submit)
    service.rendered.connect(workspace.handleRenderResult)
    service.failed.connect(workspace.handleRenderFailure)
    entered, release = Event(), Event()
    tokens, failures = [], []
    service.failed.connect(failures.append)
    try:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        tab = next(iter(workspace._tab_dict.values()))
        wait_until(lambda: tab.ready)
        committed = tab._committed_request
        reconstructor = service._worker._pet_reconstructor
        full_mip = reconstructor._full_mip
        def held_mip(volume, preview=False, cancel_event=None):
            if not preview:
                tokens.append(cancel_event)
                entered.set()
                assert release.wait(10)
            return full_mip(volume, preview, cancel_event)
        monkeypatch.setattr(reconstructor, "_full_mip", held_mip)
        transform = np.eye(4)
        transform[0, 3] = 1
        tab.set_registration(transform)
        wait_until(entered.is_set)
        tab.setRegistrationActive(True)
        tab.begin_registration_drag()
        tab.setRegistrationParameter(0, 2)
        assert tokens[0].is_set()
        release.set()
        wait_until(lambda: tab._presented_revision == tab._requested.revision)
        assert not failures
        assert tab.matrix[0, 3] == 2
        assert tab._committed_request is committed
        tab.finishRegistrationPreview()
        wait_until(lambda: tab._committed_request == tab._requested)
        assert not failures and tab.matrix[0, 3] == 2
    finally:
        release.set()
        service.shutdown()
        workspace.shutdown()
