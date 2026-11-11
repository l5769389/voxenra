from dataclasses import replace
from unittest.mock import Mock

import numpy as np
import pytest
from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor

from voxplane.core.volume_view import (
    VolumeViewState, face_rotation, nearest_face, view_basis, drag_volume_window,
)
from voxplane.model import ToolType, WindowLevel
from voxplane.model.dicom_types import MrParameters
from voxplane.model.render_models import VolumeLoadResult
from voxplane.model.volume_models import VOLUME_DIRECTIONS, VolumeDisplayState, VolumeBlendMode
from voxplane.volume_presets import VOLUME_PRESETS, VOLUME_PRESET_BY_ID
from voxplane.ui.volume_render_backend import (
    VolumeRenderBackend, create_orientation_marker, create_transfer_functions,
)
from test_volume_view import make_tab, volume  # shared synthetic volume fixture


@pytest.fixture
def loaded_tab(volume):
    tab = make_tab()
    requests = []
    tab.renderRequested.connect(requests.append)
    tab.init_render()
    request = requests[-1]
    tab.handleRenderResult(VolumeLoadResult(response_id=request.request_id,
        viewport_id=request.viewport_id, series_uid=request.series_uid, volume=volume))
    return tab


@pytest.mark.parametrize("direction", VOLUME_DIRECTIONS, ids=lambda d: d.face)
def test_standard_faces_preserve_camera_handedness_and_anatomical_up(direction):
    state = replace(VolumeViewState(), rotation=face_rotation(direction.face))
    basis = view_basis(state)
    np.testing.assert_allclose(basis[:, 2], direction.normal, atol=1e-12)
    np.testing.assert_allclose(basis[:, 1], direction.up, atol=1e-12)
    assert np.linalg.det(basis) == pytest.approx(1)
    assert nearest_face(state) == direction.face


def test_initial_anterior_and_oblique_tie_preserves_single_direction():
    assert nearest_face(VolumeViewState()) == "A"
    diagonal = VolumeViewState(rotation=(np.cos(np.pi/8), 0, np.sin(np.pi/8), 0))
    assert nearest_face(diagonal, "A") == "A"
    assert nearest_face(diagonal, "L") == "L"
    assert nearest_face(diagonal, "P") == "A"
    beyond = VolumeViewState(rotation=(np.cos(np.pi/8+0.01), 0, np.sin(np.pi/8+0.01), 0))
    assert nearest_face(beyond, "A") == "L"


def test_cube_has_six_matching_surface_colors_and_white_letters():
    assembly, labels, surface = create_orientation_marker()
    assert assembly.GetParts().GetNumberOfItems() == 2
    data = surface.GetMapper().GetInput()
    actual = set()
    for i in range(data.GetNumberOfCells()):
        points = data.GetCell(i).GetPoints()
        normal = np.mean([points.GetPoint(j) for j in range(points.GetNumberOfPoints())], axis=0)
        d = max(VOLUME_DIRECTIONS, key=lambda d: np.dot(normal, d.normal))
        rgb = tuple(data.GetCellData().GetScalars().GetTuple3(i))
        assert rgb == tuple(int(d.color[k:k+2], 16) for k in (1, 3, 5))
        actual.add(rgb)
    assert len(actual) == 6
    assert labels.GetCubeProperty().GetOpacity() == 0
    assert not labels.GetTextEdgesVisibility()  # No edge-on outlines outside the cube faces.
    for axis, plus, minus in (("X", "L", "R"), ("Y", "P", "A"), ("Z", "S", "I")):
        for side, face in (("Plus", plus), ("Minus", minus)):
            assert getattr(labels, f"Get{axis}{side}FaceText")() == face
            assert getattr(labels, f"Get{axis}{side}FaceProperty")().GetColor() == (1, 1, 1)


@pytest.mark.parametrize("preset", VOLUME_PRESETS, ids=lambda p: p.preset_id)
def test_window_moves_color_and_opacity_together_preserving_curve_shape(preset):
    first, second = WindowLevel(center=0, width=100), WindowLevel(center=300, width=700)
    c1, a1 = create_transfer_functions(preset, first)
    c2, a2 = create_transfer_functions(preset, second)
    for t in sorted({*np.linspace(0, 1, 25), *[p[0] for p in preset.colors],
                     *[p[0] for p in preset.opacity]}):
        x1, x2 = first.center+first.width*(t-0.5), second.center+second.width*(t-0.5)
        np.testing.assert_allclose(c1.GetColor(x1), c2.GetColor(x2), atol=1e-12)
        assert a1.GetValue(x1) == pytest.approx(a2.GetValue(x2))


def test_presets_have_complete_ordered_curves_and_ct_windows():
    assert len({p.preset_id for p in VOLUME_PRESETS}) == len(VOLUME_PRESETS)
    assert {"aaa", "red", "cardiac", "muscle", "carotid", "bone-plate", "fracture",
            "lumbar", "hardware", "lung2", "lung3", "renals-stomach", "vessel-outline", "bones"} <= set(VOLUME_PRESET_BY_ID)
    for p in VOLUME_PRESETS:
        for points in (p.colors, p.opacity):
            assert np.isfinite(points).all()
            assert np.all(np.diff([node[0] for node in points]) > 0)
            values = np.asarray(points)[:, 1:]
            assert np.all((values >= 0) & (values <= 1))
        if p.ct_only:
            assert p.default_window is not None and p.default_window.width > 0
            _, opacity = create_transfer_functions(p, p.default_window)
            assert opacity.GetValue(-1000) == 0  # Outside air stays transparent.
    assert VOLUME_PRESET_BY_ID["bone"].default_window == WindowLevel(center=300, width=1500)
    assert VOLUME_PRESET_BY_ID["lung"].default_window == WindowLevel(center=-400, width=1500)
    assert VOLUME_PRESET_BY_ID["vessel"].default_window == WindowLevel(center=400, width=700)


def test_selection_windowing_and_resets_keep_independent_state(loaded_tab, volume):
    view, tools = loaded_tab.activeViewport, loaded_tab.toolController
    original_pixels = volume.modality_pixels.copy()
    view._set_state(VolumeViewState(pan=(0.2, 0.1), zoom=2))
    tools.activateTool("volume-direction")
    assert tools.activeInteraction == "volume:rotate"
    view.setViewFace("R")
    pose = view.state
    assert view.currentFace == "R" and pose.pan == (0.2, 0.1) and pose.zoom == 2
    tools.activateTool("volume-preset")
    assert tools.activeInteraction == "volume:rotate"
    view.applyVolumePreset("bone")
    assert view.state == pose and view.windowWidth == 1500
    tools.activateTool("window")
    assert tools.activeInteraction == "window" and tools.activePanel == "window"
    view.begin_drag((200, 200), (800, 600))
    view.update_drag((400, 50))
    expected = WindowLevel(center=307.375, width=1750)  # 59-unit source range
    assert view.display_state.window == expected
    view.update_drag((400, 50))  # Absolute drag offset, not cumulative increments.
    assert view.display_state.window == expected
    view.end_drag()
    assert view.state == pose and view.currentPresetId == "bone"
    tools.resetActiveTool()
    assert view.display_state.window == WindowLevel(center=300, width=1500)
    view.applyVolumePreset("lung")
    assert view.windowCenter == -400 and view.state == pose
    view._set_display_state(replace(view.display_state, window=WindowLevel(50, 100)))
    view.applyVolumePreset("lung")
    assert view.windowCenter == -400  # Selecting the same preset also resets it.
    view.reset_tool_state(ToolType.VOLUME_DIRECTION)
    assert view.currentFace == "A" and view.state.pan == pose.pan and view.currentPresetId == "lung"
    view.reset_tool_state(ToolType.VOLUME_PRESET)
    assert view.display_state == VolumeDisplayState("aaa", VOLUME_PRESET_BY_ID["aaa"].default_window)
    view.applyVolumePreset("vessel")
    view.setViewFace("P")
    tools.activateTool("reset")
    assert view.state == VolumeViewState()
    assert view.display_state == VolumeDisplayState("aaa", VOLUME_PRESET_BY_ID["aaa"].default_window)
    np.testing.assert_array_equal(volume.modality_pixels, original_pixels)


def test_window_drag_stops_at_one_without_inversion():
    result = drag_volume_window(WindowLevel(40, 80), (-10000, -100), (500, 500))
    assert result == WindowLevel(center=48, width=8)
    for _ in range(3):
        result = drag_volume_window(result, (-10000, 0), (500, 500))
    assert result.width == 1
    assert drag_volume_window(result, (100, 0), (500, 500)).width == pytest.approx(1.1)


@pytest.mark.parametrize("delta", [(0, -70), (0, 70), (85, 0), (-85, 0), (85, -70)])
def test_ct_gesture_matches_slicer_transfer_function_transform(delta):
    preset = VOLUME_PRESET_BY_ID["aaa"]
    original = preset.default_window
    updated = drag_volume_window(original, delta, (850, 700), scalar_range=3976,
                                 opacity_range=tuple(p[0] for p in preset.opacity))
    before_color, before_opacity = create_transfer_functions(preset, original)
    color, opacity = create_transfer_functions(preset, updated)
    factor = 1 + delta[0]*0.5/700
    shift = -delta[1]*3976*0.5/700
    # The Slicer opacity curve spans -3024..3071, so its pivot is 23.5 HU,
    # not the effective-window center (281.646 HU).
    for before, after, length in ((before_color, color, 6), (before_opacity, opacity, 4)):
        for index in range(before.GetSize()):
            p, q = [0.0]*length, [0.0]*length
            before.GetNodeValue(index, p)
            after.GetNodeValue(index, q)
            assert q[0] == pytest.approx(23.5 + (p[0]-23.5)*factor + shift)
            assert q[1:] == p[1:]


def test_ct_starts_in_color_without_reusing_2d_window(loaded_tab, volume):
    view = loaded_tab.activeViewport
    assert view.currentPresetId == "aaa"
    assert view.display_state.window == VOLUME_PRESET_BY_ID["aaa"].default_window
    assert volume.default_window == WindowLevel(0, 60)
    colors, opacity = create_transfer_functions(VOLUME_PRESET_BY_ID["aaa"], view.display_state.window)
    assert opacity.GetValue(100) == 0
    assert opacity.GetValue(166.222) == pytest.approx(.686275)
    np.testing.assert_allclose(colors.GetColor(166.222), (.882353, .603922, .290196))
    for preset_id in ("general", "mip", "xray"):
        view.applyVolumePreset(preset_id)
        assert view.display_state.window == volume.default_window


@pytest.mark.parametrize("modality", ["PT", "US", "OT"])
def test_non_ct_generic_presets_do_not_acquire_hu_defaults(loaded_tab, volume, modality):
    view = loaded_tab.activeViewport
    view.viewport_config = replace(view.viewport_config,
        series_meta=replace(view.viewport_config.series_meta, modality=modality))
    view.reset_all_view_state()
    assert view.display_state == VolumeDisplayState(window=volume.default_window)
    assert {p["presetId"] for p in view.volumePresets if p["available"]} == {"general", "mip", "xray"}


def test_non_ct_cannot_apply_ct_templates_or_invalid_selection(loaded_tab):
    view = loaded_tab.activeViewport
    view.viewport_config = replace(view.viewport_config,
        series_meta=replace(view.viewport_config.series_meta, modality="MR"))
    view.reset_all_view_state()
    assert {p["presetId"] for p in view.volumePresets if p["available"]} == {"mr-general", "mr-bright", "mr-mip"}
    for preset_id in (*[p.preset_id for p in VOLUME_PRESETS if p.ct_only], "unknown"):
        view.applyVolumePreset(preset_id)
        assert view.currentPresetId == "mr-general"
    view.setViewFace("invalid")
    assert view.currentFace == "A"
    view.applyVolumePreset("mr-mip")
    assert view.currentPresetId == "mr-mip"


@pytest.mark.parametrize("modality, sample_divisor", [("CT", 4), ("MR", 2)])
def test_display_updates_reuse_volume_and_camera_changes_reuse_transfer_functions(volume, modality, sample_divisor):
    volume = replace(volume, representative_instance_meta=replace(
        volume.representative_instance_meta,
        mr_parameters=MrParameters() if modality == "MR" else None))
    window = vtkGenericOpenGLRenderWindow()
    interactor = vtkGenericRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    widget = Mock()
    widget.GetRenderWindow.return_value = window
    widget.width.return_value, widget.height.return_value = 640, 480
    backend = VolumeRenderBackend(widget)
    try:
        backend.set_volume(volume)
        data = backend.mapper.GetInput()
        expected_step = min(volume.geometry.column_spacing,
                            volume.geometry.row_spacing,
                            volume.geometry.slice_spacing) / sample_divisor
        assert backend.mapper.GetSampleDistance() == pytest.approx(expected_step)
        assert backend.mapper.GetImageSampleDistance() == 1
        assert not backend.mapper.GetAutoAdjustSampleDistances()
        assert not backend.mapper.GetLockSampleDistanceToInputSpacing()
        assert data.GetSpacing() == (1, 1, 1)
        assert data.GetOrigin() == (0, 0, 0)
        # Rendering and masks still land at the exact patient coordinates,
        # including oblique, anisotropic volumes and nonzero origins.
        matrix = backend.actor.GetMatrix()
        for k, j, i in ((0, 0, 0), (2, 3, 4), (1, 2, 3)):
            np.testing.assert_allclose(matrix.MultiplyPoint((i, j, k, 1)),
                                       volume.geometry.voxel_to_patient @ [k, j, i, 1])
        for p in VOLUME_PRESETS:
            state = VolumeDisplayState(p.preset_id, p.default_window or volume.default_window)
            backend.apply_display(VolumeDisplayState(p.preset_id))
            assert backend._applied_display == state
            backend.apply_display(state)
            colors = backend.properties.GetRGBTransferFunction()
            stamp = colors.GetMTime()
            backend.apply_state(VolumeViewState(zoom=2))
            backend.apply_display(state)
            assert backend.properties.GetRGBTransferFunction().GetMTime() == stamp
            assert backend.mapper.GetInput() is data
            assert backend.properties.GetShade() == p.shade
            assert backend.mapper.GetBlendMode() == {
                VolumeBlendMode.COMPOSITE: 0, VolumeBlendMode.MIP: 1, VolumeBlendMode.ADDITIVE: 4,
            }[p.blend_mode]
            assert backend.mapper.GetSampleDistance() == pytest.approx(expected_step)
            assert backend.mapper.GetImageSampleDistance() == 1
            assert not backend.mapper.GetAutoAdjustSampleDistances()
            changed = replace(state, window=WindowLevel(200, 400))
            backend.apply_display(changed)
            assert backend.properties.GetRGBTransferFunction().GetMTime() != stamp
    finally:
        backend.dispose()


def test_tabs_do_not_share_display_state(loaded_tab, volume):
    other_tab = make_tab("other")
    other = other_tab.activeViewport
    loaded_tab.activeViewport.applyVolumePreset("bone")
    assert other.currentPresetId == "general" and other.windowWidth == 0
    assert other.state == VolumeViewState()


def test_disposed_view_ignores_queued_menu_and_pointer_actions(loaded_tab):
    view = loaded_tab.activeViewport
    view.applyVolumePreset("bone")
    view.setViewFace("P")
    pose, display = view.state, view.display_state
    view.dispose()
    view.applyVolumePreset("lung")
    view.setViewFace("A")
    view.begin_drag((0, 0), (600, 600))
    view.update_drag((100, 100))
    view.wheel_zoom(120, 0)
    view.reset_tool_state(ToolType.VOLUME_PRESET)
    view.reset_all_view_state()
    assert view.state == pose and view.display_state == display
    assert view.volume is None


@pytest.mark.parametrize('pixel_ratio', [1, 2])
def test_orientation_cube_resizes_with_viewport_without_reloading_volume(volume, pixel_ratio):
    window = vtkGenericOpenGLRenderWindow()
    interactor = vtkGenericRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    widget = Mock()
    widget.GetRenderWindow.return_value = window
    backend = VolumeRenderBackend(widget)
    try:
        backend.set_volume(volume)
        data = backend.mapper.GetInput()
        edges = []
        for width, height in ((1920, 1080), (800, 600), (380, 330), (240, 320), (120, 80), (1, 1)):
            widget.width.return_value, widget.height.return_value = width, height
            window.SetSize(width * pixel_ratio, height * pixel_ratio)
            backend.apply_state(VolumeViewState())
            left, bottom, right, top = backend.marker.GetViewport()
            assert 0 <= left < right <= 1 and 0 <= bottom < top <= 1
            edge = (right-left)*width
            assert edge == pytest.approx((top-bottom)*height)
            assert edge <= min(96, min(width, height)*.25) + 1e-8
            assert (1-right)*width == pytest.approx((1-top)*height)
            if min(width, height) >= 240:
                assert edge >= 48 - 1e-8
            edges.append(edge)
            assert backend.mapper.GetInput() is data
        assert edges == sorted(edges, reverse=True)
        assert edges[2] < edges[0]*.7  # A small quad cell no longer gets the full-size cube.
    finally:
        backend.dispose()
