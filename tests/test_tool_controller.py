import pytest

from qt_dicom_viewer.model import InteractionType, TabType
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController


def test_initial_tool_state_opens_window_panel() -> None:
    controller = ToolController()

    assert controller.activeTool == "window"
    assert controller.activeToolLabel == "显示映射"
    assert controller.activeToolIcon == "window"
    assert controller.activePanel == "window"
    assert controller.activeInteraction == "window"


def test_interaction_tool_closes_panel_and_selects_interaction() -> None:
    controller = ToolController()

    controller.activateTool("pan")

    assert controller.activeTool == "pan"
    assert controller.activeToolLabel == "平移"
    assert controller.activeToolIcon == "pan"
    assert controller.activePanel == ""
    assert controller.activeInteraction == "pan"


def test_rotation_tool_enables_drag_and_keeps_action_panel() -> None:
    controller = ToolController()

    controller.activateTool("rotate")

    assert controller.activeTool == "rotate"
    assert controller.activePanel == "rotate"
    assert controller.activeInteraction == "rotate"


def test_secondary_tool_can_select_concrete_interaction() -> None:
    controller = ToolController()
    controller.activateTool("measure")

    controller.selectInteraction("measure:length")

    assert controller.activeTool == "measure"
    assert controller.activePanel == "measure"
    assert controller.active_interaction is InteractionType.MEASURE_LENGTH


def test_command_preserves_current_tool_state() -> None:
    controller = ToolController()
    commands: list[str] = []
    controller.commandRequested.connect(commands.append)
    controller.activateTool("pan")

    controller.activateTool("reset")

    assert commands == ["viewport:reset"]
    assert controller.activeTool == "pan"
    assert controller.activePanel == ""
    assert controller.activeInteraction == "pan"


def test_active_tool_exposes_and_requests_its_scoped_reset() -> None:
    controller = ToolController()
    resets: list[str] = []
    controller.resetRequested.connect(resets.append)
    controller.activateTool("pan")

    assert controller.resetLabel == "重置平移"
    assert controller.canResetActiveTool is True

    controller.resetActiveTool()

    assert resets == ["pan"]


def test_annotation_tool_activates_arrow_and_exposes_scoped_reset() -> None:
    controller = ToolController()
    resets: list[str] = []
    controller.resetRequested.connect(resets.append)
    controller.activateTool("annotate")

    assert controller.resetLabel == "重置标注"
    assert controller.canResetActiveTool is True

    controller.resetActiveTool()

    assert resets == ["annotate"]
    assert controller.activeInteraction == "annotate:arrow"


def test_image_display_tools_are_panels_with_expected_interaction() -> None:
    controller = ToolController(tab_type=TabType.TWO_D)
    tools = {tool["toolType"]: tool for tool in controller.tools}

    assert {"annotate", "pseudocolor", "viewport-settings"} <= tools.keys()

    controller.activateTool("annotate")
    assert controller.activePanel == "annotate"
    assert controller.activeInteraction == "annotate:arrow"

    controller.activateTool("pseudocolor")
    assert controller.activePanel == "pseudocolor"
    assert controller.activeInteraction == ""

    controller.activateTool("viewport-settings")
    assert controller.activePanel == "viewport-settings"
    assert controller.activeInteraction == ""


@pytest.mark.parametrize("tab_type", [TabType.THREE_D, TabType.TAG])
def test_image_display_tools_are_hidden_outside_image_tabs(tab_type) -> None:
    controller = ToolController(tab_type=tab_type)
    tool_types = {tool["toolType"] for tool in controller.tools}
    assert not {"annotate", "pseudocolor", "viewport-settings"} & tool_types


def test_mpr_3d_rotation_is_a_primary_interaction_tool() -> None:
    controller = ToolController(tab_type=TabType.MPR)

    controller.activateTool("mpr-rotate-3d")

    assert controller.activeTool == "mpr-rotate-3d"
    assert controller.activePanel == ""
    assert controller.active_interaction is InteractionType.MPR_ROTATE_3D
    assert controller.activeInteraction == "mpr:rotate3d"
    assert any(
        tool["iconName"] == "rotate-3d"
        and tool["toolType"] == "mpr-rotate-3d"
        for tool in controller.tools
    )
    assert all(
        action["action"] != "mpr:rotate3d"
        for action in controller.rotateActions
    )


def test_mpr_3d_rotation_is_hidden_outside_mpr_tabs() -> None:
    controller = ToolController(tab_type=TabType.TWO_D)

    assert all(
        tool["toolType"] != "mpr-rotate-3d"
        for tool in controller.tools
    )

    controller.activateTool("mpr-rotate-3d")

    assert controller.activeTool == "window"
    assert controller.activeInteraction == "window"


def test_mip_tool_is_mpr_only_and_exposes_default_settings() -> None:
    mpr = ToolController(tab_type=TabType.MPR)
    stack = ToolController(tab_type=TabType.TWO_D)

    assert any(tool["toolType"] == "mip" for tool in mpr.tools)
    assert all(tool["toolType"] != "mip" for tool in stack.tools)
    assert mpr.mprProjectionEnabled is False
    assert mpr.mprProjectionMode == "mip"
    assert mpr.mprThicknesses == {
        "axial": 0,
        "coronal": 0,
        "sagittal": 0,
    }

    mpr.activateTool("mip")

    assert mpr.activeTool == "mip"
    assert mpr.activePanel == "mip"
    assert mpr.activeInteraction == ""


def test_mip_settings_update_clamp_and_reset() -> None:
    controller = ToolController(tab_type=TabType.MPR)
    changes = []
    controller.mprProjectionChanged.connect(
        lambda: changes.append(controller.mpr_projection_settings)
    )

    controller.setMprThickness("axial", 36.4)
    controller.setMprThickness("coronal", -5)
    controller.setMprThickness("sagittal", 200)
    controller.setMprProjectionMode("mean")
    controller.setMprProjectionEnabled(True)

    assert controller.mprThicknesses == {
        "axial": 36,
        "coronal": 0,
        "sagittal": 100,
    }
    assert controller.mprProjectionMode == "mean"
    assert controller.mprProjectionEnabled is True

    controller.resetMprProjection()

    assert controller.mprProjectionEnabled is False
    assert controller.mprProjectionMode == "mip"
    assert controller.mprThicknesses == {
        "axial": 0,
        "coronal": 0,
        "sagittal": 0,
    }
    assert len(changes) == 5


def test_non_mpr_controller_rejects_mip_settings() -> None:
    controller = ToolController(tab_type=TabType.TWO_D)

    controller.activateTool("mip")
    controller.setMprThickness("axial", 20)
    controller.setMprProjectionMode("sum")
    controller.setMprProjectionEnabled(True)

    assert controller.activeTool == "window"
    assert controller.mpr_projection_settings.enabled is False
    assert controller.mprThicknesses["axial"] == 0


def test_play_panel_is_available_for_slices_and_temporal_tabs() -> None:
    four_d_controller = ToolController(tab_type=TabType.FOUR_D)

    assert any(
        tool["toolType"] == "play" and tool["iconName"] == "cine-4d-play"
        for tool in four_d_controller.tools
    )
    four_d_controller.activateTool("play")
    assert four_d_controller.activeTool == "play"
    assert four_d_controller.activePanel == "play"
    assert four_d_controller.activeInteraction == ""

    for tab_type in (TabType.TWO_D, TabType.MPR):
        controller = ToolController(tab_type=tab_type)
        assert any(t["toolType"] == "play" and t["iconName"] == "cine-play" for t in controller.tools)
        controller.activateTool("play")
        assert controller.activePanel == "play"

    for tab_type in (TabType.THREE_D, TabType.TAG):
        controller = ToolController(tab_type=tab_type)
        initial_tool = controller.activeTool
        initial_panel = controller.activePanel
        assert all(tool["toolType"] != "play" for tool in controller.tools)
        controller.activateTool("play")
        assert controller.activeTool == initial_tool
        assert controller.activePanel == initial_panel


def test_services_are_available_as_a_primary_panel_only_tool_in_2d() -> None:
    controller = ToolController(tab_type=TabType.TWO_D)
    assert any(tool["toolType"] == "service" and tool["iconName"] == "service"
               for tool in controller.tools)
    assert controller.serviceActions == [
        {"action": "service:mtf", "label": "MTF", "iconName": "mtf"},
        {"action": "service:fwhm", "label": "FWHM", "iconName": "fwhm"},
        {"action": "service:qa", "label": "QA", "iconName": "qa"},
    ]

    controller.activateTool("service")

    assert controller.activeToolLabel == "分析"
    assert controller.activeToolIcon == "service"
    assert controller.activePanel == "service"
    assert controller.activeInteraction == ""
    assert controller.activeService == ""
    assert not controller.canResetActiveTool


def test_pet_2d_hides_ct_services_and_uses_intensity_tool() -> None:
    controller = ToolController(tab_type=TabType.TWO_D, modality="PT")

    assert all(tool["toolType"] != "service" for tool in controller.tools)
    assert controller.windowPresets == []
    assert controller.activeToolLabel == "显示映射"
    assert next(
        tool for tool in controller.tools if tool["toolType"] == "window"
    )["label"] == "显示映射"

    controller.activateTool("service")
    assert controller.activeTool == "window"

    controller_without_tab_type = ToolController(modality="PT")
    controller_without_tab_type.activateTool("service")
    assert controller_without_tab_type.activeTool == "window"


@pytest.mark.parametrize("action", ["service:mtf", "service:fwhm", "service:qa"])
def test_service_selection_restores_corresponding_interaction_without_commands(action) -> None:
    controller = ToolController(tab_type=TabType.TWO_D)
    commands, resets, selections = [], [], []
    controller.commandRequested.connect(commands.append)
    controller.resetRequested.connect(resets.append)
    controller.activeServiceChanged.connect(lambda: selections.append(controller.activeService))
    controller.activateTool("measure")
    controller.selectInteraction("measure:rect")

    controller.selectService(action)
    controller.selectService(action)
    controller.resetActiveTool()

    assert controller.activeTool == controller.activePanel == "service"
    assert controller.activeService == action
    expected = InteractionType(action)
    assert controller.active_interaction is expected
    assert selections == [action]
    assert commands == []
    assert resets == ["service"]

    # 离开后重新打开面板保留入口选择，但不改变其他工具的行为。
    controller.activateTool("pan")
    assert controller.activeInteraction == "pan"
    controller.activateTool("service")
    assert controller.activeService == action
    assert controller.activeInteraction == expected.value


def test_unknown_service_entry_is_ignored() -> None:
    controller = ToolController()
    controller.selectService("measure:rect")
    assert controller.activeTool == "window"
    assert controller.activeInteraction == "window"
    assert controller.activeService == ""


def test_global_reset_remains_available_from_services() -> None:
    controller = ToolController(tab_type=TabType.TWO_D)
    commands = []
    controller.commandRequested.connect(commands.append)
    controller.selectService("service:mtf")
    controller.activateTool("reset")
    assert commands == ["viewport:reset"]
    assert controller.activePanel == "service"
    assert controller.activeService == "service:mtf"
    assert controller.activeInteraction == "service:mtf"


@pytest.mark.parametrize("tab_type", [TabType.MPR, TabType.THREE_D, TabType.FOUR_D, TabType.TAG])
def test_services_are_hidden_and_cannot_be_selected_outside_2d(tab_type) -> None:
    controller = ToolController(tab_type=tab_type)
    initial = (controller.activeTool, controller.activePanel, controller.activeInteraction)
    assert all(tool["toolType"] != "service" for tool in controller.tools)
    events = []
    controller.activeToolChanged.connect(lambda: events.append("tool"))
    controller.activePanelChanged.connect(lambda: events.append("panel"))
    controller.activeServiceChanged.connect(lambda: events.append("service"))
    controller.activeInteractionChanged.connect(lambda: events.append("interaction"))
    controller.commandRequested.connect(events.append)
    controller.resetRequested.connect(events.append)

    controller.activateTool("service")
    controller.selectService("service:mtf")
    controller.selectService("service:qa")

    assert (controller.activeTool, controller.activePanel, controller.activeInteraction) == initial
    assert controller.activeService == ""
    assert events == []
