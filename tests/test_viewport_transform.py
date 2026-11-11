from dataclasses import replace

import numpy as np
import pytest

from voxplane.model import (
    FrameDisplayMeta,
    ImageGeometryMeta,
    InstanceDisplayMeta,
    PixelSpacing,
    SeriesDisplayMeta,
    StackRenderResult,
    ToolType,
    TwoDViewType,
    ViewportConfig,
    WindowLevel,
)
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.controller.viewport.image_2d.stack_viewport_controller import (
    StackViewportController,
)


def _controller(*, tab_type=None) -> StackViewportController:
    series_meta = SeriesDisplayMeta(
        patient_name="Example Patient",
        patient_id="P001",
        study_description="Study",
        series_description="Series",
        modality="CT",
        series_uid="series-1",
    )
    return StackViewportController(
        viewport_config=ViewportConfig(
            viewport_id="viewport-1",
            tab_id="tab-1",
            viewport_type=TwoDViewType.STACK,
            series_uid=series_meta.series_uid,
            series_meta=series_meta,
        ),
        tool_controller=ToolController(tab_type=tab_type),
    )


def _render_result(
    controller: StackViewportController,
) -> StackRenderResult:
    return StackRenderResult(
        response_id="request-1",
        viewport_id=controller.viewport_config.viewport_id,
        series_uid=controller.viewport_config.series_uid,
        view_type=TwoDViewType.STACK,
        image=np.zeros((2, 2), dtype=np.uint8),
        modality_pixel=np.zeros((2, 2), dtype=np.float32),
        frame_meta=FrameDisplayMeta(
            slice_index=0,
            slice_count=1,
            window=WindowLevel(center=40.0, width=400.0),
            inverted=False,
            instance_meta=InstanceDisplayMeta(
                instance_number=1,
                sop_instance_uid="sop-1",
                manufacturer=None,
                kvp=None,
                tube_current_ma=None,
                slice_thickness=None,
                rows=2,
                columns=2,
                pixel_spacing=(1.0, 1.0),
                image_position=(0.0, 0.0, 0.0),
                slice_location=0.0,
            ),
            geometry=ImageGeometryMeta(
                rows=2,
                columns=2,
                pixel_spacing=PixelSpacing(row=1.0, column=1.0),
                image_position_patient=(0.0, 0.0, 0.0),
                image_orientation_patient=(
                    1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                ),
            ),
        ),
    )


def test_rotation_actions_are_normalized_to_one_turn() -> None:
    controller = _controller()

    controller.applyTransformAction("rotate:cw90")
    assert controller.rotationDegrees == 90.0

    controller.applyTransformAction("rotate:cw90")
    assert controller.rotationDegrees == 180.0

    controller.applyTransformAction("rotate:ccw90")
    assert controller.rotationDegrees == 90.0

    controller.applyTransformAction("rotate:ccw90")
    assert controller.rotationDegrees == 0.0

    controller.applyTransformAction("rotate:ccw90")
    assert controller.rotationDegrees == 270.0


def test_mirror_actions_toggle_independently() -> None:
    controller = _controller()

    controller.applyTransformAction("rotate:mirror-h")
    assert controller.horizontalFlip is True
    assert controller.verticalFlip is False

    controller.applyTransformAction("rotate:mirror-v")
    assert controller.horizontalFlip is True
    assert controller.verticalFlip is True

    controller.applyTransformAction("rotate:mirror-h")
    assert controller.horizontalFlip is False
    assert controller.verticalFlip is True


def test_unknown_transform_action_is_ignored() -> None:
    controller = _controller()
    initial_state = controller.viewport_state

    controller.applyTransformAction("rotate:unsupported")

    assert controller.viewport_state == initial_state


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
def test_roi_uses_modality_pixels_and_is_independent_of_window_and_view_transform(kind):
    controller = _controller()
    pixels = np.array([[-1000, 0], [100, 4000]], dtype=float)
    result = replace(_render_result(controller), modality_pixel=pixels)
    controller.handleRenderResult(result)
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    controller.beginInteraction(0, 0, 1, False, -.5, -.5, .05, .05)
    controller.endInteraction(10, 10, False, 1.5, 1.5)
    item = controller.measurementController.measurementItems[0]
    assert item["type"] == kind
    assert item["metrics"]["mean"] == 775
    assert item["metrics"]["unit"] == "HU"
    controller.applyTransformAction("rotate:cw90")
    controller.applyTransformAction("rotate:mirror-h")
    controller.apply_zoom(3)
    controller.handleRenderResult(replace(result, frame_meta=replace(result.frame_meta,
                                   window=WindowLevel(center=100, width=50))))
    assert controller.measurementController.measurementItems == [item]


def test_measurements_are_hidden_on_other_slice_or_plane_and_restored_on_return():
    controller = _controller()
    original = _render_result(controller)
    controller.handleRenderResult(original)
    controller._tool_controller.selectInteraction("measure:rect")
    controller.beginInteraction(0, 0, 1, True, 0, 0, .05, .05)
    controller.endInteraction(10, 10, True, 1, 1)
    saved = controller.measurementController.measurementItems
    other_slice = replace(original, frame_meta=replace(original.frame_meta, slice_index=1))
    controller.handleRenderResult(other_slice)
    assert controller.measurementController.measurementItems == []
    controller.handleRenderResult(original)
    assert controller.measurementController.measurementItems == saved
    other_plane = replace(original, frame_meta=replace(original.frame_meta,
                          geometry=replace(original.frame_meta.geometry,
                          image_orientation_patient=(0, 1, 0, -1, 0, 0))))
    controller.handleRenderResult(other_plane)
    assert controller.measurementController.measurementItems == []
    controller.handleRenderResult(original)
    assert controller.measurementController.measurementItems == saved


def test_angle_viewport_clicks_and_tool_change_cancel_preview():
    controller = _controller()
    controller.handleRenderResult(_render_result(controller))
    controller._tool_controller.selectInteraction("measure:angle")
    for column, row in [(20, 0), (0, 0), (0, 20)]:
        controller.selectMeasurementAt(False, column, row, .05, .05)
    assert controller.measurementController.measurementItems[0]["label"] == "90.00°"
    controller.selectMeasurementAt(False, 100, 100, .05, .05)
    assert controller.measurementController.has_active_transaction
    controller._tool_controller.selectInteraction("measure:ellipse")
    assert not controller.measurementController.has_active_transaction


def test_scoped_resets_only_change_the_selected_tool_state() -> None:
    controller = _controller()
    controller.handleRenderResult(_render_result(controller))
    controller.apply_pan(12.0, -8.0)
    controller.apply_zoom(2.5)
    controller.applyTransformAction("rotate:cw90")

    controller.reset_tool_state(ToolType.PAN)

    assert controller.panX == 0.0
    assert controller.panY == 0.0
    assert controller.zoom == 2.5
    assert controller.rotationDegrees == 90.0

    controller.reset_tool_state(ToolType.ZOOM)
    controller.reset_tool_state(ToolType.ROTATE)

    assert controller.zoom == 1.0
    assert controller.rotationDegrees == 0.0


def test_reset_all_view_state_restores_all_display_transforms() -> None:
    controller = _controller()
    controller.handleRenderResult(_render_result(controller))
    controller.applyWindowPreset(80.0, 200.0)
    controller.apply_pan(12.0, -8.0)
    controller.apply_zoom(2.5)
    controller.applyTransformAction("rotate:mirror-h")

    controller.reset_all_view_state()

    assert controller.viewport_state.window == WindowLevel(40.0, 400.0)
    assert controller.panX == 0.0
    assert controller.panY == 0.0
    assert controller.zoom == 1.0
    assert controller.horizontalFlip is False


def test_direction_labels_follow_geometry_and_display_transform() -> None:
    controller = _controller()
    changes = []
    controller.directionLabelsChanged.connect(
        lambda: changes.append(controller.directionLabels)
    )

    assert controller.directionLabels == {
        "top": "",
        "right": "",
        "bottom": "",
        "left": "",
    }

    controller.handleRenderResult(_render_result(controller))

    assert controller.directionLabels == {
        "top": "A",
        "right": "L",
        "bottom": "P",
        "left": "R",
    }

    controller.applyTransformAction("rotate:cw90")

    assert controller.directionLabels == {
        "top": "R",
        "right": "A",
        "bottom": "L",
        "left": "P",
    }
    assert len(changes) == 2
