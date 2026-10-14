from dataclasses import replace
from unittest.mock import Mock

import numpy as np
import pytest
from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor
from vtkmodules.util.numpy_support import vtk_to_numpy

from test_pet_fusion import paired_series
from test_measurement_qml import qt_app
from qt_dicom_viewer.core.pet_reconstruction import PetReconstructor
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.pet_volume_render_backend import (
    PetVolumeRenderBackend, fusion_camera_geometry, padding_safe_vtk, pet_transfer_functions,
)


@pytest.fixture
def fusion_scene(qt_app, paired_series):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    requests = []
    workspace.renderRequested.connect(requests.append)
    workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    source = workspace.activeTab
    renderer = PetReconstructor(catalog, VolumeManager())
    source.handleRenderResult(renderer.render(requests[-1]))
    yield workspace, source, renderer, requests
    workspace.shutdown()


def test_volume_tab_uses_committed_volumes_and_survives_source_close(fusion_scene, monkeypatch):
    workspace, source, renderer, requests = fusion_scene
    initial_requests = len(requests)
    source.openVolumeView()
    view, tab_id = workspace.activeViewport, workspace.activeTabId
    assert view.isFusionVolume and view.scene is source._last_result
    assert len(requests) == initial_requests  # no duplicate load / 2D render
    assert view.loadState == "ready" and len(workspace.currentTabAllViewports) == 1
    assert len(source.viewports_by_id) == 4
    assert {item["toolType"] for item in workspace.activeTab.toolController.tools} == {
        "window", "pan", "zoom", "volume-rotate", "volume-direction", "volume-preset", "reset"}
    view.setVolumeMode("pet")
    view.setPetOpacity(.4)
    source.openVolumeView()
    assert workspace.activeViewport is view and view.volumeMode == "pet"
    initial = view.scene
    source.setRegistrationActive(True)
    source.begin_registration_drag()
    transform = source.matrix.copy()
    transform[0, 3] = 2
    source.set_registration(transform, preview=True)
    source.handleRenderResult(renderer.render(requests[-1]))
    assert view.scene is initial  # partial interactive MIP is not a 3D snapshot
    source.finishRegistrationPreview()
    source.handleRenderResult(renderer.render(requests[-1]))
    assert view.scene is source._last_result and view.scene.request.transform[3] == 2
    source.petController.setPetUnit("kbqml")
    source.handleRenderResult(renderer.render(requests[-1]))
    assert view.petUnit == "kBq/ml"
    assert view.petThreshold == pytest.approx(view.petUpper*.1)
    from PySide6.QtWidgets import QMessageBox
    with monkeypatch.context() as closing:
        closing.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Close)
        workspace.closeTab(source._tab_config.tab_id)
    assert view.source_workspace is None and "快照" in view.sceneLabel
    snapshot = view.scene
    source.snapshotCommitted.emit(initial)
    assert view.scene is snapshot
    workspace.closeTab(tab_id)
    assert view.scene is None and view.volume is None


def test_multivolume_preserves_grids_transform_and_transfer_functions(fusion_scene):
    workspace, source, _, _ = fusion_scene
    source.openVolumeView()
    view = workspace.activeViewport
    window = vtkGenericOpenGLRenderWindow()
    interactor = vtkGenericRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    widget = Mock()
    widget.GetRenderWindow.return_value = window
    widget.width.return_value, widget.height.return_value = 640, 480
    backend = PetVolumeRenderBackend(widget, view)
    try:
        backend.set_volume(view.volume)
        backend.apply_display(view.display_state)
        ct_image, pet_image = [backend.mapper.GetInputDataObject(port, 0) for port in (0, 1)]
        for image, volume in ((ct_image, view.scene.ct_volume), (pet_image, view.scene.pet_volume)):
            np.testing.assert_allclose(image.GetOrigin(), volume.geometry.origin_patient)
            np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()),
                                         volume.modality_pixels.ravel())
        transform = np.eye(4)
        transform[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        transform[:3, 3] = [9, 4, 0]
        view.accept_snapshot(replace(view.scene, request=replace(view.scene.request,
                                                               transform=tuple(transform.ravel()))))
        backend.apply_display(view.display_state)
        matrix = backend.layers[1].GetUserMatrix()
        np.testing.assert_allclose([[matrix.GetElement(r, c) for c in range(4)] for r in range(4)], transform)
        assert backend.mapper.GetInputDataObject(0, 0) is ct_image
        assert backend.mapper.GetInputDataObject(1, 0) is pet_image
        for mode in ("ct", "pet", "fusion"):
            view.setVolumeMode(mode)
            backend.apply_display(view.display_state)
            ct_alpha = backend.layers[0].GetProperty().GetScalarOpacity().GetValue(2000)
            pet_alpha = backend.layers[1].GetProperty().GetScalarOpacity().GetValue(view.petUpper)
            assert (ct_alpha > 0) == (mode != "pet")
            assert (pet_alpha > 0) == (mode != "ct")
        assert backend.mapper.GetBlendMode() == 0  # same-ray compositing
    finally:
        backend.dispose()


def test_padding_and_camera_fit_do_not_modify_quantitative_data(fusion_scene):
    _, source, _, _ = fusion_scene
    ct, pet = source._last_result.ct_volume, source._last_result.pet_volume
    pixels = pet.modality_pixels.copy()
    pixels[0, 0, 0] = np.nan
    image, _ = padding_safe_vtk(replace(pet, modality_pixels=pixels), pet=True)
    assert vtk_to_numpy(image.GetPointData().GetScalars())[0] == 0
    assert np.isnan(pixels[0, 0, 0])
    transform = np.eye(4)
    transform[:3, 3] = [100, -20, 30]
    fitted = fusion_camera_geometry(ct, pet, transform)
    np.testing.assert_allclose(fitted.origin_patient, [0, -20, 0])
    np.testing.assert_allclose([fitted.column_spacing, fitted.row_spacing, fitted.slice_spacing], [106, 26, 34])
    colors, alpha = pet_transfer_functions(10, 2, "hotIron", .8)
    assert alpha.GetValue(1) == 0 and alpha.GetValue(10) == pytest.approx(.8)
    assert colors.GetColor(10) == (1, 1, 1)
    with pytest.raises(ValueError):
        pet_transfer_functions(0, 2, "hotIron", .8)


def test_fusion_volume_window_is_independent_of_source(fusion_scene):
    workspace, source, renderer, requests = fusion_scene
    source.openVolumeView()
    view = workspace.activeViewport
    source_window = source.ctCenter, source.ctWidth
    view.applyWindowPreset(50, 900)
    assert view.windowWidth == 900
    assert (source.ctCenter, source.ctWidth) == source_window and not source.ctInverted
    source.setCtWindow(20, 600)
    source.handleRenderResult(renderer.render(requests[-1]))
    assert (view.windowCenter, view.windowWidth) == (50, 900)
    workspace.closeTab(source._tab_config.tab_id)
    assert view.windowWidth == 900
    view.reset_all_view_state()
    assert view.windowWidth == 1500
