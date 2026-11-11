import numpy as np
import pytest
from PySide6.QtCore import QPointF

from voxplane.model import (
    CrosshairCenterChange,
    CrosshairMoveContext,
    CrosshairRotationContext,
    FrameDisplayMeta,
    ImageGeometryMeta,
    ImagePoint,
    InstanceDisplayMeta,
    InteractionType,
    MprFrame,
    MprGridAnchor,
    MprGridSpec,
    MprImageGeometry,
    Mpr3DRotationChange,
    Mpr3DRotationContext,
    MprPlane,
    MprProjectionSettings,
    MprRenderRequest,
    MprRenderResult,
    MprState,
    MprViewAnchors,
    MprViewGrids,
    PixelSpacing,
    Point,
    PointerPosition,
    SeriesDisplayMeta,
    StackRenderRequest,
    StackRenderResult,
    RenderFailure,
    TabConfig,
    TabType,
    TwoDViewType,
    ViewportConfig,
    WindowLevel,
)
from voxplane.ui.controller.tab.tab_controller import TabController
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.controller.viewport.image_2d.mpr_viewport_controller import (
    MprViewportController,
)
from voxplane.ui.controller.viewport.image_2d.stack_viewport_controller import (
    StackViewportController,
)
from voxplane.ui.controller.viewport.viewport_controller import (
    ViewportController,
)


def _series_meta() -> SeriesDisplayMeta:
    return SeriesDisplayMeta(
        patient_name="Example Patient",
        patient_id="P001",
        study_description="Study",
        series_description="Series",
        modality="CT",
        series_uid="series-1",
    )


def _viewport_config(viewport_type) -> ViewportConfig:
    series_meta = _series_meta()
    return ViewportConfig(
        viewport_id=f"viewport-{viewport_type.value}",
        tab_id="tab-1",
        viewport_type=viewport_type,
        series_uid=series_meta.series_uid,
        series_meta=series_meta,
    )


def _frame_meta() -> FrameDisplayMeta:
    return FrameDisplayMeta(
        slice_index=2,
        slice_count=5,
        window=WindowLevel(center=40.0, width=400.0),
        inverted=False,
        instance_meta=InstanceDisplayMeta(
            instance_number=None,
            sop_instance_uid=None,
            manufacturer=None,
            kvp=None,
            tube_current_ma=None,
            slice_thickness=None,
            rows=3,
            columns=4,
            pixel_spacing=(2.0, 3.0),
            image_position=None,
            slice_location=None,
        ),
        geometry=ImageGeometryMeta(
            rows=3,
            columns=4,
            pixel_spacing=PixelSpacing(row=2.0, column=3.0),
            image_position_patient=(10.0, 20.0, 30.0),
            image_orientation_patient=None,
        ),
    )


def _mpr_geometry(frame: MprFrame) -> MprImageGeometry:
    return MprImageGeometry(
        rows=3,
        columns=4,
        row_spacing=2.0,
        column_spacing=3.0,
        navigation_spacing=1.0,
        frame=frame,
        image_origin_mpr=(0.0, 0.0, 0.0),
        row_direction_mpr=(0.0, 1.0, 0.0),
        column_direction_mpr=(1.0, 0.0, 0.0),
        navigation_direction_mpr=(0.0, 0.0, 1.0),
    )


def _mpr_geometry_for_plane(
    frame: MprFrame,
    plane: MprPlane,
) -> MprImageGeometry:
    axes = {
        MprPlane.AXIAL: (
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        MprPlane.CORONAL: (
            (0.0, 0.0, -1.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        MprPlane.SAGITTAL: (
            (0.0, 0.0, -1.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ),
    }
    row, column, navigation = axes[plane]
    return MprImageGeometry(
        rows=101,
        columns=101,
        row_spacing=2.0,
        column_spacing=3.0,
        navigation_spacing=1.0,
        frame=frame,
        image_origin_mpr=(0.0, 0.0, 0.0),
        row_direction_mpr=row,
        column_direction_mpr=column,
        navigation_direction_mpr=navigation,
    )


def _mpr_result(
    controller: MprViewportController,
    frame: MprFrame,
    response_id: str = "request-1",
    view_grids: MprViewGrids | None = None,
) -> MprRenderResult:
    geometry = _mpr_geometry(frame)
    return MprRenderResult(
        response_id=response_id,
        viewport_id=controller.viewport_config.viewport_id,
        series_uid=controller.viewport_config.series_uid,
        view_type=controller.viewport_config.viewport_type,
        image=np.zeros((3, 4), dtype=np.uint8),
        modality_pixel=np.zeros((3, 4), dtype=np.float32),
        frame_meta=_frame_meta(),
        mpr_frame=frame,
        plane_geometry=geometry,
        mpr_view_grids=view_grids,
    )


def test_concrete_controllers_share_the_root_type() -> None:
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        ToolController(),
    )
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        ToolController(),
    )

    assert isinstance(stack, ViewportController)
    assert isinstance(mpr, ViewportController)


def test_concrete_controllers_reject_mismatched_configs() -> None:
    with pytest.raises(ValueError):
        StackViewportController(
            _viewport_config(MprPlane.AXIAL),
            ToolController(),
        )
    with pytest.raises(ValueError):
        MprViewportController(
            _viewport_config(TwoDViewType.STACK),
            ToolController(),
        )


def test_concrete_controllers_build_typed_requests() -> None:
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        ToolController(),
    )
    mpr = MprViewportController(
        _viewport_config(MprPlane.CORONAL),
        ToolController(),
    )
    stack_requests = []
    mpr_requests = []
    stack.renderRequested.connect(stack_requests.append)
    mpr.renderRequested.connect(mpr_requests.append)

    stack.request_first_loader()
    mpr.request_first_loader()

    assert isinstance(stack_requests[0], StackRenderRequest)
    assert stack_requests[0].slice_index == 0
    assert isinstance(mpr_requests[0], MprRenderRequest)
    assert mpr_requests[0].plane == MprPlane.CORONAL
    assert mpr_requests[0].mpr_frame is None


def test_concrete_controllers_reject_wrong_result_types() -> None:
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        ToolController(),
    )
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        ToolController(),
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    mpr_result = _mpr_result(mpr, frame)
    stack_result = StackRenderResult(
        response_id="request-2",
        viewport_id=mpr.viewport_config.viewport_id,
        series_uid=mpr.viewport_config.series_uid,
        view_type=TwoDViewType.STACK,
        image=None,
        modality_pixel=None,
        frame_meta=_frame_meta(),
    )
    stack_state = stack.viewport_state
    mpr_state = mpr.viewport_state

    with pytest.raises(TypeError):
        stack.handleRenderResult(
            MprRenderResult(
                response_id=mpr_result.response_id,
                viewport_id=stack.viewport_config.viewport_id,
                series_uid=mpr_result.series_uid,
                view_type=mpr_result.view_type,
                image=mpr_result.image,
                modality_pixel=mpr_result.modality_pixel,
                frame_meta=mpr_result.frame_meta,
                mpr_frame=mpr_result.mpr_frame,
                plane_geometry=mpr_result.plane_geometry,
            )
        )
    with pytest.raises(TypeError):
        mpr.handleRenderResult(stack_result)

    assert stack.viewport_state == stack_state
    assert mpr.viewport_state == mpr_state


def test_stack_exposes_safe_empty_crosshair_properties() -> None:
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        ToolController(),
    )

    assert stack.crosshairImagePosition.x() == -1.0
    assert stack.crosshairImagePosition.y() == -1.0
    assert stack.crosshairStyle["lineWidth"] == 0
    assert stack.crosshairHoverTarget == ""


def test_stack_exposes_slice_state_and_clamps_slider_updates() -> None:
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        ToolController(),
    )
    result = StackRenderResult(
        response_id="request-1",
        viewport_id=stack.viewport_config.viewport_id,
        series_uid=stack.viewport_config.series_uid,
        view_type=TwoDViewType.STACK,
        image=np.zeros((3, 4), dtype=np.uint8),
        modality_pixel=np.zeros((3, 4), dtype=np.float32),
        frame_meta=_frame_meta(),
    )
    requests = []
    changes = []
    stack.renderRequested.connect(requests.append)
    stack.sliceChanged.connect(
        lambda: changes.append((stack.sliceIndex, stack.sliceCount))
    )

    stack.handleRenderResult(result)

    assert stack.sliceIndex == 2
    assert stack.sliceCount == 5
    assert changes == [(2, 5)]

    stack.setSliceIndex(99)

    assert stack.sliceIndex == 4
    assert requests[-1].slice_index == 4

    stack.setSliceIndex(-10)

    assert stack.sliceIndex == 0
    assert requests[-1].slice_index == 0


def test_stack_measurement_can_extend_beyond_image_across_canvas() -> None:
    tool_controller = ToolController()
    tool_controller.selectInteraction(InteractionType.MEASURE_LENGTH.value)
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        tool_controller,
    )
    stack.handleRenderResult(
        StackRenderResult(
            response_id="request-1",
            viewport_id=stack.viewport_config.viewport_id,
            series_uid=stack.viewport_config.series_uid,
            view_type=TwoDViewType.STACK,
            image=np.zeros((3, 4), dtype=np.uint8),
            modality_pixel=np.zeros((3, 4), dtype=np.float32),
            frame_meta=_frame_meta(),
        )
    )

    # image_valid=False 表示点在图像矩形外，但坐标仍来自视口画布。
    stack.beginInteraction(
        10.0, 10.0, 1,
        False, -10.0, 1.0,
        2.0, 2.0,
    )
    stack.updateInteraction(
        QPointF(10.0, 10.0),
        QPointF(20.0, 10.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 0.0),
        False, -20.0, 1.0,
    )

    assert stack.measurementController.activeTransaction["startColumn"] == -10.0
    assert stack.measurementController.activeTransaction["endColumn"] == -20.0

    stack.endInteraction(
        20.0, 10.0,
        False, -20.0, 1.0,
    )

    assert len(stack.measurementController.measurementItems) == 1
    assert stack.measurementController.measurementItems[0]["label"] == "30.00 mm"


def test_viewport_exposes_active_interaction_for_cursor_selection() -> None:
    tool_controller = ToolController()
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        tool_controller,
    )
    changes: list[str] = []
    stack.activeInteractionChanged.connect(
        lambda: changes.append(stack.activeInteraction)
    )

    assert stack.activeInteraction == InteractionType.WINDOW.value

    tool_controller.selectInteraction(InteractionType.SCROLL.value)

    assert stack.activeInteraction == InteractionType.SCROLL.value
    assert changes == [InteractionType.SCROLL.value]


def test_pixel_sampling_remains_available_while_window_tool_is_idle() -> None:
    tool_controller = ToolController()
    stack = StackViewportController(
        _viewport_config(TwoDViewType.STACK),
        tool_controller,
    )
    stack.handleRenderResult(
        StackRenderResult(
            response_id="request-1",
            viewport_id=stack.viewport_config.viewport_id,
            series_uid=stack.viewport_config.series_uid,
            view_type=TwoDViewType.STACK,
            image=np.zeros((3, 4), dtype=np.uint8),
            modality_pixel=np.zeros((3, 4), dtype=np.float32),
            frame_meta=_frame_meta(),
        )
    )

    # 是否处于鼠标按压周期由 QML InteractionLayer 负责拦截；
    # Controller 收到普通悬停位置时始终读取 X/Y/CT。
    stack.updateCursorPosition(
        10.0, 10.0,
        1.0, 1.0,
        1.0, 1.0,
        True, 2.0, 2.0,
    )
    assert stack.cursorController.cursorInfo == {
        "inside": True,
        "x": "1",
        "y": "1",
        "value": "0",
        "unit": "HU",
        "label": "CT",
    }


def test_mpr_crosshair_uses_the_viewports_geometry() -> None:
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        ToolController(),
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    centers = []
    mpr.crosshairCenterChangeRequested.connect(centers.append)
    mpr.handleRenderResult(_mpr_result(mpr, frame))

    assert mpr.crosshairImagePosition.x() == 0.0
    assert mpr.crosshairImagePosition.y() == 0.0

    handled = mpr._apply_specific_interaction_result(
        CrosshairCenterChange(ImagePoint(column=2.0, row=1.0))
    )

    assert handled is True
    assert centers == [(16.0, 22.0, 30.0)]


def test_mpr_slab_guides_skip_own_view_and_use_physical_half_thickness() -> None:
    tools = ToolController(tab_type=TabType.MPR)
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    state = MprState(frame)
    coronal = MprViewportController(
        _viewport_config(MprPlane.CORONAL),
        tools,
    )
    axial = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        tools,
    )

    for controller in (coronal, axial):
        result = _mpr_result(controller, frame)
        controller.handleRenderResult(
            MprRenderResult(
                response_id=result.response_id,
                viewport_id=result.viewport_id,
                series_uid=result.series_uid,
                view_type=result.view_type,
                image=result.image,
                modality_pixel=result.modality_pixel,
                frame_meta=result.frame_meta,
                mpr_frame=frame,
                plane_geometry=_mpr_geometry_for_plane(
                    frame,
                    controller.viewport_config.viewport_type,
                ),
            )
        )
        controller.apply_mpr_state(state)

    tools.setMprThickness("axial", 10)
    tools.setMprProjectionEnabled(True)

    assert axial.mprSlabGuides == []
    assert len(coronal.mprSlabGuides) == 2
    assert {guide["color"] for guide in coronal.mprSlabGuides} == {"#ff0000"}
    tools.settingsController.setValue("crosshair", "axialColor", "#123456")
    assert {guide["color"] for guide in coronal.mprSlabGuides} == {"#123456"}
    assert sorted(
        guide["anchorRow"] for guide in coronal.mprSlabGuides
    ) == pytest.approx([-2.5, 2.5])
    assert all(
        abs(guide["directionColumn"]) > 0
        and abs(guide["directionRow"]) < 1e-10
        for guide in coronal.mprSlabGuides
    )


def test_axial_3d_rotation_inverts_screen_angle_for_sampling_axes() -> None:
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        ToolController(),
    )
    rotations = []
    mpr.mpr3DRotationRequested.connect(
        lambda axis, angle: rotations.append((axis, angle))
    )

    handled = mpr._apply_specific_interaction_result(
        Mpr3DRotationChange(
            axis_patient=(0.0, 0.0, 1.0),
            angle_delta_radians=0.25,
        )
    )

    assert handled is True
    assert rotations == [((0.0, 0.0, 1.0), -0.25)]


def test_mpr_crosshair_hover_distinguishes_center_and_lines() -> None:
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        ToolController(),
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    mpr.handleRenderResult(_mpr_result(mpr, frame))

    def hover(column: float, row: float, valid: bool = True) -> str:
        mpr.updateCursorPosition(
            0.0,
            0.0,
            column,
            row,
            0.0,
            0.0,
            valid,
            # MPR 命中容差使用毫米；此几何的间距为 2/3 mm。
            0.5,
            0.5,
        )
        return mpr.crosshairHoverTarget

    assert hover(0.1, 0.1) == "center"
    assert hover(2.0, 0.1) == "horizontalLine"
    assert hover(0.1, 2.0) == "verticalLine"
    assert hover(2.0, 2.0) == ""
    # 图像矩形外仍使用连续图像坐标，十字线移出影像后依然可命中。
    assert hover(0.0, 0.0, valid=False) == "center"


def test_mpr_crosshair_drag_continues_outside_image_bounds() -> None:
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        ToolController(),
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    mpr.handleRenderResult(_mpr_result(mpr, frame))
    centers = []
    mpr.crosshairCenterChangeRequested.connect(centers.append)

    mpr.beginInteraction(
        10.0, 10.0, 1,
        True, 0.0, 0.0,
        0.5, 0.5,
    )
    mpr.updateInteraction(
        QPointF(10.0, 10.0),
        QPointF(-20.0, 200.0),
        QPointF(-30.0, 190.0),
        QPointF(-30.0, 190.0),
        False, -5.0, 110.0,
    )

    assert centers == [(-5.0, 240.0, 30.0)]


def test_stale_mip_render_result_does_not_rewind_crosshair_anchor() -> None:
    tools = ToolController(tab_type=TabType.MPR)
    tools.setMprThickness("axial", 30)
    tools.setMprProjectionEnabled(True)
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        tools,
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    grid = MprGridSpec(101, 101, 2.0, 3.0)
    grids = MprViewGrids(grid, grid, grid)
    centered = MprViewAnchors.centered(grids)
    initial_state = MprState(
        frame,
        view_grids=grids,
        view_anchors=centered,
    )
    mpr.apply_mpr_state(initial_state)
    mpr.handleRenderResult(_mpr_result(mpr, frame))
    assert mpr.crosshairImagePosition == QPointF(50.0, 50.0)

    latest_anchors = MprViewAnchors(
        axial=MprGridAnchor(57.0, 46.0),
        coronal=centered.coronal,
        sagittal=centered.sagittal,
    )
    latest_state = MprState(
        MprFrame.standard_lps((31.0, 12.0, 30.0)),
        view_grids=grids,
        view_anchors=latest_anchors,
    )
    mpr.apply_mpr_state(latest_state)
    assert mpr.crosshairImagePosition == QPointF(57.0, 46.0)

    # 模拟拖动期间较慢的旧 MIP 请求返回。
    mpr.handleRenderResult(_mpr_result(mpr, frame, "stale-mip"))
    assert mpr.crosshairImagePosition == QPointF(57.0, 46.0)


def test_crosshair_interactions_take_priority_over_3d_rotation() -> None:
    tool_controller = ToolController()
    tool_controller.selectInteraction(InteractionType.MPR_ROTATE_3D)
    mpr = MprViewportController(
        _viewport_config(MprPlane.AXIAL),
        tool_controller,
    )
    mpr.handleRenderResult(
        _mpr_result(
            mpr,
            MprFrame.standard_lps((10.0, 20.0, 30.0)),
        )
    )

    def interaction_context(
        column: float,
        row: float,
    ):
        interaction = mpr._begin_specific_interaction(
            PointerPosition(
                viewport=Point(column, row),
                image=ImagePoint(column, row),
            ),
            endpoint_tolerance=0.5,
            line_tolerance=0.5,
        )
        assert interaction is not None
        return interaction[1]

    assert isinstance(
        interaction_context(0.1, 0.1),
        CrosshairMoveContext,
    )
    assert isinstance(
        interaction_context(2.0, 0.1),
        CrosshairRotationContext,
    )
    assert isinstance(
        interaction_context(2.0, 2.0),
        Mpr3DRotationContext,
    )


def test_tab_creates_specific_controller_types() -> None:
    stack_tab = TabController(
        TabConfig("stack-tab", "Stack", TabType.TWO_D, (_series_meta(),))
    )
    mpr_tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )

    assert all(
        isinstance(viewport, StackViewportController)
        for viewport in stack_tab.viewports_by_id.values()
    )
    assert all(
        isinstance(viewport, MprViewportController)
        for viewport in mpr_tab.viewports_by_id.values()
    )


def test_tab_updates_shared_frame_and_rerenders_all_mpr_views() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    axial = next(
        viewport
        for viewport in tab.viewports_by_id.values()
        if viewport.viewport_config.viewport_type == MprPlane.AXIAL
    )
    assert isinstance(axial, MprViewportController)
    requests = []
    tab.renderRequested.connect(requests.append)

    initial_frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    tab.init_render()
    assert len(requests) == 1
    initial_request = requests.pop()
    tab.handleRenderResult(
        _mpr_result(
            axial,
            initial_frame,
            initial_request.request_id,
        )
    )

    assert len(requests) == 2
    for request in list(requests):
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        tab.handleRenderResult(
            _mpr_result(
                viewport,
                initial_frame,
                request.request_id,
            )
        )
    requests.clear()

    axial.crosshairCenterChangeRequested.emit((11.0, 22.0, 33.0))

    assert tab._target_mpr_state.frame is not None
    assert tab._target_mpr_state.frame.center_patient == (11.0, 22.0, 33.0)
    assert len(requests) == 3
    assert all(isinstance(request, MprRenderRequest) for request in requests)
    assert all(
        request.mpr_frame is not None
        and request.mpr_frame.center_patient == (11.0, 22.0, 33.0)
        for request in requests
    )


def test_tab_propagates_fixed_grid_to_each_mpr_view() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    requests = []
    tab.renderRequested.connect(requests.append)
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    grids = MprViewGrids(
        axial=MprGridSpec(100, 120, 0.8, 0.8),
        coronal=MprGridSpec(80, 120, 1.2, 0.8),
        sagittal=MprGridSpec(80, 100, 1.2, 0.8),
    )

    tab.init_render()
    initial_request = requests.pop()
    axial = tab.viewports_by_id[initial_request.viewport_id]
    assert isinstance(axial, MprViewportController)
    tab.handleRenderResult(
        _mpr_result(
            axial,
            frame,
            initial_request.request_id,
            grids,
        )
    )

    assert len(requests) == 2
    for request in requests:
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        plane = viewport.viewport_config.viewport_type
        assert request.mpr_grid == grids.for_plane(plane)
        assert request.mpr_grid_anchor is not None
        assert request.mpr_grid_anchor.column == pytest.approx(
            (request.mpr_grid.columns - 1) / 2.0
        )
        assert request.mpr_grid_anchor.row == pytest.approx(
            (request.mpr_grid.rows - 1) / 2.0
        )


def test_mpr_render_coalesces_drag_updates_to_the_latest_frame() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    requests = []
    tab.renderRequested.connect(requests.append)
    initial_frame = MprFrame.standard_lps((10.0, 20.0, 30.0))

    tab.init_render()
    initial_request = requests.pop()
    axial = tab.viewports_by_id[initial_request.viewport_id]
    assert isinstance(axial, MprViewportController)
    tab.handleRenderResult(
        _mpr_result(axial, initial_frame, initial_request.request_id)
    )
    for request in list(requests):
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        tab.handleRenderResult(
            _mpr_result(viewport, initial_frame, request.request_id)
        )
    requests.clear()

    axial.crosshairCenterChangeRequested.emit((11.0, 21.0, 31.0))
    active_requests = list(requests)
    axial.crosshairCenterChangeRequested.emit((12.0, 22.0, 32.0))
    axial.crosshairCenterChangeRequested.emit((13.0, 23.0, 33.0))

    assert requests == active_requests
    for request in active_requests:
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        tab.handleRenderResult(
            _mpr_result(
                viewport,
                request.mpr_frame,
                request.request_id,
            )
        )

    next_requests = requests[len(active_requests):]
    assert len(next_requests) == 3
    assert all(
        request.mpr_frame is not None
        and request.mpr_frame.center_patient == (13.0, 23.0, 33.0)
        for request in next_requests
    )


def test_mpr_single_view_invalidation_starts_one_request() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    requests = []
    tab.renderRequested.connect(requests.append)
    initial_frame = MprFrame.standard_lps((10.0, 20.0, 30.0))

    tab.init_render()
    initial_request = requests.pop()
    axial = tab.viewports_by_id[initial_request.viewport_id]
    assert isinstance(axial, MprViewportController)
    tab.handleRenderResult(
        _mpr_result(axial, initial_frame, initial_request.request_id)
    )
    for request in list(requests):
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        tab.handleRenderResult(
            _mpr_result(viewport, initial_frame, request.request_id)
        )
    requests.clear()

    axial.request_render()

    assert len(requests) == 1
    assert requests[0].viewport_id == axial.viewport_config.viewport_id


def test_mip_setting_changes_render_only_effective_planes_and_coalesce() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    tab._set_target_mpr_state(MprState(frame))
    requests = []
    tab.renderRequested.connect(requests.append)

    tab.toolController.setMprThickness("axial", 20)
    assert requests == []

    tab.toolController.setMprProjectionEnabled(True)
    assert len(requests) == 1
    first = requests[0]
    assert first.plane == MprPlane.AXIAL
    assert first.projection_mode.value == "mip"
    assert first.slab_thickness_mm == 20.0

    tab.toolController.setMprThickness("axial", 21)
    tab.toolController.setMprThickness("axial", 22)
    assert len(requests) == 1

    viewport = tab.viewports_by_id[first.viewport_id]
    assert isinstance(viewport, MprViewportController)
    tab.handleRenderResult(
        _mpr_result(viewport, frame, first.request_id)
    )

    assert len(requests) == 2
    assert requests[1].plane == MprPlane.AXIAL
    assert requests[1].slab_thickness_mm == 22.0


def test_mip_mode_change_renders_each_enabled_plane() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    tab._set_target_mpr_state(
        MprState(MprFrame.standard_lps((10.0, 20.0, 30.0)))
    )
    tab.toolController.setMprThickness("axial", 10)
    tab.toolController.setMprThickness("sagittal", 12)
    tab.toolController.setMprProjectionEnabled(True)
    active = list(tab._active_mpr_requests)
    for request_id in active:
        viewport_id = tab._active_mpr_requests[request_id]
        tab.handleRenderFailure(
            RenderFailure(
                request_id=request_id,
                viewport_id=viewport_id,
                error=RuntimeError("done"),
            )
        )

    requests = []
    tab.renderRequested.connect(requests.append)
    tab.toolController.setMprProjectionMode("mean")

    assert {request.plane for request in requests} == {
        MprPlane.AXIAL,
        MprPlane.SAGITTAL,
    }
    assert all(request.projection_mode.value == "mean" for request in requests)


def test_mip_scoped_and_global_reset_restore_defaults() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    state = MprState(frame)
    tab._initial_mpr_state = state
    tab._set_target_mpr_state(state)
    requests = []
    tab.renderRequested.connect(requests.append)

    def finish_active_requests() -> None:
        for request_id, viewport_id in list(tab._active_mpr_requests.items()):
            viewport = tab.viewports_by_id[viewport_id]
            assert isinstance(viewport, MprViewportController)
            tab.handleRenderResult(
                _mpr_result(viewport, frame, request_id)
            )

    tab.toolController.setMprThickness("coronal", 18)
    tab.toolController.setMprProjectionMode("sum")
    tab.toolController.setMprProjectionEnabled(True)
    finish_active_requests()
    tab.toolController.activateTool("mip")
    tab.toolController.resetActiveTool()

    assert tab.toolController.mpr_projection_settings == MprProjectionSettings()
    finish_active_requests()

    tab.toolController.setMprThickness("axial", 12)
    tab.toolController.setMprProjectionEnabled(True)
    finish_active_requests()
    tab.toolController.activateTool("reset")

    assert tab.toolController.mprProjectionEnabled is False
    assert tab.toolController.mprProjectionMode == "mip"
    assert set(tab.toolController.mprThicknesses.values()) == {0}


def test_tab_schedules_crosshair_and_3d_rotation_differently() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    requests = []
    tab.renderRequested.connect(requests.append)
    initial_frame = MprFrame.standard_lps((10.0, 20.0, 30.0))

    tab.init_render()
    initial_request = requests.pop()
    axial = tab.viewports_by_id[initial_request.viewport_id]
    assert isinstance(axial, MprViewportController)
    tab.handleRenderResult(
        _mpr_result(axial, initial_frame, initial_request.request_id)
    )
    for request in list(requests):
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        tab.handleRenderResult(
            _mpr_result(viewport, initial_frame, request.request_id)
        )
    requests.clear()

    axial.crosshairRotationRequested.emit(MprPlane.AXIAL, 0.2)

    assert len(requests) == 2
    assert all(
        request.viewport_id != axial.viewport_config.viewport_id
        for request in requests
    )
    assert tab._target_mpr_state is not None
    assert (
        tab._target_mpr_state.view_rolls.axial_radians
        == pytest.approx(-0.2)
    )
    for request in list(requests):
        viewport = tab.viewports_by_id[request.viewport_id]
        assert isinstance(viewport, MprViewportController)
        assert request.mpr_frame is not None
        tab.handleRenderResult(
            _mpr_result(
                viewport,
                request.mpr_frame,
                request.request_id,
            )
        )
    requests.clear()

    axial.mpr3DRotationRequested.emit((1.0, 0.0, 0.0), 0.1)

    assert len(requests) == 3
    assert {
        request.viewport_id for request in requests
    } == set(tab._mpr_viewport_ids())


def test_scoped_3d_reset_preserves_crosshair_rotation_but_full_reset_does_not() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    requests = []
    tab.renderRequested.connect(requests.append)
    initial_frame = MprFrame.standard_lps((10.0, 20.0, 30.0))

    tab.init_render()
    initial_request = requests.pop()
    axial = tab.viewports_by_id[initial_request.viewport_id]
    assert isinstance(axial, MprViewportController)
    tab.handleRenderResult(
        _mpr_result(axial, initial_frame, initial_request.request_id)
    )
    assert tab._initial_mpr_state is not None

    axial.mpr3DRotationRequested.emit((0.0, 0.0, 1.0), 0.2)
    axial.crosshairRotationRequested.emit(MprPlane.AXIAL, 0.1)
    assert tab._target_mpr_state is not None
    assert tab._target_mpr_state.frame != initial_frame

    tab.toolController.activateTool("mpr-rotate-3d")
    tab.toolController.resetActiveTool()

    assert tab._target_mpr_state is not None
    assert (
        tab._target_mpr_state.view_rolls.axial_radians
        == pytest.approx(-0.1)
    )
    assert tab._target_mpr_state.frame != initial_frame

    tab.toolController.activateTool("reset")

    assert tab._target_mpr_state == tab._initial_mpr_state


def test_mpr_failure_finishes_the_active_round() -> None:
    tab = TabController(
        TabConfig("mpr-tab", "MPR", TabType.MPR, (_series_meta(),))
    )
    requests = []
    tab.renderRequested.connect(requests.append)

    tab.init_render()
    request = requests[0]
    tab.handleRenderFailure(
        RenderFailure(
            request_id=request.request_id,
            viewport_id=request.viewport_id,
            error=RuntimeError("failed"),
        )
    )

    assert tab._active_mpr_requests == {}
