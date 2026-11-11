"""PET-only 3D routing, quantitative units, crop masks and stale work."""
from dataclasses import replace
from unittest.mock import Mock
import numpy as np
import pytest
from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor
from vtkmodules.util.numpy_support import vtk_to_numpy
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import RenderFailure
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.workers.dicom_render_worker import DicomRenderWorker
from voxplane.ui.standalone_pet_volume_backend import StandalonePetVolumeBackend
from test_pet_fusion import paired_series, qt_app
from test_dicom_tags import wait_until


@pytest.fixture
def pet_volume(qt_app, paired_series):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    requests = []
    workspace.renderRequested.connect(requests.append)
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(workspace.handleRenderFailure)
    workspace.createTab(pet.series_instance_uid, "PET 3D", "3d")
    yield workspace, workspace.activeViewport, requests, worker, pet
    workspace.shutdown()


def ready(fixture):
    workspace, view, requests, worker, pet = fixture
    worker.handleRenderRequest(requests[-1])
    assert view.loadState == "ready", view.errorMessage
    assert workspace.activeLoadState.status == "ready"
    return view


def test_direct_pet_volume_reuses_tab_and_truthful_tools(pet_volume):
    workspace, view, requests, worker, pet = pet_volume
    assert workspace.activeLoadState.loading and view._host is None
    ready(pet_volume)
    assert view.isStandalonePetVolume and view.petUnitId == "suvbw"
    assert view.petUpper > 0 and view.petThreshold == pytest.approx(view.petUpper * .1)
    assert view.petPalette == workspace.activeTab.toolController.settingsController.values["colormap"]["pet"]
    workspace.createTab(pet.series_instance_uid, "PET", "3d")
    assert workspace.activeViewport is view and len(requests) == 1
    tools = [t["toolType"] for t in workspace.activeTab.toolController.tools]
    assert tools == ["pan", "zoom", "volume-rotate", "volume-preset", "volume-direction", "volume-crop", "export", "reset"]
    assert not view.bedRemovalAvailable


def test_units_keep_physical_range_camera_mask_and_ignore_stale_results(pet_volume):
    workspace, view, requests, worker, pet = pet_volume
    ready(pet_volume)
    original = view.volume
    pixels = original.modality_pixels.copy()
    view.setPetUpper(.179)
    view.setPetThreshold(.023)
    view.setPetOpacity(.45)
    view.setViewFace("L")
    state = view.state
    mask = np.ones(original.modality_pixels.shape, dtype=bool)
    mask[:, :, 0] = False
    view.crop_mask = mask
    view._update_mask()
    view.setPetUnit("kbqml")
    stale = requests[-1]
    assert workspace.activeLoadState.loading
    view.setPetUnit("suvbw")
    worker.handleRenderRequest(stale)
    assert view.loadState == "loading" and view.volume is original
    worker.handleRenderRequest(requests[-1])
    assert view.petUpper == pytest.approx(.179)
    view.setPetUnit("kbqml")
    worker.handleRenderRequest(requests[-1])
    ratio = view.volume.pixel_value_meta.scale_from_source / original.pixel_value_meta.scale_from_source
    assert view.petUpper == pytest.approx(.179 * ratio)
    assert view.petThreshold == pytest.approx(.023 * ratio)
    assert view.petOpacity == .45 and view.state == state
    assert view.visible_mask is mask
    np.testing.assert_array_equal(original.modality_pixels, pixels)
    view.reset_all_view_state()
    worker.handleRenderRequest(requests[-1])
    assert view.petUnitId == "suvbw" and view.visible_mask is None
    assert view.petUpper == view._initial_upper and view.petOpacity == .8


def test_pet_crop_uses_worker_and_reset_preserves_source(pet_volume):
    workspace, view, requests, worker, pet = pet_volume
    ready(pet_volume)
    original = view.volume.modality_pixels.copy()
    workspace.activeTab.toolController.activateTool("volume-crop")
    view.begin_drag((0, 0), (640, 480))
    for point in ((320, 0), (320, 480), (0, 480)):
        view.update_drag(point)
    view.end_drag()
    wait_until(lambda: not view.editBusy)
    assert view.hasCrop and view.visible_mask.any() and not view.visible_mask.all()
    np.testing.assert_array_equal(view.volume.modality_pixels, original)
    view.resetCrop()
    assert view.visible_mask is None


@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf")])
def test_invalid_upper_does_not_change_image(pet_volume, value):
    view = ready(pet_volume)
    before = view.petUpper
    view.setPetUpper(value)
    assert view.petUpper == before


def test_missing_units_are_not_offered_or_relabelled(pet_volume):
    workspace, view, requests, worker, pet = pet_volume
    ready(pet_volume)
    from voxplane.model.dicom_types import PixelUnitOption
    native = PixelUnitOption("native", "counts", "counts", 1.)
    view._unit = "native"
    view.volume = replace(view.volume, pixel_value_meta=replace(view.volume.pixel_value_meta,
        unit="counts", unit_id="native", unit_options=(native,)))
    count = len(requests)
    view.setPetUnit("suvbw")
    assert len(requests) == count and [o["unitId"] for o in view.petUnitOptions] == ["native"]


def test_failure_retry_close_and_late_worker_results(pet_volume):
    workspace, view, requests, worker, pet = pet_volume
    first = requests[-1]
    workspace.handleRenderFailure(RenderFailure(request_id=first.request_id,
        viewport_id=view.viewportId, error=ValueError("broken PET")))
    assert workspace.activeLoadState.status == "error"
    workspace.retryActiveTab()
    assert requests[-1].request_id != first.request_id
    worker.handleRenderRequest(first)
    assert workspace.activeLoadState.loading
    ready(pet_volume)
    view.setPetUnit("kbqml")
    late = requests[-1]
    workspace.closeTab(workspace.activeTabId)
    worker.handleRenderRequest(late)
    assert view.volume is None and not workspace.tabs


def test_pet_backend_preserves_grid_values_transfer_and_crop(pet_volume):
    view = ready(pet_volume)
    window = vtkGenericOpenGLRenderWindow()
    interactor = vtkGenericRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    widget = Mock()
    widget.GetRenderWindow.return_value = window
    widget.width.return_value, widget.height.return_value = 640, 480
    backend = StandalonePetVolumeBackend(widget, view)
    try:
        backend.set_volume(view.volume)
        view.setPetUpper(.179)
        view.setPetThreshold(.025)
        backend.apply_display(view.display_state)
        image = backend.mapper.GetInput()
        np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()), view.volume.modality_pixels.ravel())
        g = view.volume.geometry
        point = [0., 0., 0.]
        image.TransformIndexToPhysicalPoint(2, 1, 1, point)
        np.testing.assert_allclose(point, (g.voxel_to_patient @ [1, 1, 2, 1])[:3])
        opacity = backend.properties.GetScalarOpacity()
        assert opacity.GetValue(.01) == 0
        assert opacity.GetValue(.179) == pytest.approx(.8)
        mask = np.ones(view.volume.modality_pixels.shape, bool)
        mask[:, :, 0] = False
        backend.apply_mask(mask)
        np.testing.assert_array_equal(vtk_to_numpy(backend.mapper.GetMaskInput().GetPointData().GetScalars()), mask.ravel() * 255)
        backend.apply_mask(None)
        assert backend.mapper.GetMaskInput() is None
    finally:
        backend.dispose()
