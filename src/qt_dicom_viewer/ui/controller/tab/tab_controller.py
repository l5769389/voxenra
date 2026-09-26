from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
import logging
import uuid
from math import isfinite
from types import MappingProxyType

from PySide6.QtCore import QObject, QTimer, Signal, Slot, Property

from qt_dicom_viewer.model import (
    MontageRenderResult,
    MprPlane,
    MprRenderRequest,
    RenderFailure,
    RenderRequest,
    RenderResult,
    TabConfig,
    TabType,
    ToolType,
    TwoDViewType,
    ViewportConfig,
)
from qt_dicom_viewer.core.mpr_rotation import (
    move_mpr_state_center,
    rotate_crosshair_state,
    rotate_mpr_state_3d,
)
from qt_dicom_viewer.model.dicom_core import (
    MprState,
    MprViewAnchors,
    Vector3,
)
from qt_dicom_viewer.model.render_models import MprRenderResult
from qt_dicom_viewer.model.interaction import WindowLevelChange
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.tab.tag_controller import TagController
from qt_dicom_viewer.ui.controller.viewport.image_2d.mpr_viewport_controller import (
    MprViewportController,
)
from qt_dicom_viewer.ui.controller.viewport.image_2d.stack_viewport_controller import (
    StackViewportController,
)
from qt_dicom_viewer.ui.controller.viewport.image_2d.montage_viewport_controller import (
    MontageViewportController,
)
from qt_dicom_viewer.ui.controller.viewport.viewport_controller import ViewportController
from qt_dicom_viewer.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
from qt_dicom_viewer.model.dicom_models import VolumeViewType
from qt_dicom_viewer.model.render_models import VolumeLoadResult

logger = logging.getLogger(__name__)
class TabController(QObject):
    _i18n_phaseItems = Signal()


    imageUpdateRequested = Signal(str, object)
    closeRequested = Signal()
    renderRequested = Signal(object)
    activeToolChanged = Signal(object)
    activeViewportChanged = Signal()
    phaseChanged = Signal()
    fpsChanged = Signal()
    playingChanged = Signal()
    playbackModeChanged = Signal()
    playbackAvailabilityChanged = Signal()
    imageRemovalRequested = Signal(str)
    stackNavigationRequested = Signal(str, int, float, float, bool)
    viewLayoutChanged = Signal()
    persistenceChanged = Signal()

    def __init__(self, tab_config: TabConfig, parent=None, *, tag_controller: TagController | None = None, enable_mpr_layout=True):
        super().__init__(parent)
        self._tab_config = tab_config
        self._focused_viewport_id = ""
        self._tag_controller = tag_controller
        if tag_controller is not None:
            tag_controller.setParent(self)
        self._viewport_dict: dict[str, ViewportController] = {}
        self._create_tool_controller()
        from .mpr_voi_controller import MprVoiController
        self._voi_controller = MprVoiController(self._tool_controller, self) if tab_config.tab_type in (TabType.MPR, TabType.FOUR_D, TabType.PETCT_FUSION) else None
        self._phase_identifiers: tuple[int, ...] = ()
        if tab_config.tab_type == TabType.FOUR_D:
            if (
                len(tab_config.series_metas) != 1
                or not tab_config.series_metas[0].supports_four_d
                or len(tab_config.series_metas[0].phase_identifiers) < 2
            ):
                raise ValueError(
                    "A 4D tab requires one supported temporal series"
                )
            self._phase_identifiers = (
                tab_config.series_metas[0].phase_identifiers
            )
        self._current_phase_index = 0
        if self._phase_identifiers:
            initial_phase_identifier = (
                tab_config.series_metas[0].initial_phase_identifier
            )
            if initial_phase_identifier in self._phase_identifiers:
                self._current_phase_index = self._phase_identifiers.index(
                    initial_phase_identifier
                )
        self._rendering_phase_index: int | None = None
        self._pending_phase_index: int | None = None
        self._fps = 2
        self._playing = False
        self._playback_mode = "phase" if tab_config.tab_type == TabType.FOUR_D else "slice"
        if tab_config.tab_type == TabType.FOUR_D:
            self._voi_controller.set_phase(self._current_phase_index)
        self._phase_timer = QTimer(self)
        self._phase_timer.setInterval(self._playback_interval_ms())
        self._phase_timer.timeout.connect(
            self._handle_playback_timeout
        )
        self._active_viewport_id: str = ''
        self._target_mpr_state: MprState | None = None
        self._initial_mpr_state: MprState | None = None
        # 不包含 3D 旋转增量的并行状态，用于只撤销 3D 旋转，
        # 同时保留之后发生的十字线移动和十字线旋转。
        self._mpr_3d_reset_state: MprState | None = None
        self._dirty_mpr_viewport_ids: set[str] = set()
        # request_id: viewport_id
        self._active_mpr_requests: dict[str, str] = {}
        self._mpr_request_phase_identifiers: dict[
            str, int | None
        ] = {}
        self._link_mpr_windows = tab_config.tab_type in (TabType.MPR, TabType.FOUR_D) and all(
            meta.modality.upper() in ("CT", "MR") for meta in tab_config.series_metas
        )
        self._linked_mpr_window: WindowLevelChange | None = None
        self._initial_mpr_window: WindowLevelChange | None = None
        self._mpr_window_revision = 0
        self._mpr_request_window_revisions: dict[str, int] = {}
        self.activeViewportChanged.connect(self.pausePlayback)
        self.activeViewportChanged.connect(self.playbackAvailabilityChanged.emit)
        self.renderRequested.connect(self._remember_measurement_request)
        self._measurement_results = None
        self._create_viewport_dict()
        from .mpr_layout_controller import MprLayoutController
        self._mpr_layout = MprLayoutController(self) if enable_mpr_layout and tab_config.tab_type in (TabType.MPR, TabType.FOUR_D) else None

    @Property(QObject, constant=True)
    def measurementResults(self):
        if self._measurement_results is None:
            from qt_dicom_viewer.ui.controller.measurement_results_controller import MeasurementResultsController
            self._measurement_results = MeasurementResultsController(self)
        return self._measurement_results

    def _remember_measurement_request(self, request):
        from qt_dicom_viewer.ui.measurement_source import capture_request
        view = self.viewports_by_id.get(request.viewport_id)
        if view is None:
            return
        requests = getattr(view, "_measurement_requests", {})
        if request.request_id in requests:
            return
        requests[request.request_id] = capture_request(request)
        if isinstance(request, MprRenderRequest):
            requests[request.request_id]["navigation"] = (getattr(view, "_independent_measurement_source", {}) or {}).get("navigation", self._target_mpr_state)
            view._latest_request_id = request.request_id
        while len(requests) > 16:
            requests.pop(next(iter(requests)))
        view._measurement_requests = requests

    def navigate_measurement(self, view, source):
        from qt_dicom_viewer.ui.measurement_source import restore_request, display_parameters
        request = restore_request(source, view.viewportId, display=display_parameters(view))
        self.pausePlayback()
        self.activateViewport(view.viewportId)
        view._measure_controller.cancel_transaction()
        if isinstance(request, MprRenderRequest) and not hasattr(view, "slice_frame"):
            # Route this one physical plane without broadcasting navigation to peers.
            for key, target in list(self._active_mpr_requests.items()):
                if target == view.viewportId:
                    self._active_mpr_requests.pop(key)
                    self._mpr_request_phase_identifiers.pop(key, None)
                    self._mpr_request_window_revisions.pop(key, None)
            navigation = source.get("navigation")
            if navigation is not None:
                view._mpr_state = navigation
            view._independent_measurement_source = dict(source)
            self._dirty_mpr_viewport_ids.discard(view.viewportId)
            self._active_mpr_requests[request.request_id] = view.viewportId
            self._mpr_request_phase_identifiers[request.request_id] = request.phase_identifier
            self._mpr_request_window_revisions[request.request_id] = self._mpr_window_revision
        view._latest_request_id = request.request_id
        view.render_pending = True
        self.renderRequested.emit(request)

    @Property(QObject, constant=True)
    def mprLayout(self):
        return self._mpr_layout

    @Property(str, notify=activeToolChanged)
    def activeTool(self):
        return self._tool_controller.activeTool

    @Property(QObject, constant=True)
    def voiController(self):
        return self._voi_controller

    @Property(QObject, constant=True)
    def historyController(self):
        return getattr(self, "_edit_history", None)

    @Property(str, notify=viewLayoutChanged)
    def focusedViewportId(self):
        return self._focused_viewport_id

    @Slot(str)
    def focusSingleViewport(self, viewport_id):
        layout = self.mprLayout
        reference = (layout is not None and layout.layout == "quad"
                     and viewport_id == layout.volumeViewport.viewportId)
        value = viewport_id if viewport_id in self._viewport_dict or reference else ""
        if value and layout is not None and (layout.active or reference):
            self.activateViewport(value)
        if value != self._focused_viewport_id:
            self._focused_viewport_id = value
            self.viewLayoutChanged.emit()


    @Property(QObject, notify=activeViewportChanged)
    def activeViewport(self):
        layout = getattr(self, "_mpr_layout", None)
        if layout is not None and layout.active:
            return layout.volumeViewport
        if self._active_viewport_id == '':
            return None
        return self._viewport_dict.get(self._active_viewport_id)

    @Property(QObject, notify=activeViewportChanged)
    def activeToolController(self):
        layout = getattr(self, "_mpr_layout", None)
        return layout.volumeTools if layout is not None and layout.active else self._tool_controller

    @Property(QObject,constant= True)
    def toolController(self) -> QObject:
        return self._tool_controller

    @Property(int, constant=True)
    def phaseCount(self) -> int:
        return len(self._phase_identifiers)

    @_TextProperty('QVariantList', notify=_i18n_phaseItems, notify_name='_i18n_phaseItems')
    def phaseItems(self) -> list[dict]:
        label_width = max(2, len(str(self.phaseCount)))
        return [
            {
                "index": index,
                "label": str(index + 1).zfill(label_width),
            }
            for index in range(self.phaseCount)
        ]

    @Property(int, notify=phaseChanged)
    def currentPhaseIndex(self) -> int:
        return self._current_phase_index

    @Property(int, notify=fpsChanged)
    def fps(self) -> int:
        return self._fps

    @Property(bool, notify=playingChanged)
    def playing(self) -> bool:
        return self._playing

    @Property(bool, constant=True)
    def temporalPlayback(self) -> bool:
        return self._tab_config.tab_type == TabType.FOUR_D

    @Property(str, notify=playbackModeChanged)
    def playbackMode(self): return self._playback_mode

    @Property(bool, notify=playbackAvailabilityChanged)
    def slicePlaybackAvailable(self):
        viewport = self.activeViewport
        return (self._tab_config.tab_type in (TabType.TWO_D, TabType.MPR, TabType.FOUR_D)
                and isinstance(viewport, (StackViewportController, MprViewportController))
                and viewport.loadState == "ready" and viewport.sliceCount > 1
                and (not self.temporalPlayback or (self._rendering_phase_index is None
                                                   and self._pending_phase_index is None)))

    @Property(bool, notify=playbackAvailabilityChanged)
    def phasePlaybackAvailable(self):
        layout = getattr(self, "_mpr_layout", None)
        return (self.temporalPlayback and self.phaseCount > 1 and self._target_mpr_state is not None
                and all(view.loadState == "ready" for view in self._viewport_dict.values())
                and not (layout is not None and layout.layout == "quad"
                         and layout.volumeViewport.loadState == "error"))

    @Property(bool, notify=playbackAvailabilityChanged)
    def playbackAvailable(self) -> bool:
        if self.temporalPlayback and self._playback_mode == "phase":
            return self.phasePlaybackAvailable
        return self.slicePlaybackAvailable

    def _connect_playback_viewport(self, viewport):
        if isinstance(viewport, (StackViewportController, MprViewportController)):
            viewport.sliceChanged.connect(self.playbackAvailabilityChanged.emit)
            viewport.loadStateChanged.connect(self._playback_load_changed)

    @Slot()
    def _playback_load_changed(self):
        if self._playing and not self.playbackAvailable:
            self.pausePlayback()
        self.playbackAvailabilityChanged.emit()

    @Slot(int)
    def setPhaseIndex(self, index: int) -> None:
        if not 0 <= index < self.phaseCount:
            return
        if self._playing and self._playback_mode == "slice":
            self.pausePlayback()
        if (
            self._active_mpr_requests
            or self._dirty_mpr_viewport_ids
            or self._rendering_phase_index is not None
            or self._target_mpr_state is None
        ):
            self._pending_phase_index = index
            self.playbackAvailabilityChanged.emit()
            return
        if index == self._current_phase_index and not any(
                getattr(v, "_independent_measurement_source", None) for v in self._viewport_dict.values()):
            return
        self._start_phase_render(index)

    @Slot(int)
    def setFps(self, fps: int) -> None:
        resolved_fps = max(1, min(15, int(fps)))
        if resolved_fps == self._fps:
            return
        self._fps = resolved_fps
        self._phase_timer.setInterval(self._playback_interval_ms())
        if self._playing:
            self._phase_timer.start()
        self.fpsChanged.emit()

    @Slot()
    def togglePlayback(self) -> None:
        self.setPlaying(not self._playing)

    @Slot(str)
    def togglePlaybackMode(self, mode):
        if mode not in ("slice", "phase") or (mode == "phase" and not self.temporalPlayback):
            return
        if self._playing:
            # Another mode cannot take over a running cine sequence. Stop first.
            if mode == self._playback_mode:
                self.pausePlayback()
            return
        self.pausePlayback()
        self._playback_mode = mode
        self.playbackModeChanged.emit()
        self.playbackAvailabilityChanged.emit()
        self.setPlaying(True)

    @Slot(bool)
    def setPlaying(self, playing: bool) -> None:
        resolved_playing = bool(playing) and self.playbackAvailable
        if resolved_playing == self._playing:
            return
        self._playing = resolved_playing
        if self._playing:
            tool = ToolType.SLICE_PLAY if self.temporalPlayback and self._playback_mode == "slice" else ToolType.PLAY
            self._tool_controller.activateTool(tool.value)
            self._tool_controller.lock_to_tool(tool)
            if self.temporalPlayback and self._mpr_layout is not None:
                tools = self._mpr_layout.volumeTools
                tools.activateTool(ToolType.PLAY.value)
                tools.lock_to_tool(ToolType.PLAY)
            self._phase_timer.start()
        else:
            # Drain submitted work, but never launch queued phase changes after Stop.
            self._pending_phase_index = None
            self._tool_controller.lock_to_tool(None)
            if self.temporalPlayback and self._mpr_layout is not None:
                self._mpr_layout.volumeTools.lock_to_tool(None)
            self._phase_timer.stop()
        self.playingChanged.emit()
        self.playbackAvailabilityChanged.emit()

    @Slot()
    def pausePlayback(self) -> None:
        self.setPlaying(False)

    def _playback_interval_ms(self) -> int:
        return max(1, round(1000 / self._fps))

    def _slice_playback_busy(self, viewport) -> bool:
        return bool(viewport.render_pending or self._active_mpr_requests or self._dirty_mpr_viewport_ids)

    def _handle_playback_timeout(self) -> None:
        if not self._playing:
            return
        if not self.temporalPlayback or self._playback_mode == "slice":
            if not self.playbackAvailable:
                self.pausePlayback()
                return
            viewport = self.activeViewport
            # Do not flood the render queue or advance beyond an unseen frame.
            if (self._slice_playback_busy(viewport) or self._rendering_phase_index is not None
                    or self._pending_phase_index is not None):
                return
            viewport.setSliceIndex((viewport.sliceIndex + 1) % viewport.sliceCount)
            return
        if not self.phasePlaybackAvailable:
            self.pausePlayback()
            return
        if (
            not self._playing
            or self.phaseCount < 2
            or (self._mpr_layout is not None and self._mpr_layout.awaiting_playback_frame)
            or self._active_mpr_requests
            or self._dirty_mpr_viewport_ids
            or self._rendering_phase_index is not None
            or self._pending_phase_index is not None
            or self._target_mpr_state is None
        ):
            return
        self._start_phase_render(
            (self._current_phase_index + 1) % self.phaseCount
        )

    def _start_phase_render(self, index: int) -> None:
        if self._target_mpr_state is not None:
            self._set_target_mpr_state(self._target_mpr_state)
        if self._voi_controller is not None:
            self._voi_controller.set_phase(index, ready=False)
        self._rendering_phase_index = index
        self.playbackAvailabilityChanged.emit()
        self._dirty_mpr_viewport_ids.update(
            self._mpr_viewport_ids()
        )
        self._try_start_next_mpr_render()

    def _phase_identifier_for_render(self) -> int | None:
        if not self._phase_identifiers:
            return None
        index = (
            self._rendering_phase_index
            if self._rendering_phase_index is not None
            else self._current_phase_index
        )
        return self._phase_identifiers[index]


    @Property(QObject, constant=True)
    def tagController(self) -> QObject | None:
        return self._tag_controller

    def _create_tool_controller(self) -> None:
        modality = (
            self._tab_config.series_metas[0].modality
            if self._tab_config.series_metas
            else ""
        )
        self._tool_controller = ToolController(
            tab_type=self._tab_config.tab_type,
            modality=modality,
            supports_ct_analysis=all(m.supports_ct_analysis for m in self._tab_config.series_metas),
            is_color=any(m.is_color for m in self._tab_config.series_metas),
            color_calibrated=all(not m.is_color or m.color_calibrated for m in self._tab_config.series_metas),
            parent=self
        )
        self._tool_controller.commandRequested.connect(
            self._handle_tool_command
        )
        self._tool_controller.resetRequested.connect(
            self._handle_tool_reset_requested
        )
        self._last_mpr_projection_settings = (
            self._tool_controller.mpr_projection_settings
        )
        self._tool_controller.mprProjectionChanged.connect(
            self._handle_mpr_projection_changed
        )

    @Slot(str)
    def _handle_tool_command(self, command: str) -> None:
        if command == "volume:toggle-bed":
            viewport = self.activeViewport
            if isinstance(viewport, VolumeViewportController):
                viewport.setBedRemovalEnabled(not viewport.bedRemovalEnabled)
            return
        if command != "viewport:reset":
            logger.warning("Unknown tool command: %s", command)
            return

        viewport = self.activeViewport
        if not isinstance(viewport, ViewportController):
            return

        if (
            isinstance(viewport, MprViewportController)
            and self._initial_mpr_state is not None
        ):
            if self._link_mpr_windows and self._initial_mpr_window is not None:
                self._set_mpr_window(self._initial_mpr_window, render=False)
            self._set_target_mpr_state(self._initial_mpr_state)
            self._mpr_3d_reset_state = self._initial_mpr_state
            self._dirty_mpr_viewport_ids.update(
                self._mpr_viewport_ids()
            )
            # 先恢复几何状态并标脏，再重置投影；投影变更信号只会
            # 启动一次使用最终状态的渲染轮次。
            self._tool_controller.resetMprProjection()
            viewport.reset_all_view_state(reset_slice=False)
            self._try_start_next_mpr_render()
            return

        if isinstance(viewport, (StackViewportController, VolumeViewportController, MontageViewportController)):
            viewport.reset_all_view_state()

    @Slot(str)
    def _handle_tool_reset_requested(self, tool_value: str) -> None:
        try:
            tool_type = ToolType(tool_value)
        except ValueError:
            logger.warning("Unknown reset tool: %s", tool_value)
            return

        if tool_type == ToolType.WINDOW and self._link_mpr_windows:
            if self._initial_mpr_window is not None:
                self._set_mpr_window(self._initial_mpr_window)
            return

        if tool_type == ToolType.MPR_ROTATE_3D:
            self._reset_mpr_3d_rotation()
            return

        if tool_type == ToolType.MIP:
            self._tool_controller.resetMprProjection()
            return

        viewport = self.activeViewport
        if isinstance(viewport, (MprViewportController, StackViewportController, VolumeViewportController, MontageViewportController)):
            viewport.reset_tool_state(tool_type)

    def _reset_mpr_3d_rotation(self) -> None:
        state = self._target_mpr_state
        reset_state = self._mpr_3d_reset_state
        if state is None or reset_state is None:
            return
        if reset_state == state:
            return

        self._set_target_mpr_state(reset_state)
        self._dirty_mpr_viewport_ids.update(
            self._mpr_viewport_ids()
        )
        self._try_start_next_mpr_render()

    @Slot()
    def _handle_mpr_projection_changed(self) -> None:
        previous = self._last_mpr_projection_settings
        current = self._tool_controller.mpr_projection_settings
        self._last_mpr_projection_settings = current

        affected_planes = {
            plane
            for plane in MprPlane
            if (
                previous.effective_projection_for_plane(plane)
                != current.effective_projection_for_plane(plane)
            )
        }
        if not affected_planes:
            return

        self._dirty_mpr_viewport_ids.update(
            viewport_id
            for viewport_id, viewport in self._viewport_dict.items()
            if (
                isinstance(viewport, MprViewportController)
                and viewport.viewport_config.viewport_type in affected_planes
            )
        )
        self._try_start_next_mpr_render()


    def _request_initial_mpr(self) -> None:
        for viewport in self._viewport_dict.values():
            if (
                isinstance(viewport, MprViewportController)
                and viewport.viewport_config.viewport_type == MprPlane.AXIAL
            ):
                request = viewport.build_mpr_render_request(
                    mpr_frame=None,
                    phase_identifier=self._phase_identifier_for_render(),
                    initial=True,
                )
                self._start_mpr_requests([request])
                return


    def init_render(self):
        if (
            self.tab_config.tab_type in (TabType.MPR, TabType.FOUR_D)
            and self._target_mpr_state is None
            and not self._active_mpr_requests
        ):
            self._request_initial_mpr()
        if self.tab_config.tab_type in (TabType.TWO_D, TabType.COMPARE_2D, TabType.THREE_D, TabType.MONTAGE):
            for viewport in self._viewport_dict.values():
                viewport.request_first_loader()


    def retry_initial_load(self):
        if self.tab_config.tab_type in (TabType.MPR, TabType.FOUR_D) and self._target_mpr_state is not None:
            self._dirty_mpr_viewport_ids.update(self._mpr_viewport_ids())
            self._try_start_next_mpr_render()
        else:
            self.init_render()


    # MappingProxyType 可以防止 Workspace 意外修改 Tab 内部字典：
    @property
    def viewports_by_id(self) -> MappingProxyType[str,ViewportController]:
        return MappingProxyType(
            self._viewport_dict
        )

    def _create_viewport_dict(self) -> None:
        match self._tab_config.tab_type:
            case TabType.THREE_D:
                for series_meta in self._tab_config.series_metas:
                    viewport_id = str(uuid.uuid4())
                    self._active_viewport_id = viewport_id
                    from qt_dicom_viewer.ui.controller.viewport.standalone_pet_volume_controller import StandalonePetVolumeController
                    controller_type = StandalonePetVolumeController if series_meta.modality.upper() == "PT" else VolumeViewportController
                    viewport = controller_type(
                        ViewportConfig(viewport_id, self._tab_config.tab_id,
                                       VolumeViewType.VOLUME, series_meta.series_uid, series_meta),
                        self._tool_controller, parent=self,
                    )
                    self.connect_signal(viewport)
                    self._viewport_dict[viewport_id] = viewport
            case TabType.TWO_D:
                for series_meta in self._tab_config.series_metas:
                    viewport_id = str(uuid.uuid4())
                    self._active_viewport_id = viewport_id
                    viewport = StackViewportController(
                        viewport_config=ViewportConfig(
                            viewport_id,
                            tab_id=self._tab_config.tab_id,
                            viewport_type=TwoDViewType.STACK,
                            series_uid=series_meta.series_uid,
                            series_meta=series_meta,
                        ),
                        tool_controller=self._tool_controller,
                        parent=self
                    )
                    self.connect_signal(viewport)
                    self._viewport_dict[viewport_id] = viewport
            case TabType.MONTAGE:
                for series_meta in self._tab_config.series_metas:
                    viewport_id = str(uuid.uuid4())
                    self._active_viewport_id = viewport_id
                    viewport = MontageViewportController(
                        viewport_config=ViewportConfig(
                            viewport_id,
                            tab_id=self._tab_config.tab_id,
                            viewport_type=TwoDViewType.MONTAGE,
                            series_uid=series_meta.series_uid,
                            series_meta=series_meta,
                        ),
                        tool_controller=self._tool_controller,
                        parent=self,
                    )
                    self.connect_signal(viewport)
                    self._viewport_dict[viewport_id] = viewport
            case TabType.MPR | TabType.FOUR_D:
                    for series_meta in self._tab_config.series_metas:
                        for view_type in [MprPlane.AXIAL, MprPlane.SAGITTAL, MprPlane.CORONAL]:
                            viewport_id = str(uuid.uuid4())
                            if view_type == MprPlane.AXIAL:
                                self._active_viewport_id = viewport_id
                            viewport = MprViewportController(
                                viewport_config=ViewportConfig(
                                    viewport_id,
                                    tab_id=self._tab_config.tab_id,
                                    viewport_type=view_type,
                                    series_uid=series_meta.series_uid,
                                    series_meta=series_meta,
                                ),
                                tool_controller=self._tool_controller,
                                parent=self
                            )
                            self.connect_signal(viewport)
                            self._viewport_dict[viewport_id] = viewport


    def connect_signal(self, viewport: ViewportController):
        self._connect_playback_viewport(viewport)
        viewport.imageUpdateRequested.connect(self.imageUpdateRequested.emit)
        if isinstance(viewport, MontageViewportController):
            viewport.renderRequested.connect(
                self._handle_render_requested
            )
            viewport.imageRemovalRequested.connect(
                self.imageRemovalRequested.emit
            )
            viewport.sliceOpenRequested.connect(
                self.stackNavigationRequested.emit
            )
            return
        if isinstance(viewport, MprViewportController):
            viewport.linked_window = self._link_mpr_windows
            viewport.linkedWindowChangeRequested.connect(self._set_mpr_window)
            viewport.crosshairCenterChangeRequested.connect(
                self._handle_crosshair_center_change_requested
            )
            viewport.renderInvalidated.connect(
                self._handle_mpr_viewport_invalidated
            )
            viewport.crosshairRotationRequested.connect(
                self._handle_crosshair_rotation_requested
            )
            viewport.mpr3DRotationRequested.connect(
                self._handle_mpr_3d_rotation_requested
            )
            return

        viewport.renderRequested.connect(
            self._handle_render_requested
        )

    @Slot(str)
    def _handle_mpr_viewport_invalidated(
            self,
            viewport_id: str,
    ) -> None:
        viewport = self._viewport_dict.get(viewport_id)
        if not isinstance(viewport, MprViewportController):
            return

        self._dirty_mpr_viewport_ids.add(viewport_id)
        self._try_start_next_mpr_render()

    @Slot(object)
    def _handle_crosshair_center_change_requested(
            self,
            center_patient: Vector3,
    ) -> None:
        state = self._target_mpr_state
        if state is None:
            return

        next_state = move_mpr_state_center(
            state,
            center_patient,
        )
        if next_state.frame == state.frame:
            return

        self._set_target_mpr_state(next_state)
        if self._mpr_3d_reset_state is not None:
            self._mpr_3d_reset_state = move_mpr_state_center(
                self._mpr_3d_reset_state,
                center_patient,
            )

        self._dirty_mpr_viewport_ids.update(
            self._mpr_viewport_ids()
        )

        self._try_start_next_mpr_render()

    @Slot(object, float)
    def _handle_crosshair_rotation_requested(
        self,
        source_plane: MprPlane,
        angle_radians: float,
    ) -> None:
        state = self._target_mpr_state
        if state is None:
            return
        next_state = rotate_crosshair_state(
            state,
            source_plane,
            angle_radians,
        )
        self._set_target_mpr_state(next_state)
        if self._mpr_3d_reset_state is not None:
            self._mpr_3d_reset_state = rotate_crosshair_state(
                self._mpr_3d_reset_state,
                source_plane,
                angle_radians,
            )

        # 源视图的 Frame 旋转与 view roll 正好抵消，像素无需重采样。
        self._dirty_mpr_viewport_ids.update(
            viewport_id
            for viewport_id, viewport in self._viewport_dict.items()
            if (
                isinstance(viewport, MprViewportController)
                and viewport.viewport_config.viewport_type != source_plane
            )
        )
        self._try_start_next_mpr_render()

    @Slot(object, float)
    def _handle_mpr_3d_rotation_requested(
        self,
        axis_patient: Vector3,
        angle_radians: float,
    ) -> None:
        state = self._target_mpr_state
        if state is None:
            return
        self._set_target_mpr_state(
            rotate_mpr_state_3d(
                state,
                axis_patient,
                angle_radians,
            )
        )
        self._dirty_mpr_viewport_ids.update(
            self._mpr_viewport_ids()
        )
        self._try_start_next_mpr_render()

    @Slot(object)
    def _handle_render_requested(
            self,
            request: RenderRequest,
    ) -> None:
        if request.viewport_id not in self._viewport_dict:
            logger.warning(
                "Reject request from unknown viewport: %s",
                request.viewport_id,
            )
            return

        self.renderRequested.emit(request)

    def _set_mpr_window(self, change: WindowLevelChange, *, render=True) -> None:
        if (not self._link_mpr_windows
                or not all(isfinite(v) for v in (change.window.center, change.window.width))
                or change.window.width < (0.001 if self.tab_config.series_metas[0].modality.upper() == "MR" else 1)):
            return
        if change == self._linked_mpr_window:
            return
        self._linked_mpr_window = change
        self._mpr_window_revision += 1
        for viewport in self._viewport_dict.values():
            if isinstance(viewport, MprViewportController):
                viewport.set_window_state(change)
        self._dirty_mpr_viewport_ids.update(self._mpr_viewport_ids())
        if render:
            self._try_start_next_mpr_render()

    def discard_stale_mpr_window_result(self, result: RenderResult) -> bool:
        """Drain obsolete requests before publishing their pixels or frame metadata."""
        if (not isinstance(result, MprRenderResult)
                or not self._link_mpr_windows
                or self._active_mpr_requests.get(result.response_id) != result.viewport_id
                or self._mpr_request_window_revisions.get(result.response_id) == self._mpr_window_revision):
            return False
        self._active_mpr_requests.pop(result.response_id)
        self._mpr_request_phase_identifiers.pop(result.response_id, None)
        self._mpr_request_window_revisions.pop(result.response_id, None)
        self._dirty_mpr_viewport_ids.add(result.viewport_id)
        self._continue_after_mpr_activity()
        return True

    def accepts_render_result(self, result: RenderResult) -> bool:
        if isinstance(result, VolumeLoadResult):
            viewport = self._viewport_dict.get(result.viewport_id)
            return isinstance(viewport, VolumeViewportController) and viewport.accepts_result(result)
        if isinstance(result, MontageRenderResult):
            viewport = self._viewport_dict.get(result.viewport_id)
            return (
                isinstance(viewport, MontageViewportController)
                and viewport.accepts_result(result)
            )
        if not isinstance(result, MprRenderResult):
            viewport = self._viewport_dict.get(result.viewport_id)
            if isinstance(viewport, StackViewportController):
                return viewport.accepts_result(result)
            return viewport is not None

        return (
            self._active_mpr_requests.get(result.response_id)
            == result.viewport_id
            and self._mpr_request_phase_identifiers.get(
                result.response_id
            )
            == result.phase_identifier
        )

    @Slot(object)
    def handleRenderResult(self, result: RenderResult) -> None:
        viewport = self._viewport_dict.get(result.viewport_id)
        if viewport is None:
            logger.warning(
                "Cannot route render result to unknown viewport: "
                "tab_id=%s viewport_id=%s",
                self._tab_config.tab_id,
                result.viewport_id,
            )
            return

        if isinstance(result, MprRenderResult):
            if self.discard_stale_mpr_window_result(result):
                return
            expected_viewport_id = self._active_mpr_requests.get(
                result.response_id
            )
            expected_phase_identifier = (
                self._mpr_request_phase_identifiers.get(
                    result.response_id
                )
            )
            if (
                expected_viewport_id != result.viewport_id
                or expected_phase_identifier != result.phase_identifier
            ):
                logger.debug(
                    "Discard stale MPR result: request_id=%s "
                    "viewport_id=%s",
                    result.response_id,
                    result.viewport_id,
                )
                return

            self._active_mpr_requests.pop(result.response_id)
            self._mpr_request_window_revisions.pop(result.response_id, None)
            self._mpr_request_phase_identifiers.pop(
                result.response_id,
                None,
            )
            needs_initial_mpr_frame = self._target_mpr_state is None

            viewport.handleRenderResult(result)
            if self._mpr_layout is not None:
                self._mpr_layout.accept_volume(result.volume)
            # Bootstrap MPR with the axial view, then render the other views
            # after the first result establishes the shared frame.
            if needs_initial_mpr_frame and result.mpr_frame is not None:
                if self._link_mpr_windows:
                    self._initial_mpr_window = WindowLevelChange(result.frame_meta.window, result.frame_meta.inverted)
                    self._set_mpr_window(self._initial_mpr_window, render=False)
                    self._dirty_mpr_viewport_ids.discard(result.viewport_id)
                    for peer in self._viewport_dict.values():
                        if isinstance(peer, MprViewportController):
                            peer._baseline_window = result.frame_meta.window
                initial_state = MprState(
                    frame=result.mpr_frame,
                    view_grids=result.mpr_view_grids,
                    view_anchors=(
                        MprViewAnchors.centered(
                            result.mpr_view_grids
                        )
                        if result.mpr_view_grids is not None
                        else None
                    ),
                )
                self._initial_mpr_state = initial_state
                self._mpr_3d_reset_state = initial_state
                self._set_target_mpr_state(initial_state)
                self._mark_other_mpr_viewports_dirty(result.viewport_id)

            self._continue_after_mpr_activity()
            return

        viewport.handleRenderResult(result)

    def _mark_other_mpr_viewports_dirty(
            self,
            excluded_viewport_id: str,
    ) -> None:
        self._dirty_mpr_viewport_ids.update(
            viewport_id
            for viewport_id in self._mpr_viewport_ids()
            if viewport_id != excluded_viewport_id
        )

    @Slot(object)
    def handleRenderFailure(self, failure: RenderFailure) -> None:
        viewport = self._viewport_dict.get(failure.viewport_id)
        if isinstance(viewport, (VolumeViewportController, MontageViewportController)):
            viewport.handleRenderFailure(failure)
            return
        if isinstance(viewport, StackViewportController):
            viewport.handleRenderFailure(failure)
            return
        expected_viewport_id = self._active_mpr_requests.get(
            failure.request_id
        )
        if (
            expected_viewport_id is None
            or expected_viewport_id != failure.viewport_id
        ):
            return

        self._active_mpr_requests.pop(failure.request_id)
        self._mpr_request_window_revisions.pop(failure.request_id, None)
        self._mpr_request_phase_identifiers.pop(
            failure.request_id,
            None,
        )
        self.pausePlayback()
        logger.error(
            "MPR render failed: request_id=%s viewport_id=%s: %s",
            failure.request_id,
            failure.viewport_id,
            failure.error,
        )
        if self._rendering_phase_index is not None:
            self.pausePlayback()
            self._rendering_phase_index = None
            self._pending_phase_index = None
            if self._voi_controller is not None:
                self._voi_controller.set_phase(self._current_phase_index, ready=False)
            if self._target_mpr_state is not None:
                self._dirty_mpr_viewport_ids.update(
                    self._mpr_viewport_ids()
                )
        self._continue_after_mpr_activity()


    def contains_viewport(self, viewport_id: str) -> bool:
        return viewport_id in self._viewport_dict

    def dispose(self) -> None:
        if self._mpr_layout is not None:
            self._mpr_layout.dispose()
        if getattr(self, "_edit_history", None) is not None:
            self._edit_history.dispose()
        self.pausePlayback()
        if self._voi_controller is not None:
            self._voi_controller.dispose()
        if self._tag_controller is not None:
            self._tag_controller.dispose()
        for viewport in self._viewport_dict.values():
            viewport.shutdown()
            if isinstance(viewport, (VolumeViewportController, MontageViewportController)):
                viewport.dispose()

    @property
    def tab_config(self) -> TabConfig:
        return self._tab_config


    @Slot(str)
    def activateViewport(self, activeViewportId: str) -> None:
        layout = getattr(self, "_mpr_layout", None)
        if layout is not None and activeViewportId == layout.volumeViewport.viewportId:
            layout.activate()
            return
        if activeViewportId not in self._viewport_dict:
            logger.warning(
                "Cannot activate unknown viewport: viewport_id=%s",
                activeViewportId,
            )
            return

        if layout is not None and layout.active:
            # Keep the last slice identity while 3D is active, then restore it.
            self._active_viewport_id = activeViewportId
            layout.deactivate()
            return
        if self._active_viewport_id == activeViewportId:
            return

        self._active_viewport_id = activeViewportId
        self.activeViewportChanged.emit()

    def navigate_stack(
        self,
        slice_index: int,
        window,
        inverted: bool,
    ) -> None:
        for viewport in self._viewport_dict.values():
            if isinstance(viewport, StackViewportController):
                viewport.navigate_to_slice(slice_index, window, inverted)
                return

    def _mpr_viewport_ids(self) -> list[str]:
        return [
            viewport_id
            for viewport_id, viewport in self._viewport_dict.items()
            if isinstance(viewport, MprViewportController)
        ]

    def _start_mpr_requests(
        self,
        requests: list[MprRenderRequest],
    ) -> None:
        if not requests:
            return
        if self._active_mpr_requests:
            raise RuntimeError(
                "Cannot start an MPR render while another round is active"
            )

        self._active_mpr_requests = {
            request.request_id: request.viewport_id
            for request in requests
        }
        self._mpr_request_phase_identifiers = {
            request.request_id: request.phase_identifier
            for request in requests
        }
        self._mpr_request_window_revisions = {
            request.request_id: self._mpr_window_revision for request in requests
        }
        for request in requests:
            self.renderRequested.emit(request)


    def _try_start_next_mpr_render(self) -> None:
        # Start a new round only when the previous round is complete,
        # at least one viewport is dirty, and a shared frame is available.
        if self._active_mpr_requests:
            return
        if not self._dirty_mpr_viewport_ids:
            return
        if self._target_mpr_state is None:
            return

        viewport_ids = set(self._dirty_mpr_viewport_ids)
        self._dirty_mpr_viewport_ids.clear()

        requests: list[MprRenderRequest] = []

        for viewport_id, viewport in self._viewport_dict.items():
            if viewport_id not in viewport_ids:
                continue
            if not isinstance(viewport, MprViewportController):
                continue

            source = getattr(viewport, "_independent_measurement_source", None)
            if source:
                from qt_dicom_viewer.ui.measurement_source import restore_request, display_parameters
                requests.append(restore_request(source, viewport_id, display=display_parameters(viewport)))
                continue

            requests.append(
                viewport.build_mpr_render_request(
                    mpr_state=self._target_mpr_state,
                    phase_identifier=self._phase_identifier_for_render(),
                    initial=False,
                )
            )

        self._start_mpr_requests(requests)

    def _continue_after_mpr_activity(self) -> None:
        if self._active_mpr_requests:
            return
        if self._dirty_mpr_viewport_ids:
            self._try_start_next_mpr_render()
            if self._active_mpr_requests:
                return

        if self._rendering_phase_index is not None:
            rendered_phase_index = self._rendering_phase_index
            self._rendering_phase_index = None
            if self._voi_controller is not None:
                self._voi_controller.set_phase(rendered_phase_index)
            if rendered_phase_index != self._current_phase_index:
                self._current_phase_index = rendered_phase_index
                self.phaseChanged.emit()

        if self.temporalPlayback and self._voi_controller is not None:
            self._voi_controller.set_phase(self._current_phase_index)
        pending_phase_index = self._pending_phase_index
        self._pending_phase_index = None
        if (
            pending_phase_index is not None
            and pending_phase_index != self._current_phase_index
            and self._target_mpr_state is not None
        ):
            self._start_phase_render(pending_phase_index)
        self.playbackAvailabilityChanged.emit()

    def _set_target_mpr_state(self, state: MprState) -> None:
        self._target_mpr_state = state
        if self._mpr_layout is not None:
            self._mpr_layout.sync_state()
        for viewport in self._viewport_dict.values():
            if isinstance(viewport, MprViewportController):
                viewport._independent_measurement_source = None
                viewport.apply_mpr_state(state)
