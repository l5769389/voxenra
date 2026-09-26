import logging
import uuid
from dataclasses import replace

from qt_dicom_viewer.model import (
    RenderRequest,
    RenderResult,
    StackRenderRequest,
    StackRenderResult,
    TwoDViewType,
    ViewportConfig,
    WindowLevel,
)
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.viewport.controller.mtf_controller import MtfController
from qt_dicom_viewer.ui.controller.viewport.controller.fwhm_controller import FwhmController
from qt_dicom_viewer.ui.controller.viewport.controller.water_qa_controller import WaterQaController
from .image_2d_viewport_controller import (
    Image2DViewportController,
)

logger = logging.getLogger(__name__)
class StackViewportController(Image2DViewportController):
    def __init__(
        self,
        viewport_config: ViewportConfig,
        tool_controller: ToolController,
        parent=None,
    ) -> None:
        if viewport_config.viewport_type != TwoDViewType.STACK:
            raise ValueError(
                "StackViewportController requires a stack viewport config"
            )
        super().__init__(viewport_config, tool_controller, parent)
        self._mtf_controller = MtfController(self)
        self._fwhm_controller = FwhmController(self)
        self._qa_controller = WaterQaController(viewport_config.series_meta.modality, self)
        owner = self.workspaceTab
        if owner is not None:
            for service in (self._mtf_controller, self._fwhm_controller, self._qa_controller):
                service.recordsChanged.connect(owner.persistenceChanged.emit)
        tool_controller.serviceSelected.connect(self._service_selected)
        tool_controller.activePanelChanged.connect(self._service_panel_changed)
        self.transformChanged.connect(self._mtf_controller.roiController.clearHover)
        self.transformChanged.connect(self._fwhm_controller.roiController.clearHover)

    def _service_selected(self, action):
        if action == "service:qa":
            self._qa_controller.activate()

    def _service_panel_changed(self):
        if self._tool_controller.activePanel == "service" and self._tool_controller.activeService == "service:qa":
            self._qa_controller.activate()

    def _initial_slice_index(self) -> int:
        meta = self.viewport_config.series_meta
        return max(0, meta.slice_count // 2) if meta.modality.upper() == "MR" else 0

    def apply_slice_index(self, index: int) -> None:
        if not self._prepare_slice_index_change(index):
            return
        self._state = replace(
            self._state,
            slice_index=index,
        )
        self.request_render()

    def navigate_to_slice(
        self,
        index: int,
        window: WindowLevel,
        inverted: bool,
    ) -> None:
        """Atomically select a stack slice and display window."""
        count = self.viewport_state.slice_count
        index = max(0, int(index))
        if count is not None and count > 0:
            index = min(index, count - 1)

        slice_changed = self._prepare_slice_index_change(index)
        normalized_window = WindowLevel(
            center=float(window.center),
            width=max(float(window.width), self.minimumWindowWidth),
        )
        window_changed = (
            normalized_window != self.viewport_state.window
            or bool(inverted) != self.viewport_state.inverted
        )
        if window_changed:
            self._state = replace(
                self._state,
                window=normalized_window,
                inverted=bool(inverted),
            )
            self.overlayChanged.emit()
        if slice_changed or window_changed:
            self.request_render()


    def _build_render_request(self, *, initial: bool) -> RenderRequest:
        state = self.viewport_state
        return StackRenderRequest(
            request_id=str(uuid.uuid4()),
            viewport_id=self.viewport_config.viewport_id,
            series_uid=self.viewport_config.series_uid,
            slice_index=(
                self._initial_slice_index()
                if initial or state.slice_index is None
                else state.slice_index
            ),
            window=(None if initial else self._pet_display.target.window
                    if self.isPetViewport and self._pet_display.target else state.window),
            inverted=False if initial else state.inverted,
            color_map=state.display_style.color_map,
            display_mapping=state.display_mapping,
            value_unit=self.pet_active_unit_id or None,
        )

    def _validate_render_result(self, result: RenderResult) -> None:
        if not isinstance(result, StackRenderResult):
            raise TypeError(
                "StackViewportController requires StackRenderResult"
            )
        if result.view_type != TwoDViewType.STACK:
            raise ValueError("Stack render result has an invalid view type")

    def _apply_specific_render_result(self, result: RenderResult) -> None:
        self._mtf_controller.set_frame(result.series_uid, result.frame_meta, result.modality_pixel)
        self._fwhm_controller.set_frame(result.series_uid, result.frame_meta, result.modality_pixel)
        self._qa_controller.set_frame(result.series_uid, result.frame_meta, result.modality_pixel)
