from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
import logging
from dataclasses import replace
from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject, Slot, Property, Signal

from qt_dicom_viewer.model import (
    RenderFailure,
    RenderRequest,
    RenderResult,
    TabConfig,
    TabType,
    WindowLevel,
)
from qt_dicom_viewer.ui.controller.tab.tab_controller import TabController
from qt_dicom_viewer.ui.controller.tab.tag_controller import TagController
from qt_dicom_viewer.service.tag_read_service import TagReadService
from qt_dicom_viewer.ui.controller.viewport.viewport_controller import ViewportController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.model.render_models import VolumeLoadResult
from qt_dicom_viewer.model.render_models import PetBatchRenderResult
from qt_dicom_viewer.ui.controller.tab.pet_workspace_controller import PetWorkspaceController

from qt_dicom_viewer.ui.controller.tab_loading_controller import TabLoadingController
from qt_dicom_viewer.ui.controller.utility_tab_controller import UtilityTabController
from qt_dicom_viewer.ui.controller.manual_tab_controller import ManualTabController

from qt_dicom_viewer.core.workspace_state import dumps
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot
from qt_dicom_viewer.i18n.messages import error_message

logger = logging.getLogger(__name__)

class WorkspaceController(QObject):
    _i18n_loadingStates = Signal()
    _i18n_tabs = Signal()


    tabsChanged = Signal()
    tabPresentationChanged = Signal()
    activeTabChanged = Signal()
    activeViewportChanged = Signal()
    loadingStatesChanged = Signal()
    showDocumentRequested = Signal()

    rendered = Signal()
    renderRequested = Signal(object)
    renderCancelled = Signal(object)

    def __init__(self,
                 series_catalog: SeriesCatalog,
                 image_provider:DicomImageProvider,
                 parent = None):
        super().__init__(parent)
        self._series_catalog = series_catalog
        self._tab_dict:dict[str, TabController | UtilityTabController] = {}
        self._active_tab_id: str | None = None
        self._tab_mru: list[str] = []
        self._load_states: dict[str, TabLoadingController] = {}
        self._image_provider = image_provider
        self._tag_read_service = TagReadService(self)
        self._window_manager = None
        self._closed_tab_snapshots = {}
        self._identity_views = WeakKeyDictionary()
        self.tabPresentationChanged.connect(self._i18n_tabs.emit)
        settings = getattr(parent, "_settings_controller", None)
        if settings is not None:
            settings.sectionChanged.connect(self._identity_preferences_changed)

    @Slot()
    def openSettings(self):
        self._open_utility(TabType.SETTINGS, _msg('text.0493'))

    @Slot()
    def openDataSources(self):
        settings = getattr(self.parent(), "_settings_controller", None)
        if settings is not None:
            settings.selectCategory("sources")
        self.openSettings()

    @Slot()
    def openPacs(self):
        self._open_utility(TabType.PACS, _msg('text.0494'))

    @Property(QObject, notify=tabsChanged)
    def manualController(self):
        return self._tab_dict.get("workspace-manual")

    @Slot()
    @Slot(str)
    def openManual(self, chapter_id=""):
        tab_id = "workspace-manual"
        if tab_id not in self._tab_dict:
            self._tab_dict[tab_id] = ManualTabController(
                self, settings=getattr(self.parent(), "_settings_controller", None))
            self.tabsChanged.emit()
        if chapter_id:
            self._tab_dict[tab_id].setSearch("")
            self._tab_dict[tab_id].selectChapter(chapter_id)
        self.activateTabId(tab_id)

    def _open_utility(self, tab_type, label):
        tab_id = f"workspace-{tab_type.value}"
        if tab_id not in self._tab_dict:
            self._tab_dict[tab_id] = UtilityTabController(tab_type, label, self)
            self.tabsChanged.emit()
        self.activateTabId(tab_id)

    @Slot(str, result=bool)
    def closeTab(self, tab_id: str):
        return self.close_tabs([tab_id])

    def close_tabs(self, tab_ids):
        """Retain committed results before releasing any of the requested views."""
        document = getattr(self.parent(), "workspaceDocumentController", None)
        if document is not None and document.busy:
            return False
        tab_ids = list(dict.fromkeys(key for key in tab_ids if key in self._tab_dict))
        snapshots = {}
        try:
            for key in tab_ids:
                tab = self._tab_dict[key]
                if any(getattr(v, "editBusy", False) for v in tab.viewports_by_id.values()):
                    raise ValueError(_msg('text.0410'))
                if self._has_editing_work(tab):
                    snapshots[key] = dumps(tab_snapshot(tab))
        except Exception as error:
            if document is not None:
                document._message, document._error = error_message(error), True
                document.changed.emit()
            return False
        self._closed_tab_snapshots.update(snapshots)
        for key in tab_ids:
            self._close_tab(key)
        return True

    def _reopen_retained(self, tab_id):
        document = getattr(self.parent(), "workspaceDocumentController", None)
        if tab_id not in self._closed_tab_snapshots or document is None or document.restoring:
            return False
        document.reopen_closed(tab_id)
        return True

    @staticmethod
    def _has_editing_work(tab):
        from qt_dicom_viewer.ui.workspace_snapshot import editable_state
        if tab.tab_config.tab_type in (TabType.SETTINGS, TabType.PACS, TabType.MANUAL, TabType.TAG):
            return False
        # Restoring or saving resets history, so committed content is the primary
        # check. History also identifies tabs whose last result was deleted.
        history = getattr(tab, "_edit_history", None)
        if history is not None and (history.canUndo or history.canRedo):
            return True
        if any(WorkspaceController._has_editing_work(group) for group in getattr(tab, "groups", ())):
            return True
        # Analysis results and their committed ROIs are persisted separately
        # from edit history; default settings alone are not editing work.
        for view in tab.viewports_by_id.values():
            for name in ("_mtf_controller", "_fwhm_controller", "_qa_controller"):
                analysis = getattr(view, name, None)
                if analysis is not None:
                    saved = analysis.persistent_state()
                    if saved.get("records") or saved.get("roi", {}).get("measurements"):
                        return True
        state = editable_state(tab)
        if state.get("voi") or getattr(tab, "_registration_changed", False):
            return True
        return any(view.get("measurements") or view.get("annotations")
                   or view.get("crop") is not None or view.get("bed") is not None
                   for view in state["views"].values())

    def _close_tab(self, tab_id: str):
        """Dispose an approved close, or internal restore cleanup, without prompting."""
        if tab_id not in self._tab_dict:
            return
        tab = self._tab_dict.pop(tab_id)
        loading = self._load_states.pop(tab_id, None)
        self._cancel_tab_render(tab, loading)
        if loading is not None:
            loading.close()
        self.loadingStatesChanged.emit()
        self._tab_mru = [key for key in self._tab_mru if key != tab_id]
        if tab_id == self._active_tab_id:
            self._active_tab_id = self._tab_mru[0] if self._tab_mru else ""
            self.activeTabChanged.emit()
            self.activeViewportChanged.emit()
        self.tabsChanged.emit()
        # Unbind QML pages and tools before disposing their native/Python owners.
        tab.dispose()
        tab.deleteLater()

    def _cancel_tab_render(self, tab, loading=None):
        keys = {tab.tab_config.tab_id, *getattr(tab, "viewports_by_id", {})}
        if loading is not None:
            keys.update(loading._pending)
        self.renderCancelled.emit(tuple(keys))

    @Slot(str)
    def submit(self, render_request: RenderRequest):
        pass

    @Property('QVariantList', notify=activeTabChanged)
    def currentTabAllViewports(self) -> list[QObject]:
        if self._active_tab_id is None:
            return []

        tab = self._tab_dict.get(
            self._active_tab_id
        )

        if tab is None:
            return []

        return list(
            tab.viewports_by_id.values()
        )


    @Property(
        QObject,
        notify=activeViewportChanged,
    )
    def activeViewport(self) -> QObject | None:
        if self._active_tab_id is None:
            return None

        tab = self._tab_dict.get(
            self._active_tab_id
        )

        if tab is None:
            return None

        return tab.activeViewport


    @Slot(str)
    def activateTabId(self, tab_id: str):
        if self._window_manager is not None:
            self._window_manager.activate_tab(tab_id)
            return
        self._activate_tab(tab_id)

    def _activate_tab(self, tab_id, *, pause_previous=True):
        if tab_id and tab_id not in self._tab_dict:
            return

        if tab_id == self._active_tab_id:
            return

        current_tab = self._tab_dict.get(self._active_tab_id)
        if current_tab is not None and pause_previous:
            current_tab.pausePlayback()
        self._active_tab_id = tab_id
        self._tab_mru = ([tab_id] if tab_id else []) + [key for key in self._tab_mru if key and key != tab_id]
        self.activeTabChanged.emit()
        self.activeViewportChanged.emit()


    @_TextProperty('QVariantList', notify=_i18n_tabs, notify_name='_i18n_tabs', source_notify='tabsChanged')
    def tabs(self):
        sources = list(self._series_catalog.snapshot().values())
        sources.extend(meta for tab in self._tab_dict.values() for meta in tab.tab_config.series_metas)
        return [self.tab_presentation(tab, sources=sources) for tab in self._tab_dict.values()]

    def tab_presentation(self, tab, *, sources=None):
        from qt_dicom_viewer.ui.reading_identity import tab_presentation, tab_hides_identity
        if sources is None:
            sources = list(self._series_catalog.snapshot().values())
            sources.extend(meta for current in self._tab_dict.values() for meta in current.tab_config.series_metas)
        settings = getattr(self.parent(), "_settings_controller", None)
        hidden = tab_hides_identity(tab, default=bool(settings and settings.section("privacy")["hideIdentity"]))
        return tab_presentation(tab, sources=sources, hide_identity=hidden)

    @Slot(str)
    def _identity_preferences_changed(self, section):
        if section == "privacy":
            self.tabPresentationChanged.emit()

    @Slot()
    def _refresh_identity(self):
        # New 2D cells can introduce sources and per-cell privacy after opening.
        self._watch_identity_views()
        self.tabPresentationChanged.emit()

    def _watch_identity_views(self, tab=None):
        tabs = (tab,) if tab is not None else self._tab_dict.values()
        for current in tabs:
            for view in current.viewports_by_id.values():
                if view in self._identity_views:
                    continue
                signal = getattr(view, "viewportSettingsChanged", None)
                if signal is not None:
                    signal.connect(self._viewport_identity_changed)
                    self._identity_views[view] = view.hideSensitiveInfo

    @Slot()
    def _viewport_identity_changed(self):
        view = self.sender()
        if view is not None and self._identity_views.get(view) != view.hideSensitiveInfo:
            self._identity_views[view] = view.hideSensitiveInfo
            self.tabPresentationChanged.emit()


    @Property(str, notify=activeTabChanged)
    def activeTabId(self) -> str | None:
        return self._active_tab_id

    @Property(QObject,notify=activeTabChanged)
    def activeTab(self) -> TabController | UtilityTabController | None:
        return self._tab_dict.get(self._active_tab_id, None)

    @Property(QObject, notify=activeTabChanged)
    def activeLoadState(self):
        return self._load_states.get(self._active_tab_id)

    @_TextProperty('QVariantMap', notify=_i18n_loadingStates, notify_name='_i18n_loadingStates', source_notify='loadingStatesChanged')
    def loadingStates(self):
        return {key: state.status for key, state in self._load_states.items()}

    @Slot()
    def retryActiveTab(self):
        tab = self.activeTab
        state = self.activeLoadState
        if tab is None or state is None or state.status != "error":
            return
        state.restart()
        if tab.tagController is not None:
            tab.tagController.retry()
        else:
            tab.retry_initial_load()

    @Property(str, notify=activeTabChanged)
    def activeTabType(self) -> str:
        tab = self._tab_dict.get(self._active_tab_id)

        if tab is None:
            return ""

        return tab.tab_config.tab_type.value


    @Slot(str, str, str)
    def createTab(self,series_uid: str,
                        tab_label: str,
                        tab_type: TabType,
                        *, phase_identifiers=None,
                   ):
        try:
            tab_type = TabType(tab_type)
        except ValueError:
            logger.warning("Unsupported tab type: %s", tab_type)
            return
        if tab_type in (TabType.SETTINGS, TabType.PACS, TabType.MANUAL, TabType.COMPARE_2D, TabType.COMPARE_MPR):
            return
        if self._reopen_retained(f'{series_uid}_{tab_type}'):
            return
        tab, created = self._create_or_activate_tab(
            series_uid,
            tab_label,
            tab_type,
            phase_identifiers=phase_identifiers,
        )
        if created and tab is not None:
            if tab.tagController is not None:
                tab.tagController.start()
            else:
                tab.init_render()

    def _create_or_activate_tab(
        self,
        series_uid: str,
        tab_label: str,
        tab_type: TabType,
        *, phase_identifiers=None,
    ) -> tuple[TabController | None, bool]:
        tab_id = f'{series_uid}_{tab_type}'
        if tab_id == self._active_tab_id:
            self.activateTabId(tab_id)
            return self._tab_dict.get(tab_id), False
        new_tab = None
        if tab_id not in self._tab_dict:
            series = self._series_catalog.get_series(series_uid)
            if series is None:
                logger.warning(
                    "Cannot create tab for unknown series: series_uid=%s",
                    series_uid,
                )
                return None, False
            if tab_type == TabType.FOUR_D and not series.supports_four_d:
                logger.warning(
                    "Cannot create 4D tab for unsupported series: "
                    "series_uid=%s",
                    series_uid,
                )
                return None, False
            # MR/CT pixel and geometry validation belongs to loading. Even an
            # unsupported source needs a tab in which to show its failure reason.
            series_display_meta = self._series_catalog.get_series_display_meta(series_uid)
            if series_display_meta is None:
                logger.warning(
                    "Cannot create tab for unknown series: series_uid=%s",
                    series_uid,
                )
                return None, False

            if phase_identifiers is not None:
                identifiers = tuple(phase_identifiers)
                if (tab_type != TabType.FOUR_D or len(identifiers) < 2
                        or any(type(value) is not int for value in identifiers)
                        or len(set(identifiers)) != len(identifiers)
                        or not set(identifiers) <= set(series_display_meta.phase_identifiers)):
                    raise ValueError(_msg('results.changedSource'))
                series_display_meta = replace(series_display_meta, phase_identifiers=identifiers)

            tab_config = TabConfig(
                tab_id = tab_id,
                tab_label = tab_label,
                tab_type = tab_type,
                series_metas=(series_display_meta,),
            )

            tag_controller = None
            if tab_type == TabType.TAG:
                tag_controller = TagController(
                    tab_id, self._series_catalog.get_series(series_uid),
                    self._tag_read_service,
                )
            if tab_type == TabType.MPR and series_display_meta.modality.upper() == "PT":
                new_tab = PetWorkspaceController(tab_config,
                    pet_series=self._series_catalog.get_series(series_uid), parent=self)
            elif tab_type == TabType.TWO_D:
                from .tab.two_d_tab_controller import TwoDTabController
                new_tab = TwoDTabController(tab_config, parent=self)
            else:
                new_tab = TabController(tab_config, parent=self, tag_controller=tag_controller)
            self.connect_signal(new_tab)
            self._tab_dict[tab_id] = new_tab

        tab = new_tab or self._tab_dict[tab_id]

        self.tabsChanged.emit()
        self.activateTabId(tab_id)
        return tab, new_tab is not None


    @Slot()
    def shutdown(self) -> None:
        for state in self._load_states.values():
            state.close()
        for tab in self._tab_dict.values():
            self._cancel_tab_render(tab)
            tab.dispose()
        self._tag_read_service.shutdown()

    @Slot()
    def _close_requested_tab(self):
        tab = self.sender()
        if isinstance(tab, TabController):
            self.closeTab(tab.tab_config.tab_id)

    def connect_signal(self, tab: TabController):
        self._watch_identity_views(tab)
        layout = getattr(tab, "twoDLayout", None)
        if layout is not None:
            layout.cellsChanged.connect(self._refresh_identity)
        tab.closeRequested.connect(self._close_requested_tab)
        tab.imageUpdateRequested.connect(self._image_provider.set_array)
        from qt_dicom_viewer.ui.controller.edit_history_controller import EditHistoryController
        tab._edit_history = EditHistoryController(tab)
        state = TabLoadingController(tab)
        self._load_states[tab.tab_config.tab_id] = state
        state.changed.connect(self.loadingStatesChanged.emit)
        # Record request identity before forwarding: even synchronous test
        # renderers and cached results must see the matching opening request.
        tab.renderRequested.connect(state.observe_request)
        if isinstance(tab, PetWorkspaceController):
            tab.volumeViewRequested.connect(self._open_fusion_volume)
        tab.renderRequested.connect(
            self.renderRequested.emit
        )
        tab.activeViewportChanged.connect(
            self.activeViewportChanged.emit
        )
        tab.imageRemovalRequested.connect(
            self._image_provider.remove_image
        )
        tab.stackNavigationRequested.connect(
            self.openSeriesSlice
        )

    def _find_tab_by_viewport_id(
            self,
            viewport_id: str,
    ) -> TabController | None:
        for tab in self._tab_dict.values():
            if tab.contains_viewport(viewport_id):
                return tab

        return None

    @Slot(object)
    def handleRenderResult(self, result: RenderResult):
        logger.debug(
            "Receive render result: viewport_id=%s",
            result.viewport_id,
        )
        tab = self._find_tab_by_viewport_id(result.viewport_id)
        if tab is None:
            logger.debug(
                "Discard render result for unknown or closed viewport: "
                "viewport_id=%s",
                result.viewport_id,
            )
            return

        if not tab.accepts_render_result(result):
            logger.debug(
                "Discard stale render result before updating image provider: "
                "request_id=%s viewport_id=%s",
                result.response_id,
                result.viewport_id,
            )
            return

        if isinstance(tab, TabController) and tab.discard_stale_mpr_window_result(result):
            return

        if isinstance(result, PetBatchRenderResult):
            for frame in result.frames:
                if frame.image is not None:
                    self._image_provider.set_array(frame.viewport_id, frame.image, frame.content_key)
        elif not isinstance(result, VolumeLoadResult) and result.image is not None:
            image_key = getattr(result, "image_key", result.viewport_id)
            self._image_provider.set_array(image_key, result.image)

        # Snapshot the completion before the tab schedules the next montage
        # frame, which can replace this viewport's pending request identity.
        state = self._load_states.get(tab.tab_config.tab_id)
        if state is not None:
            state.accept_result(result)
        tab.handleRenderResult(result)

    @Slot(str, str)
    def createMprCompareTab(self, first_uid, second_uid):
        from qt_dicom_viewer.core.compare import supports_mpr_compare
        from .tab.compare_mpr_tab_controller import CompareMprTabController
        if first_uid == second_uid or not all(supports_mpr_compare(self._series_catalog.get_series(uid))
                                              for uid in (first_uid, second_uid)):
            return
        tab_id = "comparempr:" + ":".join(sorted((first_uid, second_uid)))
        if self._reopen_retained(tab_id):
            return
        if tab_id in self._tab_dict:
            self.activateTabId(tab_id)
            return
        metas = tuple(self._series_catalog.get_series_display_meta(uid) for uid in (first_uid, second_uid))
        label = " / ".join(meta.series_description or meta.modality for meta in metas)
        tab = CompareMprTabController(TabConfig(tab_id, label, TabType.COMPARE_MPR, metas), self)
        self.connect_signal(tab)
        self._tab_dict[tab_id] = tab
        self.tabsChanged.emit()
        self.activateTabId(tab_id)
        tab.init_render()

    @Slot(str, str)
    def createCompareTab(self, first_uid, second_uid):
        self.createMultiCompareTab([first_uid, second_uid])

    @Slot('QVariantList')
    def createMultiCompareTab(self, series_uids):
        from qt_dicom_viewer.core.compare import supports_compare
        from .tab.compare_tab_controller import CompareTabController
        if not 2 <= len(series_uids) <= 4 or len(set(series_uids)) != len(series_uids) or not all(
                supports_compare(self._series_catalog.get_series(uid)) for uid in series_uids):
            return
        # Opening the same pair in reverse order activates its existing window.
        tab_id = "compare2d:" + ":".join(sorted(series_uids))
        if self._reopen_retained(tab_id):
            return
        if tab_id in self._tab_dict:
            self.activateTabId(tab_id)
            return
        metas = tuple(self._series_catalog.get_series_display_meta(uid) for uid in series_uids)
        label = " / ".join(meta.series_description or meta.modality for meta in metas)
        tab = CompareTabController(TabConfig(tab_id, label, TabType.COMPARE_2D, metas), self)
        self.connect_signal(tab)
        self._tab_dict[tab_id] = tab
        self.tabsChanged.emit()
        self.activateTabId(tab_id)
        tab.init_render()

    @Slot(str, str)
    def createFusionTab(self, ct_uid, pet_uid, *, isolated=False):
        ct = self._series_catalog.get_series(ct_uid)
        pet = self._series_catalog.get_series(pet_uid)
        if ct is None or pet is None or ct.modality.upper() != "CT" or pet.modality.upper() != "PT":
            return
        tab_id = f"petct:{ct_uid}:{pet_uid}"
        if not isolated and self._reopen_retained(tab_id):
            return
        if not isolated and tab_id in self._tab_dict:
            self.activateTabId(tab_id)
            return
        if isolated:
            from uuid import uuid4
            tab_id = "restore-source:" + uuid4().hex
        config = TabConfig(tab_id=tab_id, tab_label=f"{ct.patient_name} · PET/CT",
            tab_type=TabType.PETCT_FUSION, series_metas=(
                self._series_catalog.get_series_display_meta(ct_uid),
                self._series_catalog.get_series_display_meta(pet_uid)))
        tab = PetWorkspaceController(config, ct_series=ct, pet_series=pet, parent=self)
        self.connect_signal(tab)
        self._tab_dict[tab_id] = tab
        self.tabsChanged.emit()
        self.activateTabId(tab_id)
        tab.init_render()

    @Slot(object)
    def handleRenderFailure(self, failure: RenderFailure) -> None:
        tab = self._find_tab_by_viewport_id(failure.viewport_id)
        if tab is None:
            return
        # Interactive PET previews can already be visible when refinement fails.
        # Restore pixels before the controller refreshes the committed frame URLs.
        if (isinstance(tab, PetWorkspaceController) and not tab._closed
                and failure.request_id == tab._latest and tab._last_result is not None):
            for frame in tab._last_result.frames:
                if frame.image is not None:
                    self._image_provider.set_array(frame.viewport_id, frame.image)
        state = self._load_states.get(tab.tab_config.tab_id)
        if state is not None:
            state.accept_failure(failure)
        tab.handleRenderFailure(failure)

    def createFusionVolumeTab(self, source, *, target_id=None):
        from qt_dicom_viewer.ui.controller.tab.pet_volume_tab_controller import PetVolumeTabController
        if source._closed or not source.ready or not source.isFusion:
            return
        tab_id = target_id or source._tab_config.tab_id + ":volume"
        if self._reopen_retained(tab_id):
            return
        if tab_id not in self._tab_dict:
            config = TabConfig(tab_id=tab_id, tab_label=source._tab_config.tab_label + " · 3D", tab_type=TabType.THREE_D,
                               series_metas=source._tab_config.series_metas)
            tab = PetVolumeTabController(config, source, self)
            self.connect_signal(tab)
            self._load_states[tab_id].finish()
            self._tab_dict[tab_id] = tab
            self.tabsChanged.emit()
        else:
            self._tab_dict[tab_id].activeViewport.attach_source(source)
        self.activateTabId(tab_id)

    @Slot()
    def _open_fusion_volume(self):
        source = self.sender()
        if isinstance(source, PetWorkspaceController):
            session = self._window_manager.owner(source.tab_config.tab_id) if self._window_manager else None
            if session:
                self._window_manager.open_in(session, self.createFusionVolumeTab, source)
            else:
                self.createFusionVolumeTab(source)

    @Slot(str, int, float, float, bool)
    def openSeriesSlice(
        self,
        series_uid: str,
        slice_index: int,
        window_center: float,
        window_width: float,
        inverted: bool,
    ) -> None:
        series = self._series_catalog.get_series(series_uid)
        if series is None:
            return
        source = self.sender()
        session = (self._window_manager.owner(source.tab_config.tab_id)
                   if self._window_manager and hasattr(source, 'tab_config') else None)
        args = (series_uid, series.patient_name, TabType.TWO_D)
        tab, _ = (self._window_manager.open_in(session, self._create_or_activate_tab, *args)
                  if session else self._create_or_activate_tab(*args))
        if tab is None:
            return
        tab.navigate_stack(
            slice_index,
            WindowLevel(
                center=float(window_center),
                width=max(float(window_width), 1.0),
            ),
            bool(inverted),
        )


    @Slot(str, str)
    def activeWorkspace(self, series_uid: str, tab_type_value: str):
        try:
            tab_type = TabType(tab_type_value)
        except ValueError:
            logger.warning(
                "Unsupported tab type: %s",
                tab_type_value,
            )
            return
        series = self._series_catalog.get_series(series_uid)
        if series is None:
            return
        label = series.patient_name.strip() or series.series_description.strip() or _msg('text.0258')
        self.createTab(series_uid,label,tab_type)
