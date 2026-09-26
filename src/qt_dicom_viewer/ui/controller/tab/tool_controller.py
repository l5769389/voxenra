from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
import logging
from dataclasses import replace
from math import isfinite

from PySide6.QtCore import Slot, Property, Signal, QObject

from qt_dicom_viewer.model import (
    InteractionType,
    MprPlane,
    MprProjectionMode,
    MprProjectionSettings,
    TabType,
    ToolBehavior,
    ToolType,
)
from qt_dicom_viewer.model.tool_catalog import (
    MEASURE_ACTIONS,
    PLACEHOLDER_TOOLS,
    ROTATE_ACTIONS,
    SERVICE_ACTIONS,
    TOOL_CATALOG,
    TOOL_DEFINITIONS,
)
from qt_dicom_viewer.preset import CT_WINDOW_PRESETS
from qt_dicom_viewer.ui.controller.settings_controller import resolve_settings

logger = logging.getLogger(__name__)

MONTAGE_TOOL_TYPES = frozenset((
    ToolType.WINDOW,
    ToolType.PAN,
    ToolType.ZOOM,
    ToolType.ROTATE,
    ToolType.PSEUDOCOLOR,
    ToolType.EXPORT,
    ToolType.RESET,
))


# Filter one common order for every view; specialised actions follow navigation
# and everyday image tools. Export and reset form the stable final pair.
TOOL_ORDER = (
    "mpr-layout", "window", "ct-window", "pet-window", "scroll", "slice-play", "play", "pan", "zoom",
    "rotate", "volume-rotate", "measure", "annotate",
    "pseudocolor", "volume-preset", "volume-direction", "viewport-settings", "invert",
    "fusion-blend", "mip", "mpr-rotate-3d", "segmentation", "voi", "volume-crop", "volume-bed",
    "registration", "service", "import", "export", "reset",
)


class ToolController(QObject):
    _i18n_activeToolLabel = Signal()
    _i18n_measureActions = Signal()
    _i18n_resetLabel = Signal()
    _i18n_rotateActions = Signal()
    _i18n_serviceActions = Signal()
    _i18n_tools = Signal()
    _i18n_windowPresets = Signal()


    activeToolChanged = Signal()
    activePanelChanged = Signal()
    activeInteractionChanged = Signal()
    activeServiceChanged = Signal()
    serviceSelected = Signal(str)
    commandRequested = Signal(str)
    resetRequested = Signal(str)
    resetStateChanged = Signal()
    mprProjectionChanged = Signal()
    windowPresetsChanged = Signal()

    def __init__(
            self,
            parent=None,
            *,
            tab_type: TabType | None = None,
            modality: str = "",
            supports_ct_analysis: bool = True,
    ):
        super().__init__(parent)

        self._settings_controller = resolve_settings(parent)
        self._settings_controller.changed.connect(self._settings_changed)
        self._tab_type = tab_type
        self._modality = modality.strip().upper()
        self._supports_ct_analysis = supports_ct_analysis
        self._active_tool = ToolType.WINDOW
        self._active_panel: ToolType | None = ToolType.WINDOW
        self._active_interaction = InteractionType.WINDOW
        if tab_type == TabType.PETCT_FUSION:
            self._active_tool = self._active_panel = ToolType.CT_WINDOW
        self._active_service = ""
        self.restoring_selection = False
        self._mpr_projection_settings = MprProjectionSettings()
        self._locked_tool: ToolType | None = None
        if tab_type == TabType.THREE_D:
            self._active_tool = ToolType.VOLUME_ROTATE
            self._active_panel = None
            self._active_interaction = InteractionType.VOLUME_ROTATE
        self.activeToolChanged.connect(self.resetStateChanged.emit)
        self.activeServiceChanged.connect(self.resetStateChanged.emit)

    @Slot()
    def _settings_changed(self):
        # A QObject receiver disconnects when its tab is destroyed; a bound
        # SignalInstance.emit callable can outlive it in the shared settings.
        self.windowPresetsChanged.emit()

    @Property(str, notify=activeToolChanged)
    def activeTool(self) -> str:
        return self._active_tool

    @_TextProperty(str, notify=_i18n_activeToolLabel, notify_name='_i18n_activeToolLabel', source_notify='activeToolChanged')
    def activeToolLabel(self) -> str:
        if self._active_tool == ToolType.WINDOW:
            return _msg("mapping.title")
        if self._modality == "MR" and self._active_tool == ToolType.SEGMENTATION:
            return _msg("seg.manage")
        definition = TOOL_DEFINITIONS.get(self._active_tool)
        return "" if definition is None else definition.label

    @Property(str, notify=activeToolChanged)
    def activeToolIcon(self) -> str:
        definition = TOOL_DEFINITIONS.get(self._active_tool)
        return "" if definition is None else definition.icon_name

    @Property(str, notify=activePanelChanged)
    def activePanel(self) -> str:
        return self._active_panel.value if self._active_panel is not None else ""

    @Property(str, notify=activeInteractionChanged)
    def activeInteraction(self) -> str:
        return self._active_interaction.value

    @Property(str, notify=activeServiceChanged)
    def activeService(self) -> str:
        return self._active_service

    @Property(bool, notify=mprProjectionChanged)
    def mprProjectionEnabled(self) -> bool:
        return self._mpr_projection_settings.enabled

    @Property(str, notify=mprProjectionChanged)
    def mprProjectionMode(self) -> str:
        return self._mpr_projection_settings.mode.value

    @Property('QVariantMap', notify=mprProjectionChanged)
    def mprThicknesses(self) -> dict:
        settings = self._mpr_projection_settings
        return {
            MprPlane.AXIAL.value: settings.axial_thickness_mm,
            MprPlane.CORONAL.value: settings.coronal_thickness_mm,
            MprPlane.SAGITTAL.value: settings.sagittal_thickness_mm,
        }

    @property
    def mpr_projection_settings(self) -> MprProjectionSettings:
        return self._mpr_projection_settings

    @property
    def active_interaction(self) -> InteractionType:
        return self._active_interaction

    @_TextProperty(str, notify=_i18n_resetLabel, notify_name='_i18n_resetLabel', source_notify='resetStateChanged')
    def resetLabel(self) -> str:
        if (self._modality == "PETCT3D" or self._modality == "PT" and self._tab_type == TabType.THREE_D) and self._active_tool == ToolType.VOLUME_PRESET:
            return _msg('text.0572')
        if self._modality == "PT" and self._active_tool == ToolType.WINDOW:
            return _msg('text.0573')
        if self._active_tool == ToolType.SERVICE and self._active_service == "service:mtf":
            return _msg('text.0574')
        if self._active_tool == ToolType.SERVICE and self._active_service == "service:fwhm":
            return _msg("fwhm.reset")
        if self._active_tool == ToolType.SERVICE and self._active_service == "service:qa":
            return _msg('text.0575')
        definition = TOOL_DEFINITIONS.get(self._active_tool)
        if definition is None or definition.reset_label is None:
            return _msg('text.0576')
        return definition.reset_label

    @Property(bool, notify=resetStateChanged)
    def canResetActiveTool(self) -> bool:
        if self._active_tool == ToolType.SERVICE:
            return self._active_service in ("service:mtf", "service:fwhm", "service:qa")
        definition = TOOL_DEFINITIONS.get(self._active_tool)
        return (
            definition is not None
            and definition.reset_label is not None
        )

    @Slot(str)
    def activateTool(self, tool_value: str) -> None:
        try:
            tool_type = ToolType(tool_value)
        except ValueError:
            logger.warning("Unknown tool type: %s", tool_value)
            return

        if (
            self._locked_tool is not None
            and tool_type != self._locked_tool
        ):
            return

        definition = TOOL_DEFINITIONS.get(tool_type)
        if definition is None:
            logger.warning("Missing tool definition: %s", tool_type.value)
            return
        if not definition.enabled:
            return
        if not tool_available(tool_type, self._tab_type, self._modality, self._supports_ct_analysis):
            logger.warning(
                "Tool %s is not available for tab type %s",
                tool_type.value,
                self._tab_type.value if self._tab_type is not None else "any",
            )
            return

        match definition.behavior:
            case ToolBehavior.INTERACTION:
                self._set_active_tool(definition.tool_type)
                self._set_active_interaction(definition.default_interaction)
                self._set_active_panel(None)

            case ToolBehavior.INTERACTION_PANEL:
                self._set_active_tool(definition.tool_type)
                self._set_active_interaction(InteractionType.PAN if self._modality == "MR"
                    and tool_type == ToolType.SEGMENTATION else definition.default_interaction)
                self._set_active_panel(None if self._tab_type == TabType.THREE_D
                    and tool_type == ToolType.WINDOW and self._modality not in ("CT", "MR", "PETCT3D")
                    else definition.tool_type)

            case ToolBehavior.PANEL:
                self._set_active_tool(definition.tool_type)
                self._set_active_interaction(
                    InteractionType(self._active_service)
                    if tool_type == ToolType.SERVICE and self._active_service in ("service:mtf", "service:fwhm", "service:qa")
                    else definition.default_interaction)
                self._set_active_panel(definition.tool_type)

            case ToolBehavior.COMMAND | ToolBehavior.TOGGLE:
                if definition.command is not None:
                    self.commandRequested.emit(definition.command)

    @Slot(str)
    def activateDirectTool(self, value):
        if value not in ("window", "ct-window", "pet-window", "scroll", "pan", "zoom", "volume-rotate", "mpr-rotate-3d"):
            return
        self.activateTool(value)
        if self.activeTool == value:
            self._set_active_panel(None)

    @Slot(str)
    def selectInteraction(self, interaction_value: str) -> None:
        if self._locked_tool is not None:
            return
        try:
            interaction = InteractionType(interaction_value)
        except ValueError:
            logger.warning("Unknown interaction type: %s", interaction_value)
            return

        if (self._modality == "MR" or not self._supports_ct_analysis) and interaction.value in ("service:mtf", "service:fwhm", "service:qa", "mpr:segmentation", "mpr:voi"):
            return
        if self._modality == "PETCT3D" and interaction not in (
            InteractionType.PAN, InteractionType.ZOOM, InteractionType.VOLUME_ROTATE,
        ):
            return
        if self._tab_type == TabType.THREE_D and interaction not in (
            InteractionType.PAN, InteractionType.ZOOM, InteractionType.VOLUME_ROTATE, InteractionType.WINDOW,
            InteractionType.VOLUME_CROP,
        ):
            return
        if interaction in (InteractionType.SERVICE_MTF, InteractionType.SERVICE_FWHM, InteractionType.SERVICE_QA):
            self.selectService(interaction.value)
            return
        if (
            self._tab_type == TabType.MONTAGE
            and interaction not in {
                InteractionType.WINDOW,
                InteractionType.PAN,
                InteractionType.ZOOM,
            }
        ):
            logger.warning(
                "Interaction %s is not available for montage tabs",
                interaction.value,
            )
            return

        self._set_active_interaction(interaction)

    def lock_to_tool(self, tool: ToolType | None) -> None:
        self._locked_tool = tool

    def persistent_selection(self) -> dict:
        return dict(version=1, tool=str(self.activeTool), panel=self.activePanel,
                    interaction=self.activeInteraction, service=self.activeService)

    def restore_selection(self, state=None, legacy_tool=None) -> None:
        """Restore selection only: never dispatch commands or select a service.

        Notify observers after assigning the complete state. Activation observers
        must respect restoring_selection so restored QA/VOI tools stay idle.
        """
        state = state if isinstance(state, dict) and state.get("version") == 1 else {}
        value = state.get("tool", legacy_tool)
        available = {item["toolType"] for item in self.tools if item.get("available")}
        if not isinstance(value, str) or value not in available:
            return
        tool = ToolType(value)
        definition = TOOL_DEFINITIONS[tool]
        if definition.behavior in (ToolBehavior.COMMAND, ToolBehavior.TOGGLE):
            return
        if self._locked_tool is not None and tool != self._locked_tool:
            return
        service = state.get("service", "")
        if not isinstance(service, str) or "service" not in available or service not in {item.action for item in SERVICE_ACTIONS}:
            service = ""
        interaction = definition.default_interaction
        if tool == ToolType.MEASURE:
            allowed = {item.action for item in MEASURE_ACTIONS}
            if isinstance(state.get("interaction"), str) and state["interaction"] in allowed:
                interaction = InteractionType(state["interaction"])
        elif tool == ToolType.ANNOTATE:
            if state.get("interaction") in ("annotate:arrow", "annotate:text"):
                interaction = InteractionType(state["interaction"])
        elif tool == ToolType.SERVICE and service:
            interaction = InteractionType(service)
        elif tool == ToolType.SEGMENTATION and self._modality == "MR":
            interaction = InteractionType.PAN
        panel = tool if definition.behavior != ToolBehavior.INTERACTION else None
        if state.get("panel") == "" or (self._tab_type == TabType.THREE_D
                and tool == ToolType.WINDOW and self._modality not in ("CT", "MR", "PETCT3D")):
            panel = None
        fields = (("_active_tool", tool, self.activeToolChanged),
                  ("_active_panel", panel, self.activePanelChanged),
                  ("_active_interaction", interaction, self.activeInteractionChanged),
                  ("_active_service", service, self.activeServiceChanged))
        changed = [signal for name, value, signal in fields if getattr(self, name) != value]
        self.restoring_selection = True
        try:
            for name, value, _ in fields:
                setattr(self, name, value)
            for signal in changed:
                signal.emit()
        finally:
            self.restoring_selection = False

    @Slot(str)
    def selectService(self, action: str) -> None:
        """MTF 绘制矩形，QA 自动识别并支持拖动已有 ROI。"""
        if (self._modality == "MR" or not self._supports_ct_analysis):
            return
        if action not in {item.action for item in SERVICE_ACTIONS}:
            logger.warning("Unknown service entry: %s", action)
            return

        self.activateTool(ToolType.SERVICE.value)
        # 不能通过二级入口绕过一级工具的视图类型限制。
        if self._active_tool != ToolType.SERVICE:
            return
        if action != self._active_service:
            self._active_service = action
            self.activeServiceChanged.emit()
        self._set_active_interaction(InteractionType(action) if action in ("service:mtf", "service:fwhm", "service:qa")
                                     else InteractionType.NONE)
        self.serviceSelected.emit(action)

    @Slot(bool)
    def setMprProjectionEnabled(self, enabled: bool) -> None:
        if not self._supports_mpr_projection():
            return
        self._set_mpr_projection_settings(
            replace(self._mpr_projection_settings, enabled=bool(enabled))
        )

    @Slot(str)
    def setMprProjectionMode(self, mode_value: str) -> None:
        if not self._supports_mpr_projection():
            return
        try:
            mode = MprProjectionMode(mode_value)
        except ValueError:
            logger.warning("Unknown MPR projection mode: %s", mode_value)
            return
        self._set_mpr_projection_settings(
            replace(self._mpr_projection_settings, mode=mode)
        )

    @Slot(str, float)
    def setMprThickness(self, plane_value: str, thickness: float) -> None:
        if not self._supports_mpr_projection() or not isfinite(thickness):
            return
        try:
            plane = MprPlane(plane_value)
        except ValueError:
            logger.warning("Unknown MPR projection plane: %s", plane_value)
            return

        value = min(100, max(0, int(round(thickness))))
        field_name = f"{plane.value}_thickness_mm"
        self._set_mpr_projection_settings(
            replace(
                self._mpr_projection_settings,
                **{field_name: value},
            )
        )

    @Slot()
    def resetMprProjection(self) -> None:
        if not self._supports_mpr_projection():
            return
        self._set_mpr_projection_settings(MprProjectionSettings())

    @Slot()
    def resetActiveTool(self) -> None:
        if not self.canResetActiveTool:
            return
        self.resetRequested.emit(self._active_tool.value)

    def _set_active_tool(self, tool: ToolType | None) -> None:
        if tool is None or tool == self._active_tool:
            return

        self._active_tool = tool
        self.activeToolChanged.emit()

    def _set_active_panel(self, panel: ToolType | None) -> None:
        if panel == self._active_panel:
            return

        self._active_panel = panel
        self.activePanelChanged.emit()

    def _set_active_interaction(self, interaction: InteractionType) -> None:
        if interaction == self._active_interaction:
            return

        self._active_interaction = interaction
        self.activeInteractionChanged.emit()

    def _supports_mpr_projection(self) -> bool:
        return self._tab_type in (None, TabType.MPR, TabType.FOUR_D, TabType.COMPARE_MPR)

    def _set_mpr_projection_settings(
        self,
        settings: MprProjectionSettings,
    ) -> None:
        if settings == self._mpr_projection_settings:
            return
        self._mpr_projection_settings = settings
        self.mprProjectionChanged.emit()

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._settings_controller

    @_TextProperty(list, notify=_i18n_windowPresets, notify_name='_i18n_windowPresets', source_notify='windowPresetsChanged')
    def windowPresets(self) -> list[dict]:
        return [] if self._modality in ("PT", "MR") or not self._supports_ct_analysis else self._settings_controller.window_presets

    @_TextProperty(list, notify=_i18n_tools, notify_name='_i18n_tools')
    def tools(self) -> list[dict]:
        return build_tool_items(self._tab_type, self._modality, self._supports_ct_analysis)

    @_TextProperty(list, notify=_i18n_rotateActions, notify_name='_i18n_rotateActions')
    def rotateActions(self) -> list[dict]:
        return [
            {
                "action": item.action,
                "label": item.label,
                "iconName": item.icon_name,
            }
            for item in ROTATE_ACTIONS
        ]

    @_TextProperty(list, notify=_i18n_measureActions, notify_name='_i18n_measureActions')
    def measureActions(self) -> list[dict]:
        return [
            {
                "action": item.action,
                "label": item.label,
                "iconName": item.icon_name,
            }
            for item in MEASURE_ACTIONS
        ]

    @_TextProperty(list, notify=_i18n_serviceActions, notify_name='_i18n_serviceActions')
    def serviceActions(self) -> list[dict]:
        return [
            {
                "action": item.action,
                "label": item.label,
                "iconName": item.icon_name,
            }
            for item in SERVICE_ACTIONS
        ]


def build_window_presets(modality: str = "") -> list[dict]:
    presets = () if modality.upper() in ("PT", "MR") else CT_WINDOW_PRESETS
    return [
        {
            "presetId": preset.preset_id,
            "label": preset.label,
            "center": preset.center,
            "width": preset.width,
        }
        for preset in presets
    ]


def build_tool_items(
        tab_type: TabType | None = None,
        modality: str = "",
        supports_ct_analysis: bool = True,
) -> list[dict]:
    items = [
        {
            "toolType": definition.tool_type.value,
            "label": (
                _msg('mapping.title')
                if definition.tool_type == ToolType.WINDOW
                else _msg('text.0577') if modality == "PT" and tab_type == TabType.THREE_D and definition.tool_type == ToolType.VOLUME_PRESET
                else _msg('text.0578') if modality == "PETCT3D" and definition.tool_type == ToolType.VOLUME_PRESET
                else _msg("playback.fourD") if definition.tool_type == ToolType.PLAY and tab_type == TabType.FOUR_D
                else _msg("seg.manage") if modality.upper() == "MR" and definition.tool_type == ToolType.SEGMENTATION
                else definition.label
            ),
            "iconName": "cine-4d-play" if definition.tool_type == ToolType.PLAY and tab_type == TabType.FOUR_D else definition.icon_name,
            "behavior": definition.behavior.value,
            "available": definition.enabled,
            "enabled": definition.enabled,
        }
        for definition in TOOL_CATALOG
        if tool_available(definition.tool_type, tab_type, modality, supports_ct_analysis)
    ]
    priority = {tool: index for index, tool in enumerate(TOOL_ORDER)}
    items.sort(key=lambda item: priority[item["toolType"]])
    placeholders = [
        {"toolType": item.key, "label": item.label, "iconName": item.key,
         "behavior": "placeholder", "available": False}
        for item in PLACEHOLDER_TOOLS if tab_type in item.supported_tab_types and modality != "PETCT3D"
    ]
    # 重置始终位于最后；未实现入口不会改变工具控制器的状态或触发命令。
    reset_index = next((i for i, item in enumerate(items)
                        if item["toolType"] == "reset"), len(items))
    return items[:reset_index] + placeholders + items[reset_index:]


def tool_available(
    tool: ToolType,
    tab_type: TabType | None,
    modality: str = "",
    supports_ct_analysis: bool = True,
) -> bool:
    if tab_type in (TabType.COMPARE_MPR, TabType.COMPARE_2D) and tool == ToolType.PLAY:
        return False
    if tab_type == TabType.COMPARE_MPR:
        if tool in (ToolType.SEGMENTATION, ToolType.VOI):
            return False
        tab_type = TabType.MPR
    if tab_type == TabType.COMPARE_2D:
        if tool == ToolType.MPR_LAYOUT:
            return False
        tab_type = TabType.TWO_D

    if not supports_ct_analysis and tool in (ToolType.SERVICE, ToolType.SEGMENTATION, ToolType.VOI, ToolType.VOLUME_BED):
        return False
    if modality.upper() == "MR" and tool in (ToolType.SERVICE, ToolType.VOI, ToolType.VOLUME_BED):
        return False
    if modality == "PETCT3D":
        return tool in (ToolType.WINDOW, ToolType.PAN, ToolType.ZOOM, ToolType.VOLUME_ROTATE,
                        ToolType.VOLUME_DIRECTION, ToolType.VOLUME_PRESET, ToolType.RESET)
    if tab_type == TabType.PETCT_FUSION:
        return tool in (ToolType.REGISTRATION, ToolType.FUSION_BLEND, ToolType.CT_WINDOW, ToolType.PET_WINDOW, ToolType.SCROLL,
                        ToolType.PAN, ToolType.ZOOM, ToolType.MEASURE, ToolType.ROTATE,
                        ToolType.ANNOTATE, ToolType.PSEUDOCOLOR, ToolType.VIEWPORT_SETTINGS,
                        ToolType.EXPORT, ToolType.RESET)
    if modality.upper() == "PT" and tool in (ToolType.SERVICE, ToolType.MIP):
        return False
    if tab_type == TabType.MONTAGE:
        return tool in MONTAGE_TOOL_TYPES
    if tab_type == TabType.THREE_D and modality.upper() == "PT":
        return tool in (ToolType.PAN, ToolType.ZOOM, ToolType.VOLUME_ROTATE,
                       ToolType.VOLUME_DIRECTION, ToolType.VOLUME_PRESET,
                       ToolType.VOLUME_CROP, ToolType.EXPORT, ToolType.RESET)
    if tab_type == TabType.THREE_D:
        return tool in (ToolType.WINDOW, ToolType.PAN, ToolType.ZOOM, ToolType.VOLUME_ROTATE,
                        ToolType.VOLUME_DIRECTION, ToolType.VOLUME_PRESET, ToolType.VOLUME_BED,
                        ToolType.VOLUME_CROP, ToolType.EXPORT, ToolType.RESET)
    supported = TOOL_DEFINITIONS[tool].supported_tab_types
    return tab_type is None or supported is None or tab_type in supported
