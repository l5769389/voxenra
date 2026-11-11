from dataclasses import replace
import time
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPolygonF
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkRenderingCore import vtkCamera
from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor

from voxplane.core.volume_edit import bed_keep_mask, crop_keep_mask, polygon_contains
from voxplane.core.volume_view import VolumeViewState, camera_parameters, face_rotation
from voxplane.model import TabType
from voxplane.model.dicom_core import VolumeGeometry
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.volume_render_backend import VolumeRenderBackend
from test_measurement_qml import qt_app
from test_volume_display import loaded_tab
from test_volume_view import volume, make_tab


@pytest.fixture
def ct_volume(volume):
    pixels = np.full((12, 128, 128), -1000, dtype=np.float32)
    y, x = np.ogrid[:128, :128]
    body = ((x-64)/35)**2 + ((y-53)/32)**2 < 1
    pixels[:, body] = 80
    pixels[:, 92:97, 8:120] = 300  # Thin table.
    pixels[:, 75:94, 63:66] = 80  # Thin contact connects body to table.
    pixels[:, 40:55, 54:66] = -850  # Enclosed lungs must remain.
    geometry = VolumeGeometry(12, 128, 128, 1, 1, 2, (0, 0, 0),
                              (0, 0, 1), (0, 1, 0), (1, 0, 0))
    return replace(volume, geometry=geometry, modality_pixels=pixels)


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_table_removal_preserves_body_lung_and_original_across_axis_orders(ct_volume, axis, reverse):
    original = ct_volume.modality_pixels.copy()
    expected = bed_keep_mask(ct_volume)
    assert not expected[:, 92:97, 8:120].any()
    assert expected[:, 40:55, 54:66].all()
    assert expected[:, 30:78, 45:85].all()
    order = list(range(3))
    order.insert(axis, order.pop(0))
    spacing = np.array((2, 1, 1))[order]
    directions = np.array(((0, 0, 1), (0, 1, 0), (1, 0, 0)))[order]
    pixels = np.transpose(original, order)
    if reverse:
        pixels = np.flip(pixels, axis=1)
        directions[1] *= -1
    g = VolumeGeometry(*pixels.shape, spacing[1], spacing[2], spacing[0], (0, 0, 0),
                       *[tuple(d) for d in directions])
    mask = bed_keep_mask(replace(ct_volume, geometry=g, modality_pixels=pixels))
    target = np.transpose(expected, order)
    if reverse:
        target = np.flip(target, axis=1)
    np.testing.assert_array_equal(mask, target)
    np.testing.assert_array_equal(ct_volume.modality_pixels, original)


def test_table_removal_keeps_two_separate_legs_and_rejects_empty_scan(ct_volume):
    p = np.full_like(ct_volume.modality_pixels, -1000)
    y, x = np.ogrid[:128, :128]
    legs = (((x-39)/16)**2 + ((y-48)/22)**2 < 1) | (((x-89)/16)**2 + ((y-48)/22)**2 < 1)
    p[:, legs] = 70
    p[:, 92:97, 8:120] = 200
    mask = bed_keep_mask(replace(ct_volume, modality_pixels=p))
    assert mask[:, 48, 39].all() and mask[:, 48, 89].all()
    assert not mask[:, 92:97, 8:120].any()
    with pytest.raises(ValueError, match="未识别"):
        bed_keep_mask(replace(ct_volume, modality_pixels=np.full_like(p, -1000)))


@pytest.mark.parametrize("face", list("APLRSI"))
@pytest.mark.parametrize("size", [(640, 480), (300, 900)])
def test_crop_matches_vtk_projection_with_oblique_anisotropic_data_pan_zoom(volume, face, size):
    state = VolumeViewState(rotation=face_rotation(face), pan=(0.07, -0.04), zoom=1.7)
    polygon = np.array([(0.22, 0.18), (0.82, 0.29), (0.57, 0.5), (0.77, 0.85), (0.23, 0.76)]) * size
    kept = crop_keep_mask(volume.geometry, state, size, polygon, "outside")
    removed = crop_keep_mask(volume.geometry, state, size, polygon, "inside")
    np.testing.assert_array_equal(kept, ~removed)
    p = camera_parameters(volume.geometry, state, size)
    camera = vtkCamera()
    camera.ParallelProjectionOn()
    camera.SetPosition(*p["position"])
    camera.SetFocalPoint(*p["focal"])
    camera.SetViewUp(*p["up"])
    camera.SetParallelScale(p["scale"])
    matrix = camera.GetCompositeProjectionTransformMatrix(size[0]/size[1], -1, 1)
    outline = QPolygonF([QPointF(*point) for point in polygon])
    expected = np.zeros_like(kept)
    for index in np.ndindex(kept.shape):
        world = volume.geometry.voxel_to_patient @ [*index, 1]
        clip = matrix.MultiplyPoint(world)
        screen = QPointF((clip[0]/clip[3]+1)*size[0]/2, (1-clip[1]/clip[3])*size[1]/2)
        expected[index] = outline.containsPoint(screen, Qt.OddEvenFill)
    np.testing.assert_array_equal(kept, expected)
    previous = np.ones_like(kept)
    previous[0] = False
    np.testing.assert_array_equal(crop_keep_mask(volume.geometry, state, size, polygon, "outside", previous),
                                  previous & expected)


def test_concave_polygon_and_boundary_are_selected():
    polygon = np.array([(0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)])
    actual = polygon_contains(np.array([1, 4, 4, 2, 0]), np.array([4, 1, 4, 4, 0]), polygon)
    np.testing.assert_array_equal(actual, [True, True, False, True, True])


def draw(view, points=((180, 100), (430, 110), (400, 330), (200, 350)), mode=None):
    view._tools.activateTool("volume-crop")
    if mode is not None:
        view.setCropMode(mode)
    view.begin_drag(points[0], (640, 480))
    for point in points[1:]:
        view.update_drag(point)
    view.end_drag()
    assert not view.selection_points and view.editBusy


def wait_edit(app, view):
    deadline = time.monotonic()+10
    while view.editBusy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not view.editBusy
    assert not view.editMessage, view.editMessage


def test_bed_toggle_coexists_with_tools_and_crop_reset(qt_app, loaded_tab, ct_volume):
    view, tools = loaded_tab.activeViewport, loaded_tab.toolController
    view.volume = ct_volume
    tools.activateTool("pan")
    tools.activateTool("volume-bed")
    wait_edit(qt_app, view)
    assert view.bedRemovalEnabled and tools.activeInteraction == "pan"
    assert tools.activeTool == "pan"
    bed = view.visible_mask.copy()
    draw(view)
    assert tools.resetLabel == "清除裁剪"
    wait_edit(qt_app, view)
    crop = view.crop_mask.copy()
    np.testing.assert_array_equal(view.visible_mask, bed & crop)
    assert not view.selection_points
    tools.activateTool("volume-bed")
    assert not view.bedRemovalEnabled and tools.activePanel == "volume-crop"
    np.testing.assert_array_equal(view.visible_mask, crop)
    tools.activateTool("volume-bed")
    tools.activateTool("volume-preset")
    view.applyVolumePreset("mip")
    view.wheel_zoom(120, 0)
    pose, display = view.state, view.display_state
    tools.activateTool("volume-crop")
    tools.resetActiveTool()
    assert not view.hasCrop and view.bedRemovalEnabled
    assert view.state == pose and view.display_state == display
    np.testing.assert_array_equal(view.visible_mask, bed)
    assert make_tab("other").activeViewport.visible_mask is None
    tools.activateTool("reset")
    assert not view.bedRemovalEnabled and view.visible_mask is None


def test_invalid_or_interrupted_strokes_do_not_apply_and_crops_accumulate(qt_app, loaded_tab):
    view = loaded_tab.activeViewport
    tools = loaded_tab.toolController
    tools.activateTool("volume-crop")
    view.begin_drag((200, 200), (640, 480))
    view.update_drag((201, 201))
    view.end_drag()
    assert not view.selection_points
    assert not view.editBusy
    draw(view, mode="outside")
    wait_edit(qt_app, view)
    first = view.crop_mask.copy()
    draw(view, ((0, 0), (340, 0), (340, 480), (0, 480)), mode="inside")
    wait_edit(qt_app, view)
    assert np.all(view.crop_mask <= first)
    for change in (view.cancel_drag, view.viewport_resized, lambda: view.wheel_zoom(120, 0),
                   lambda: tools.activateTool("pan"), lambda: view.setNativeVisible(False)):
        tools.activateTool("volume-crop")
        view.begin_drag((100, 100), (640, 480))
        view.update_drag((300, 100))
        view.update_drag((300, 300))
        before = view.crop_mask
        change()
        view.end_drag()
        assert not view.selection_points and not view.editBusy
        assert view.crop_mask is before


def test_crop_mode_is_chosen_before_drawing_and_each_release_applies_once(qt_app, loaded_tab):
    view, tools = loaded_tab.activeViewport, loaded_tab.toolController
    tools.activateTool("volume-crop")
    assert view.cropMode == "inside"
    points = ((180, 100), (430, 110), (400, 330), (200, 350))
    for mode in ("inside", "outside"):
        view.resetCrop()
        view.setCropMode(mode)
        assert not view.editBusy and not view.hasCrop
        expected = crop_keep_mask(view.volume.geometry, view.state, (640, 480), points, mode)
        draw(view, points)
        token = view._edit_token
        view.end_drag()
        assert view._edit_token == token
        view.setCropMode("inside" if mode == "outside" else "outside")
        view.begin_drag((0, 0), (640, 480))
        assert view.cropMode == mode and not view.selection_points
        wait_edit(qt_app, view)
        np.testing.assert_array_equal(view.crop_mask, expected)
    view.setCropMode("invalid")
    assert view.cropMode == "outside"
    tools.activateTool("pan")
    tools.activateTool("volume-crop")
    assert view.cropMode == "inside"
    view.resetCrop()
    expected = crop_keep_mask(view.volume.geometry, view.state, (640, 480), points, "inside")
    draw(view, points)
    view.wheel_zoom(120, 0)
    wait_edit(qt_app, view)
    np.testing.assert_array_equal(view.crop_mask, expected)


@pytest.mark.parametrize("action", ["reset", "dispose", "render-error"])
def test_late_worker_result_cannot_restore_canceled_crop(loaded_tab, action):
    view = loaded_tab.activeViewport
    view._edit_token, view._edit_kind = 42, "crop"
    if action == "reset":
        view.resetCrop()
    elif action == "render-error":
        view.render_failed("renderer failed")
    else:
        view.dispose()
    view._edit_finished(42, "crop", np.zeros((3, 4, 5), dtype=bool), "")
    assert view.visible_mask is None and not view.editBusy and not view.hasCrop


def test_mask_processing_error_keeps_previous_state_and_unsupported_modes_are_disabled(loaded_tab):
    view = loaded_tab.activeViewport
    view._edit_token, view._edit_kind = 42, "bed"
    view._edit_finished(42, "bed", None, "未识别到人体")
    assert view.loadState == "ready" and not view.bedRemovalEnabled
    assert view.editMessage == "未识别到人体"
    view.viewport_config = replace(view.viewport_config,
        series_meta=replace(view.viewport_config.series_meta, modality="MR"))
    view.setBedRemovalEnabled(True)
    assert not view.bedRemovalAvailable and not view.editBusy
    for kind in (TabType.TWO_D, TabType.MPR, TabType.FOUR_D):
        tools = ToolController(tab_type=kind)
        assert not {"volume-bed", "volume-crop"} & {t["toolType"] for t in tools.tools}


def test_binary_mask_preserves_geometry_is_cached_and_can_be_removed(volume):
    window = vtkGenericOpenGLRenderWindow()
    interactor = vtkGenericRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    widget = Mock()
    widget.GetRenderWindow.return_value = window
    backend = VolumeRenderBackend(widget)
    try:
        backend.set_volume(volume)
        original = backend.mapper.GetInput()
        mask = np.ones(volume.modality_pixels.shape, dtype=bool)
        mask[:, :, :2] = False
        backend.apply_mask(mask)
        image = backend.mapper.GetMaskInput()
        np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()).reshape(mask.shape), mask*255)
        assert image.GetOrigin() == original.GetOrigin()
        assert image.GetSpacing() == original.GetSpacing()
        for row in range(3):
            for col in range(3):
                assert image.GetDirectionMatrix().GetElement(row, col) == original.GetDirectionMatrix().GetElement(row, col)
        stamp = image.GetMTime()
        backend.apply_mask(mask)
        assert backend.mapper.GetMaskInput().GetMTime() == stamp
        assert backend.mapper.GetInput() is original
        backend.apply_mask(None)
        assert backend.mapper.GetMaskInput() is None
    finally:
        backend.dispose()
