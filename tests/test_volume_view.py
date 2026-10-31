from dataclasses import fields, replace
from itertools import product
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from vtkmodules.util.numpy_support import vtk_to_numpy

from qt_dicom_viewer.core.volume_view import (
    VolumeViewState, camera_parameters, rotate_drag, rotation_matrix,
    validate_volume_series, zoom_by,
)
from qt_dicom_viewer.model import (
    DicomInstanceMeta, DicomSeriesRecord, InstanceDisplayMeta, PixelSpacing,
    RenderFailure, SeriesDisplayMeta, TabConfig, TabType, WindowLevel,
)
from qt_dicom_viewer.model.dicom_core import DicomVolume, VolumeGeometry
from qt_dicom_viewer.model.render_models import VolumeLoadRequest, VolumeLoadResult
from qt_dicom_viewer.ui.controller.tab.tab_controller import TabController
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.volume_render_backend import volume_to_vtk
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker


@pytest.fixture
def volume():
    # A right-handed oblique grid with unequal spacing detects axis swaps,
    # LPS sign flips and incorrect VTK scalar ordering.
    c, s = np.cos(0.4), np.sin(0.4)
    geometry = VolumeGeometry(
        slice_count=3, rows=4, columns=5,
        row_spacing=0.8, column_spacing=0.6, slice_spacing=2.1,
        origin_patient=(-18, 24, 36),
        column_index_direction_patient=(c, 0, s),
        row_index_direction_patient=(0, 1, 0),
        slice_index_direction_patient=(-s, 0, c),
    )
    meta = InstanceDisplayMeta(**{f.name: None for f in fields(InstanceDisplayMeta)})
    return DicomVolume(
        np.arange(60, dtype=np.float32).reshape(3, 4, 5)-30, geometry,
        "test-series", WindowLevel(center=0, width=60), meta,
    )


@pytest.fixture
def series(volume):
    g = volume.geometry
    instances = []
    for index in range(g.slice_count):
        position = (g.voxel_to_patient @ [index, 0, 0, 1])[:3]
        instances.append(DicomInstanceMeta(
            path=Path(f"{index}.dcm"), patient_name="", patient_id="", study_description="",
            study_instance_uid="study", series_description="", series_instance_uid="test-series",
            series_number=1, instance_number=index, sop_instance_uid=f"instance-{index}",
            pixel_spacing=PixelSpacing(g.row_spacing, g.column_spacing), modality="CT",
            rows=g.rows, columns=g.columns, transfer_syntax="",
            image_position_patient=tuple(position), image_orientation_patient=(
                *g.column_index_direction_patient, *g.row_index_direction_patient),
            slice_thickness=g.slice_spacing,
        ))
    return DicomSeriesRecord("", "", "", "study", "", "test-series", 1, "CT", tuple(instances))


def make_tab(tab_id="tab", series_uid="test-series"):
    meta = SeriesDisplayMeta("", "", "", "", "CT", series_uid)
    return TabController(TabConfig(tab_id, "3D", TabType.THREE_D, (meta,)))


@pytest.mark.parametrize('drift', ['lateral', 'spacing', 'regular', 'roundoff'])
def test_grid_validation_bounds_total_position_error(series, drift):
    n = 1001
    positions = np.column_stack((np.zeros(n), np.zeros(n), np.arange(n, dtype=float)))
    if drift == 'lateral':
        positions[:, 0] = np.arange(n) * .0009
    elif drift == 'spacing':
        positions[:, 2] = np.r_[0., np.cumsum([.9985]*500 + [1.0015]*500)]
    elif drift == 'roundoff':
        positions[1::2, 0] = .0001
    # Large patient origins must not enlarge the allowed residual.
    positions += (10000, -20000, 30000)
    records = tuple(replace(series.instances[0], image_position_patient=tuple(p),
                           image_orientation_patient=(1, 0, 0, 0, 1, 0))
                    for p in positions[::-1])
    candidate = replace(series, instances=records)
    if drift in ('lateral', 'spacing'):
        with pytest.raises(ValueError):
            validate_volume_series(candidate)
    else:
        validate_volume_series(candidate)


def test_vtk_preserves_physical_coordinates_and_signed_scalar_values(volume):
    image, backing = volume_to_vtk(volume)
    assert image.GetDimensions() == (5, 4, 3)
    np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()),
                                  volume.modality_pixels.ravel())
    for k, j, i in ((0, 0, 0), (2, 3, 4), (1, 2, 3)):
        patient = [0.0]*3
        image.TransformIndexToPhysicalPoint(i, j, k, patient)
        np.testing.assert_allclose(patient, (volume.geometry.voxel_to_patient @ [k, j, i, 1])[:3])
        assert image.GetScalarComponentAsDouble(i, j, k, 0) == volume.modality_pixels[k, j, i]
    assert np.shares_memory(backing, volume.modality_pixels)


@pytest.mark.parametrize("invalid", ["shape", "spacing", "pixels"])
def test_invalid_volume_is_rejected_before_vtk_render(volume, invalid):
    if invalid == "shape":
        volume.modality_pixels = np.zeros((1, 2, 3))
    elif invalid == "spacing":
        volume.geometry = replace(volume.geometry, column_spacing=float("nan"))
    else:
        volume.modality_pixels[0, 0, 0] = float("inf")
    with pytest.raises(ValueError):
        volume_to_vtk(volume)


def test_rotation_stays_orthonormal_and_changes_camera_only(volume):
    state = VolumeViewState(pan=(0.1, -0.2), zoom=2)
    for _ in range(200):
        state = rotate_drag(state, (320, 240), (390, 285), (640, 480))
    matrix = rotation_matrix(state.rotation)
    np.testing.assert_allclose(matrix.T @ matrix, np.eye(3), atol=1e-12)
    assert np.linalg.det(matrix) == pytest.approx(1)
    assert state.pan == (0.1, -0.2) and state.zoom == 2
    assert rotate_drag(state, (20, 30), (20, 30), (640, 480)) == state
    # Antipodal sphere points should produce a finite half-turn.
    half_turn = rotate_drag(VolumeViewState(), (0, 240), (640, 240), (640, 480))
    assert np.linalg.norm(half_turn.rotation) == pytest.approx(1)
    camera = camera_parameters(volume.geometry, VolumeViewState(), (640, 480))
    np.testing.assert_allclose(camera["focal"], volume.geometry.center_patient)
    zoomed = camera_parameters(volume.geometry, VolumeViewState(zoom=2), (640, 480))
    assert zoomed["scale"] == camera["scale"]/2
    np.testing.assert_allclose(zoomed["position"], camera["position"])


def test_zoom_is_bounded_and_pan_does_not_change_view_direction(volume):
    assert zoom_by(VolumeViewState(), 1e9).zoom == 20
    assert zoom_by(VolumeViewState(), -1e9).zoom == 0.1
    before = camera_parameters(volume.geometry, VolumeViewState(), (300, 800))
    after = camera_parameters(volume.geometry, VolumeViewState(pan=(0.5, 0.1)), (300, 800))
    np.testing.assert_allclose(before["position"]-before["focal"], after["position"]-after["focal"])
    np.testing.assert_allclose(before["up"], after["up"])
    assert before["scale"] == after["scale"]


@pytest.mark.parametrize("size", [(1100, 760), (520, 340), (320, 680)])
@pytest.mark.parametrize("shape", [(48, 64, 64), (160, 48, 48), (24, 48, 160)])
@pytest.mark.parametrize("oblique", [False, True])
def test_initial_camera_fits_projected_corners_with_moderate_margin(volume, size, shape, oblique):
    geometry = replace(volume.geometry, slice_count=shape[0], rows=shape[1], columns=shape[2])
    if not oblique:
        geometry = replace(geometry, column_index_direction_patient=(1, 0, 0),
                           row_index_direction_patient=(0, 1, 0),
                           slice_index_direction_patient=(0, 0, 1))
    camera = camera_parameters(geometry, VolumeViewState(), size)
    # Independently project patient-space corners onto the actual VTK camera.
    back = camera["position"] - camera["focal"]
    back /= np.linalg.norm(back)
    right = np.cross(camera["up"], back)
    occupancy = []
    for k, j, i in product(*[(0, n-1) for n in shape]):
        point = (geometry.voxel_to_patient @ [k, j, i, 1])[:3]
        relative = point - camera["focal"]
        occupancy.extend((abs(relative @ right) / (camera["scale"] * size[0] / size[1]),
                          abs(relative @ camera["up"]) / camera["scale"]))
        depth = (camera["position"] - point) @ back
        assert camera["clipping"][0] < depth < camera["clipping"][1]
    assert max(occupancy) == pytest.approx(1 / 1.15)
    rotated = rotate_drag(VolumeViewState(), (40, 40), (180, 130), size)
    assert camera_parameters(geometry, rotated, size)["scale"] == camera["scale"]


def test_regular_oblique_grid_accepts_reverse_input_order(series):
    validate_volume_series(replace(series, instances=series.instances[::-1]))


@pytest.mark.parametrize("invalid", ["single", "missing", "duplicate", "nonuniform", "shear"])
def test_unrepresentable_grid_is_rejected(series, invalid):
    instances = list(series.instances)
    if invalid == "single":
        instances = instances[:1]
    elif invalid == "missing":
        instances[1] = replace(instances[1], image_position_patient=None)
    elif invalid == "duplicate":
        instances[1] = replace(instances[1], image_position_patient=instances[0].image_position_patient)
    else:
        offset = (0, 0, 1) if invalid == "nonuniform" else (0, 1, 0)
        instances[1] = replace(instances[1], image_position_patient=tuple(
            np.array(instances[1].image_position_patient)+offset))
    with pytest.raises(ValueError):
        validate_volume_series(replace(series, instances=tuple(instances)))


def test_3d_tools_and_scoped_resets_are_independent_per_tab(volume):
    tab, other = make_tab(), make_tab("other")
    view, tools = tab.activeViewport, tab.toolController
    assert {t["toolType"] for t in tools.tools} == {
        "pan", "zoom", "volume-rotate", "volume-direction", "volume-preset", "window", "reset",
        "volume-bed", "volume-crop",
        "export",
    }
    assert all(t["available"] for t in tools.tools)
    assert tools.activeInteraction == "volume:rotate"
    assert tools.activePanel == ""
    view._set_status("ready")
    for tool, end in (("volume-rotate", (400, 300)), ("pan", (360, 250)), ("zoom", (320, 180))):
        tools.activateTool(tool)
        view.begin_drag((320, 240), (640, 480))
        view.update_drag(end)
        view.end_drag()
    saved = view.state
    assert saved.rotation != VolumeViewState().rotation and saved.pan != (0, 0) and saved.zoom > 1
    tools.resetActiveTool()
    assert view.state == replace(saved, zoom=1)
    tools.activateTool("pan")
    tools.resetActiveTool()
    assert view.state == VolumeViewState(rotation=saved.rotation)
    tools.activateTool("volume-rotate")
    tools.resetActiveTool()
    assert view.state == VolumeViewState()
    view.wheel_zoom(120, 0)
    assert view.state.zoom > 1
    view.wheel_zoom(0, 30)
    assert other.activeViewport.state == VolumeViewState()
    tools.activateTool("reset")
    assert view.state == VolumeViewState()


def test_async_load_retry_and_dispose_ignore_old_results(volume):
    tab = make_tab()
    view = tab.activeViewport
    requests = []
    tab.renderRequested.connect(requests.append)
    tab.init_render()
    first = requests[-1]
    view.handleRenderFailure(RenderFailure(request_id=first.request_id, viewport_id=first.viewport_id,
                                           error=ValueError("failed")))
    assert view.loadState == "error"
    view.retry()
    second = requests[-1]
    view.handleRenderResult(VolumeLoadResult(response_id=first.request_id, viewport_id=first.viewport_id,
                                           series_uid=first.series_uid, volume=volume))
    view.handleRenderFailure(RenderFailure(request_id=first.request_id, viewport_id=first.viewport_id,
                                           error=ValueError("late")))
    assert view.loadState == "loading" and view.volume is None
    result = VolumeLoadResult(response_id=second.request_id, viewport_id=second.viewport_id,
                              series_uid=second.series_uid, volume=volume)
    assert not view.accepts_result(replace(result, viewport_id="wrong"))
    view.handleRenderResult(result)
    assert view.loadState == "ready" and view.volume is volume
    tab.dispose()
    view.handleRenderResult(result)
    view.retry()
    assert view.volume is None and view.nativeWindow is None and len(requests) == 2


def test_worker_loads_volume_without_2d_image_payload_and_reports_invalid_series(series, volume):
    catalog, manager = Mock(), Mock()
    catalog.get_series.return_value = series
    manager.get_or_build.return_value = volume
    worker = DicomRenderWorker(catalog, manager)
    results, failures = [], []
    worker.render_finished.connect(results.append)
    worker.render_failed.connect(failures.append)
    request = VolumeLoadRequest(request_id="r", viewport_id="v", series_uid="test-series")
    worker.handleRenderRequest(request)
    assert len(results) == 1 and not failures
    assert results[0].volume is volume and not hasattr(results[0], "image")
    catalog.get_series.return_value = replace(series, instances=series.instances[:1])
    worker.handleRenderRequest(request)
    assert len(failures) == 1 and failures[0].request_id == "r"
    assert manager.get_or_build.call_count == 1


def test_workspace_routes_volume_without_image_provider_and_discards_closed_tab_results(volume):
    catalog, image_provider = Mock(), Mock()
    catalog.get_series_display_meta.return_value = SeriesDisplayMeta("", "", "", "", "CT", "test-series")
    workspace = WorkspaceController(catalog, image_provider)
    requests = []
    workspace.renderRequested.connect(requests.append)
    workspace.createTab("test-series", "3D", TabType.THREE_D)
    request = requests[-1]
    result = VolumeLoadResult(response_id=request.request_id, viewport_id=request.viewport_id,
                              series_uid=request.series_uid, volume=volume)
    workspace.handleRenderResult(result)
    assert workspace.activeViewport.volume is volume
    image_provider.set_array.assert_not_called()
    workspace.closeTab(workspace.activeTabId)
    workspace.createTab("test-series", "Reopened", TabType.THREE_D)
    workspace.handleRenderResult(result)
    workspace.handleRenderFailure(RenderFailure(request_id=request.request_id,
        viewport_id=request.viewport_id, error=ValueError("late error")))
    assert workspace.activeViewport.volume is None
    assert workspace.activeViewport.loadState == "loading"
    workspace.shutdown()
