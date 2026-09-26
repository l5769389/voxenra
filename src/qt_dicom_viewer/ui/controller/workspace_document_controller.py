"""Asynchronous workspace persistence, UID-checked reopening and crash recovery."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import time
from weakref import WeakSet

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QStandardPaths, QCoreApplication, QEvent

from qt_dicom_viewer import __version__
from qt_dicom_viewer.core.local_import import LocalImportStore, ImportCancelled
from qt_dicom_viewer.core.workspace_document import (
    FORMAT, VERSION, source_manifest, read_document, load_referenced_series)
from qt_dicom_viewer.core.workspace_state import atomic_write, dumps
from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot, apply_fusion_source
from qt_dicom_viewer.ui.file_location import reveal_path
from qt_dicom_viewer.i18n.widgets import QFileDialog, QMessageBox


class WorkspaceDocumentController(QObject):
    _i18n_message = Signal()
    _i18n_recoveryStatusText = Signal()
    _i18n_workspaceName = Signal()

    changed = Signal()
    completed = Signal(object)
    progress = Signal(object)
    restored = Signal()

    def __init__(self, app, *, settings_path=None):
        super().__init__(app)
        self.app, self.workspace, self.panel = app, app.workspaceController, app.panelController
        self._path, self._message, self._error = "", "", False
        self._dirty = self._busy = self._closed = self._restoring = False
        self._recovery_dirty = False
        self._pending = None
        self._load_queue = []
        self._loading_tab = None
        self._cancel = Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workspace-files")
        self._wired = WeakSet()
        self._extra_paths = []
        self._sidebar_layout = {"width": 300., "collapsed": False}
        self._close_after_save = False
        self._remember_exit_after_save = False
        self._close_prompt_active = False
        self._open_after_save = None
        self._quit_approved = False
        if QCoreApplication.instance() is not None:
            QCoreApplication.instance().installEventFilter(self)
        root = (Path(settings_path).parent if settings_path else
                Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)))
        self._recovery_path = root / "workspace-recovery.voxworkspace"
        self._autosave_supported = settings_path is not False
        self._autosave_enabled = self._autosave_supported and self.app.settingsController.section("workspace")["automaticRecovery"]
        self._previous_recovery = self._autosave_supported and self._recovery_path.is_file()
        self._owns_recovery = False
        self._saving_recovery = False
        self._recovery_error = ""
        self._last_recovery_at = ""
        self.completed.connect(self._accept)
        self.progress.connect(self._set_message)
        self.workspace.tabsChanged.connect(self._tabs_changed)
        self.workspace.activeTabChanged.connect(self.mark_dirty)
        self.panel.seriesItemsChanged.connect(self.mark_dirty)
        self.panel.selectionChanged.connect(self.mark_dirty)
        self.panel.patientSearchChanged.connect(self.mark_dirty)
        self.app.settingsController.sectionChanged.connect(self._settings_changed)
        self.app.settingsController.sectionChanged.connect(self._recovery_setting_changed)
        self._autosave = QTimer(self)
        self._autosave.setInterval(30000)
        self._autosave.timeout.connect(self._save_recovery)
        if self._autosave_enabled:
            self._autosave.start()
        self._restore_timer = QTimer(self)
        self._restore_timer.setInterval(25)
        self._restore_timer.timeout.connect(self._advance_restore)

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(bool, notify=changed)
    def dirty(self): return self._dirty

    @Property(bool, notify=changed)
    def hasContent(self):
        # Layout initialization and utility tabs can mark the workspace dirty
        # without any image work to save. The registry includes detached tabs.
        return bool(self.panel._scan_series_record) or any(
            tab.tab_config.series_metas for tab in self.workspace._tab_dict.values())

    @Property(str, notify=changed)
    def path(self): return self._path

    @_TextProperty(str, notify=_i18n_workspaceName, notify_name='_i18n_workspaceName', source_notify='changed')
    def workspaceName(self): return Path(self._path).stem if self._path else _msg('text.0401')

    @Property(str, constant=True)
    def recoveryPath(self): return str(self._recovery_path)

    @Property(bool, notify=changed)
    def recoveryDirectoryAvailable(self): return self._recovery_path.parent.is_dir()

    @Property(bool, notify=changed)
    def automaticRecovery(self): return self._autosave_enabled

    @Property(str, notify=changed)
    def recoveryState(self):
        if self._saving_recovery:
            return "saving"
        if self.recoveryAvailable:
            return "recoverable"
        if not self._autosave_enabled:
            return "disabled"
        if self._recovery_error:
            return "error"
        if not self.hasContent:
            return "idle"
        if self._recovery_dirty:
            return "pending"
        if self._last_recovery_at and self._owns_recovery:
            return "saved"
        return "idle"

    @_TextProperty(str, notify=_i18n_recoveryStatusText, notify_name='_i18n_recoveryStatusText', source_notify='changed')
    def recoveryStatusText(self):
        state = self.recoveryState
        return {
            "saving": _msg('text.0402'),
            "recoverable": _msg('text.0403'),
            "disabled": _msg('text.0404'),
            "error": _msg('text.0405') + self._recovery_error,
            "idle": _msg('text.0406'),
            "pending": _msg('text.0407'),
            "saved": _msg('text.0408') + self._last_recovery_at,
        }[state]

    @Slot(str)
    def _settings_changed(self, section):
        if section not in ("workspace", "appearance"):
            self.mark_dirty()

    @Slot(str)
    def _recovery_setting_changed(self, section):
        if section != "workspace":
            return
        enabled = self._autosave_supported and self.app.settingsController.section("workspace")["automaticRecovery"]
        if enabled != self._autosave_enabled:
            self._autosave_enabled = enabled
            if enabled:
                self._recovery_dirty = True
                self._autosave.start()
            else:
                self._autosave.stop()
            self.changed.emit()

    @Slot(bool, result=bool)
    def setAutomaticRecovery(self, enabled):
        if self._busy or not self._autosave_supported:
            return False
        saved = self.app.settingsController.setValue("workspace", "automaticRecovery", enabled)
        if not saved:
            self._message, self._error = self.app.settingsController._message, True
            self.changed.emit()
        return saved

    @Slot()
    def copyRecoveryPath(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(str(self._recovery_path))

    @Slot(result=bool)
    def openRecoveryDirectory(self):
        if reveal_path(str(self._recovery_path.parent)):
            return True
        self._message, self._error = _msg('text.0409'), True
        self.changed.emit()
        return False

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='changed')
    def message(self): return self._message

    @Property(bool, notify=changed)
    def isError(self): return self._error

    @Property(bool, notify=changed)
    def restoring(self): return self._restoring

    @Property('QVariantMap', notify=changed)
    def sidebarLayout(self): return dict(self._sidebar_layout)

    @Slot(float, bool)
    def setSidebarLayout(self, width, collapsed):
        value = dict(width=max(200., min(350., width)), collapsed=collapsed)
        if value != self._sidebar_layout:
            self._sidebar_layout = value
            self.mark_dirty()

    @Property(bool, notify=changed)
    def hasMissingSources(self):
        return self._pending is not None and bool(self._pending["missing"])

    @Property(bool, notify=changed)
    def recoveryAvailable(self):
        return self._previous_recovery and self._recovery_path.is_file()

    def _set_message(self, message):
        if not self._closed:
            self._message = message
            self.changed.emit()

    def mark_dirty(self, *args):
        if not self._restoring and not self._closed:
            self._dirty = self._recovery_dirty = True
            self.changed.emit()

    def _tabs_changed(self):
        for tab in self.workspace._tab_dict.values():
            if tab in self._wired:
                continue
            self._wired.add(tab)
            for name in ("settingsChanged", "phaseChanged", "fpsChanged", "snapshotCommitted", "viewLayoutChanged", "persistenceChanged"):
                signal = getattr(tab, name, None)
                if signal is not None:
                    signal.connect(self.mark_dirty)
            tools = [getattr(tab, "toolController", None)]
            tools.extend(group.toolController for group in getattr(tab, "groups", ()))
            layout = getattr(tab, "mprLayout", None)
            if layout is not None:
                tools.append(layout.volumeTools)
            for controller in tools:
                if controller is not None:
                    for name in ("activeToolChanged", "activePanelChanged", "activeInteractionChanged", "activeServiceChanged"):
                        getattr(controller, name).connect(self.mark_dirty)
            history = getattr(tab, "_edit_history", None)
            if history is not None:
                history.changed.connect(self.mark_dirty)
            for view in tab.viewports_by_id.values():
                for name in ("transformChanged", "windowChanged", "windowLevelChanged",
                             "displayStateChanged", "stateChanged", "sliceIndexChanged", "displayCommand", "petDisplayChanged", "crosshairImagePositionChanged"):
                    signal = getattr(view, name, None)
                    if signal is not None:
                        signal.connect(self.mark_dirty)
        self.mark_dirty()

    def _capture(self, path):
        tabs = self.app.windowManager.ordered_tabs()
        sidebar = list(self.panel._scan_series_record)
        ids = set(sidebar)
        ids.update(m.series_uid for tab in tabs for m in tab.tab_config.series_metas)
        records = [self.app._series_catalog.get_series(uid) for uid in sorted(ids)]
        records = [record for record in records if record is not None]
        if any(getattr(view, "editBusy", False) for tab in tabs for view in tab.viewports_by_id.values()):
            raise ValueError(_msg('text.0410'))
        document = {"format": FORMAT, "version": VERSION, "applicationVersion": __version__,
                    "savedAt": datetime.now(timezone.utc).isoformat(),
                    "tabs": [tab_snapshot(tab) for tab in tabs],
                    "activeTab": next((i for i, tab in enumerate(tabs) if tab is self.workspace.activeTab), 0),
                    "sidebar": sidebar, "selected": list(self.panel._selected_series_uids),
                    "activeSeries": self.panel._active_series_uid,
                    "search": self.panel._patient_search, "collapsed": list(self.panel._collapsed_groups),
                    "layout": dict(self.app.settingsController.values["layout"]),
                    "sidebarLayout": dict(self._sidebar_layout)}
        # No live QObject crosses the worker boundary; source records and value
        # dataclasses are immutable, and source provenance gets its own index.
        resolver = LocalImportStore()
        resolver._archive_sources = dict(self.panel._import_store._archive_sources)
        return document, records, resolver

    def save_to(self, path, *, recovery=False):
        if self._busy or self.panel.scanning or self._closed:
            return False
        try:
            document, records, resolver = self._capture(path)
        except ValueError as error:
            self._message, self._error = error_message(error), True
            if recovery:
                self._recovery_error = error_message(error)
                self._message = _msg('text.0405') + error_message(error)
            self.changed.emit()
            return False
        self._busy = True
        self._saving_recovery = recovery
        if not recovery:
            self._error = False
            self._message = _msg('text.0411')
            self._dirty = False
        else:
            if self._message.startswith(_msg('text.0412')):
                self._message, self._error = "", False
            self._recovery_error = ""
            self._recovery_dirty = False
        self.changed.emit()

        def save():
            document["series"] = [source_manifest(record, resolver, path) for record in records]
            atomic_write(path, dumps(document))
            return {"kind": "save", "path": str(path), "recovery": recovery}
        self._submit(save, "save")
        return True

    def _submit(self, function, kind):
        future = self._executor.submit(function)
        def done(result):
            try:
                payload = result.result()
            except Exception as error:
                payload = {"kind": kind, "error": error_message(error) or _msg('text.0413')}
            if self._closed:
                if payload.get("store") is not None:
                    payload["store"].cleanup()
            else:
                self.completed.emit(payload)
        future.add_done_callback(done)

    @Slot()
    def save(self):
        if self._path:
            return self.save_to(self._path)
        return self.saveAs()

    @Slot()
    def saveAs(self):
        if self._busy or self.panel.scanning:
            return False
        path, _ = QFileDialog.getSaveFileName(None, _msg('text.0414'), self._path or _msg('text.0415'),
                                            _msg('text.0416'))
        if not path:
            return False
        if not path.lower().endswith(".voxworkspace"):
            path += ".voxworkspace"
        return self.save_to(path)

    def _confirm_replace(self, path):
        if not self._dirty or not self.hasContent:
            return True
        answer = QMessageBox.question(None, _msg('text.0417'), _msg('text.0418'),
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            self._open_after_save = path
            if not self.save():
                self._open_after_save = None
            return False
        return answer == QMessageBox.Discard

    @Slot()
    def open(self):
        if self._busy or self.panel.scanning:
            return
        path, _ = QFileDialog.getOpenFileName(None, _msg('text.0417'), self._path,
                                            _msg('text.0416'))
        if path and self._confirm_replace(path):
            self.restore_from(path)

    def restore_from(self, path, *, extra_paths=()):
        if self._busy or self.panel.scanning or self._closed:
            return False
        if self.app.pacsController.busy:
            self._message, self._error = _msg('text.0419'), True
            self.changed.emit()
            return False
        self._busy, self._error, self._restoring = True, False, True
        self._cancel.clear()
        self._extra_paths = list(extra_paths)
        self._message = _msg('text.0420')
        self.changed.emit()
        def load():
            store = LocalImportStore()
            try:
                document = read_document(path)
                snapshot, missing = load_referenced_series(document, path, store, extra_paths=extra_paths,
                    cancelled=self._cancel.is_set, progress=self.progress.emit)
                if self._cancel.is_set():
                    raise ImportCancelled(_msg('text.0421'))
                return dict(kind="load", document=document, snapshot=snapshot, missing=missing,
                            store=store, path=str(path))
            except BaseException:
                store.cleanup()
                raise
        self._submit(load, "load")
        return True

    @Slot(object)
    def _accept(self, payload):
        if self._closed:
            if payload.get("store") is not None:
                payload["store"].cleanup()
            return
        recovery_save = self._saving_recovery
        self._saving_recovery = False
        if "error" in payload:
            self._busy = self._restoring = False
            self._error, self._message = True, payload["error"]
            if payload["kind"] == "save":
                self._recovery_dirty = True
                if recovery_save:
                    self._recovery_error = payload["error"]
                    self._message = _msg('text.0405') + payload["error"]
                else:
                    self._dirty = True
            self._close_after_save = False
            self._remember_exit_after_save = False
            self._open_after_save = None
        elif payload["kind"] == "save":
            self._busy = False
            if not payload["recovery"]:
                self._message = _msg('text.0422')
                self._path = payload["path"]
                if self._dirty:
                    self._close_after_save = False
                    self._remember_exit_after_save = False
                    self._open_after_save = None
                    self._message = _msg('text.0423')
                if self._close_after_save and not self._dirty:
                    remember = self._remember_exit_after_save
                    self._close_after_save = self._remember_exit_after_save = False
                    if not remember or self._remember_exit_behavior("save"):
                        self._quit_approved = True
                        QCoreApplication.quit()
                if self._open_after_save and not self._dirty:
                    target, self._open_after_save = self._open_after_save, None
                    self.restore_from(target)
            else:
                self._owns_recovery = True
                self._last_recovery_at = datetime.now().astimezone().strftime("%H:%M:%S")
                self._recovery_error = ""
        else:
            if self._pending is not None:
                self._pending["store"].cleanup()
            self._pending = payload
            if payload["missing"]:
                self._busy = self._restoring = False
                self._message = _msg('text.0424', value1=len(payload['missing']))
                self._error = True
            else:
                self._begin_restore()
        self.changed.emit()

    @Slot()
    def locateMissing(self):
        if self._pending is None:
            return
        from qt_dicom_viewer.ui.dialogs.local_import_dialog import select_import_paths
        paths = select_import_paths()
        if paths:
            self._extra_paths.extend(paths)
            self.restore_from(self._pending["path"], extra_paths=self._extra_paths)

    @Slot()
    def skipMissing(self):
        if self._pending is not None and self._pending["snapshot"] is not None:
            self._begin_restore()

    def _begin_restore(self):
        payload = self._pending
        self._busy = self._restoring = True
        self._error = False
        # Parsing and UID/geometry checks finish before existing tabs are closed.
        for tab_id in list(self.workspace._tab_dict):
            self.workspace.closeTab(tab_id)
        self.app.windowManager.restore_to_main()
        self._wired.clear()
        snapshot = payload["snapshot"]
        if snapshot is not None:
            self.app._series_catalog.update(snapshot)
        old_store = self.panel._import_store
        self.panel._import_store = payload["store"]
        self._retired_stores = getattr(self, "_retired_stores", []) + [old_store]
        available = {s.series_instance_uid: s for s in snapshot.series} if snapshot else {}
        doc = payload["document"]
        self._sidebar_layout = doc.get("sidebarLayout", {"width": 300., "collapsed": False})
        if self.panel._thumbnail_service is not None:
            for uid in self.panel._scan_series_record:
                self.panel._thumbnail_service.cancel(uid)
        self.panel._scan_series_record = {uid: available[uid] for uid in doc.get("sidebar", []) if uid in available}
        self.panel._removed_series_uids.clear()
        self.panel._selected_series_uids = [uid for uid in doc.get("selected", []) if uid in self.panel._scan_series_record]
        self.panel._patient_search = doc.get("search", "")
        self.panel._collapsed_groups = set(doc.get("collapsed", []))
        active = doc.get("activeSeries", "")
        selected = self.panel._selected_series_uids
        self.panel._active_series_uid = active if active in selected else (selected[-1] if selected else "")
        self.panel._thumbnails.clear()
        self.panel.seriesItemsChanged.emit()
        self.panel.patientSearchChanged.emit()
        self.panel.selectionChanged.emit()
        self.panel.sidebarItemsChanged.emit()
        self.panel._thumbnail_timer.start()
        for key, value in doc.get("layout", {}).items():
            self.app.settingsController.setValue("layout", key, value)
        self._load_queue = [(index, tab) for index, tab in enumerate(doc["tabs"])
                            if all(uid in available for uid in tab["series"])]
        self._load_queue.sort(key=lambda item: 0 if "fusionSource" in item[1] else 1)
        self._restored_ids = {}
        self._loading_tab = None
        self._restore_timer.start()

    def _advance_restore(self):
        if self._closed:
            return
        try:
            if self._cancel.is_set():
                self._finish_restore(_msg('text.0425'), error=True)
                return
            if self._loading_tab is not None:
                index, record, tab, started, is_source, applied = self._loading_tab
                state = self.workspace._load_states.get(tab.tab_config.tab_id)
                if state is not None and state.status == "error":
                    self._finish_restore(_msg('text.0426'), error=True)
                    return
                if (state is not None and state.status != "ready") or tab._active_mpr_requests:
                    if time.monotonic() - started > 180:
                        raise ValueError(_msg('text.0427'))
                    return
                if is_source:
                    if not applied and "fusionSource" in record:
                        state.restart()
                        apply_fusion_source(tab, record["fusionSource"])
                        self._loading_tab = (index, record, tab, started, True, True)
                        return
                    self.workspace.createFusionVolumeTab(tab)
                    volume_tab = self.workspace.activeTab
                    self.workspace.closeTab(tab.tab_config.tab_id)
                    self._loading_tab = (index, record, volume_tab, time.monotonic(), False, False)
                    return
                if not applied:
                    if state is not None and any(hasattr(v, "_frame_meta") for v in tab.viewports_by_id.values()):
                        state.restart()
                    apply_tab_snapshot(tab, record)
                    self._loading_tab = (index, record, tab, started, False, True)
                    return
                if getattr(tab, "_edit_history", None) is not None:
                    tab._edit_history.reset()
                self._restored_ids[index] = tab.tab_config.tab_id
                self._loading_tab = None
                return
            if not self._load_queue:
                self._finish_restore(_msg('text.0428'))
                return
            index, record = self._load_queue.pop(0)
            kind, uids = record["type"], record["series"]
            self._message = _msg('text.0429', value1=index + 1, value2=len(self._pending['document']['tabs']))
            self.changed.emit()
            if kind in ("settings", "pacs", "manual"):
                {"settings": self.workspace.openSettings, "pacs": self.workspace.openPacs,
                 "manual": self.workspace.openManual}[kind]()
                self._restored_ids[index] = self.workspace.activeTabId
                return
            fusion_volume = kind == "3d" and len(uids) == 2
            if kind == "comparempr":
                self.workspace.createMprCompareTab(*uids)
            elif kind == "compare2d":
                self.workspace.createMultiCompareTab(uids)
            elif kind == "petctfusion" or fusion_volume:
                self.workspace.createFusionTab(*uids)
            else:
                self.workspace.createTab(uids[0], record["label"], kind)
            tab = self.workspace.activeTab
            if tab is None:
                raise ValueError(_msg('text.0430'))
            self._loading_tab = (index, record, tab, time.monotonic(), fusion_volume, False)
        except Exception as error:
            self._finish_restore(_msg('text.0431', value1=error), error=True)

    def _finish_restore(self, message, *, error=False):
        self._restore_timer.stop()
        self._loading_tab = None
        payload = self._pending
        if payload is not None:
            ordered = [self._restored_ids[index] for index in sorted(self._restored_ids)]
            ordered.extend(key for key in self.workspace._tab_dict if key not in ordered)
            self.workspace._tab_dict = {key: self.workspace._tab_dict[key] for key in ordered
                                        if key in self.workspace._tab_dict}
            self.app.windowManager.restore_to_main()
            self.workspace.tabsChanged.emit()
            if payload["missing"]:
                error = True
                message += _msg('text.0432', value1=len(payload['missing']))
            active = self._restored_ids.get(payload["document"].get("activeTab", 0))
            if active:
                self.workspace.activateTabId(active)
            self._path = "" if error or Path(payload["path"]) == self._recovery_path else payload["path"]
            if Path(payload["path"]) == self._recovery_path:
                self._previous_recovery = False
                self._owns_recovery = True
        self._pending = None
        self._busy = False
        self._dirty = bool(error or not self._path)
        self._recovery_dirty = True  # A reopened workspace must replace any older recovery snapshot.
        self._message, self._error = message, error
        self.changed.emit()
        self.restored.emit()
        self._restoring = False
        self.changed.emit()

    @Slot()
    def cancel(self):
        self._cancel.set()

    def _save_recovery(self):
        if (self._autosave_enabled and not self._previous_recovery and self._recovery_dirty
                and not self._busy and not self.hasMissingSources
                and self.hasContent):
            self.save_to(self._recovery_path, recovery=True)

    @Slot()
    def recover(self):
        if self.recoveryAvailable and self._confirm_replace(self._recovery_path):
            self.restore_from(self._recovery_path)

    @Slot()
    def discardRecovery(self):
        if not self._busy and self._autosave_supported:
            self._recovery_path.unlink(missing_ok=True)
            self._previous_recovery = self._owns_recovery = False
            self._last_recovery_at = self._recovery_error = ""
            self._recovery_dirty = True
            self.changed.emit()

    def _ask_exit_behavior(self):
        from qt_dicom_viewer.ui.dialogs.workspace_exit_dialog import WorkspaceExitDialog
        dialog = WorkspaceExitDialog(self.app.appearanceController,
                                     workspace_name=Path(self._path).stem if self._path else "")
        try:
            answer = dialog.exec()
            return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(answer, "cancel"), dialog.checkBox().isChecked()
        finally:
            dialog.deleteLater()

    def _remember_exit_behavior(self, behavior):
        saved = self.app.settingsController.setValue("workspace", "exitBehavior", behavior)
        if not saved:
            self._message, self._error = self.app.settingsController._message, True
            self.changed.emit()
        return saved

    @Slot(result=bool)
    def requestClose(self):
        if self._closed or self._quit_approved:
            return True
        if self._close_prompt_active:
            return False
        if self._busy:
            self._message = _msg('text.0436')
            self.changed.emit()
            return False
        if not self._dirty or not self.hasContent:
            self._quit_approved = True
            return True
        self._close_prompt_active = True
        try:
            behavior = self.app.settingsController.section("workspace")["exitBehavior"]
            remember = False
            if behavior == "ask":
                behavior, remember = self._ask_exit_behavior()
            if behavior == "save":
                self._close_after_save = True
                self._remember_exit_after_save = remember
                if not self.save():
                    self._close_after_save = self._remember_exit_after_save = False
                return False
            if behavior == "discard":
                self._quit_approved = not remember or self._remember_exit_behavior("discard")
                return self._quit_approved
            return False
        finally:
            self._close_prompt_active = False

    def eventFilter(self, watched, event):
        if watched is QCoreApplication.instance() and event.type() == QEvent.Quit:
            return not self.requestClose()
        return False

    def shutdown(self):
        self._closed = True
        if QCoreApplication.instance() is not None:
            QCoreApplication.instance().removeEventFilter(self)
        self._cancel.set()
        self._autosave.stop()
        self._restore_timer.stop()
        self._executor.shutdown(wait=True, cancel_futures=True)
        if self._pending is not None and not self._restoring:
            self._pending["store"].cleanup()
        if self._owns_recovery:
            self._recovery_path.unlink(missing_ok=True)

    def cleanup_imports(self):
        for store in getattr(self, "_retired_stores", []):
            store.cleanup()
