from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from typing import Dict

from qt_dicom_viewer.core.local_import import LocalImportStore

from PySide6.QtCore import QObject, Signal, QThread, QTimer, Slot, Property, QUrl
from PySide6.QtGui import QDesktopServices
from qt_dicom_viewer.ui.dialogs.local_import_dialog import select_import_paths

from qt_dicom_viewer.model import DicomFolderScanSnapshot, DicomSeriesRecord
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.ui.workers.dicom_scan_worker import (
    DicomScanWorker,
)

from qt_dicom_viewer.core.series_sidebar import build_sidebar_rows
from qt_dicom_viewer.ui.controller.series_sidebar_model import SeriesSidebarModel
from qt_dicom_viewer.service.thumbnail_service import ThumbnailRequest, ThumbnailService


class PanelController(QObject):
    _i18n_fusionAnchor = Signal()
    _i18n_fusionCandidates = Signal()
    _i18n_fusionError = Signal()
    _i18n_fusionIdentityWarning = Signal()
    _i18n_seriesItems = Signal()
    _i18n_activeMrViewErrors = Signal()
    _i18n_sidebarItems = Signal()
    _i18n_statusMessage = Signal()


    statusMessageChanged = Signal()
    importTaskChanged = Signal()
    scanningChanged = Signal()
    seriesItemsChanged = Signal()
    sidebarItemsChanged = Signal()
    selectionChanged = Signal()
    viewSupportChanged = Signal()
    patientSearchChanged = Signal()
    # series_uid , tab_type
    tabCreateRequested = Signal(str, str)
    fusionCreateRequested = Signal(str, str)
    fusionDialogChanged = Signal()

    # parent=self 是 Qt 的对象所有权关系，不是业务上的“父子 Controller 调用关系”。
    def __init__(self, parent=None, series_catalog=None, *, image_provider=None) -> None:
        super().__init__(parent)
        self.selectionChanged.connect(self.viewSupportChanged.emit)
        self._scan_thread: QThread | None = None
        self._scan_worker: DicomScanWorker | None = None
        self._scanning = False
        self._status_message = ""
        self._import_error = False
        self._import_task_open = False
        self._import_progress = -1.0
        self._import_clean_success = False
        self._last_import_paths = []
        self._last_import_directory = ""
        self._import_store = LocalImportStore()
        self._last_import_snapshot = None
        self._scan_series_record: Dict[str, DicomSeriesRecord] = {}
        self._removed_series_uids: set[str] = set()
        self._series_catalog:SeriesCatalog = series_catalog
        self._active_series_uid = ""
        self._selected_series_uids = []
        self._fusion_anchor_uid = ""
        self._fusion_partner_uid = ""
        self._fusion_dialog_open = False
        self._fusion_error = ""
        self._fusion_show_all = False
        self._patient_search = ""
        self._collapsed_groups: set[str] = set()
        self._thumbnails: dict[str, str] = {}
        self._thumbnail_version = 0
        self._image_provider = image_provider
        self._closing = False
        from .compare_series_controller import CompareSeriesController
        self._compare_controller = CompareSeriesController(self)
        self._sidebar_model = SeriesSidebarModel(self)
        self._compact_sidebar_model = SeriesSidebarModel(self)
        self.sidebarItemsChanged.connect(self._refresh_sidebar_model)
        self._thumbnail_service = ThumbnailService(self) if image_provider is not None else None
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.setInterval(150)
        self._thumbnail_timer.timeout.connect(self._request_thumbnails)
        if self._thumbnail_service is not None:
            self._thumbnail_service.finished.connect(self._accept_thumbnail)


    @Property(QObject, constant=True)
    def compareController(self):
        return self._compare_controller

    def _workspace_is_restoring(self):
        document = getattr(self.parent(), "workspaceDocumentController", None)
        return document is not None and document.restoring

    def _start_import(self, paths):
        if self._closing or self._scanning or not paths or self._workspace_is_restoring():
            return
        self._last_import_snapshot = None
        self._import_clean_success = False
        self._last_import_paths = list(paths)
        self._import_task_open = True
        self._import_progress = -1.0
        self._set_status(_msg('text.0472'))
        # An explicit new import can restore items removed from the previous scan.
        self._removed_series_uids.clear()
        self._set_scanning(True)
        thread = QThread(self)
        worker = DicomScanWorker(paths, self._import_store,
            base_series=self._series_catalog.snapshot() if self._series_catalog else {})
        self.importTaskChanged.emit()

        self._scan_thread = thread
        self._scan_worker = worker

        worker.moveToThread(thread)
        self._wire_scan_thread(self._scan_thread, self._scan_worker)
        thread.start()

    def _wire_scan_thread(self,thread: QThread | None, worker: QObject | None) -> None:
        if thread is None or worker is None:
            return

        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_scan_finished)
        worker.failed.connect(self._handle_scan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clean_scan_thread)

        worker.process.connect(self._handle_scan_process)
        worker.status.connect(self._set_status)
        worker.progress.connect(self._handle_import_progress)

    @Slot(object)
    def _handle_scan_process(self, result:DicomFolderScanSnapshot) -> None:
        if self._closing or result is None: return
        self._last_import_snapshot = result
        try:
            self._update_series_record(result)
            self.update_series_session(result)
        finally:
            if self._scan_worker:
                self._scan_worker.acknowledge_process()

    @Slot(int, int, int, int)
    def _handle_import_progress(self, processed, total, dicom, skipped):
        if self._closing or (self._scan_thread and self._scan_thread.isInterruptionRequested()):
            return
        self._import_progress = processed / total if total else 0.0
        self.importTaskChanged.emit()
        self._set_status(_msg('text.0473', value1=f'{processed:,}', value2=f'{total:,}', value3=f'{dicom:,}', value4=f'{skipped:,}'))

    @Property(bool, notify=importTaskChanged)
    def importTaskOpen(self): return self._import_task_open

    @Property(float, notify=importTaskChanged)
    def importProgress(self): return self._import_progress

    @Slot()
    def closeImportTask(self):
        self._import_task_open = False
        self.importTaskChanged.emit()

    @Slot()
    def retryImport(self):
        if not self._scanning and self._last_import_paths:
            self._start_import(self._last_import_paths)

    def update_series_session(self, dicom_scan_snapshot:DicomFolderScanSnapshot):
        self._series_catalog.update(dicom_scan_snapshot)


    @Slot(object)
    def _handle_scan_finished(self, result: DicomFolderScanSnapshot | None) -> None:
        if self._closing: return
        if result is not None and result is not self._last_import_snapshot:
            self._handle_scan_process(result)
        final = self._last_import_snapshot
        self._import_clean_success = False
        if self._scan_thread and self._scan_thread.isInterruptionRequested():
            self._set_status(_msg('text.0474'))
        elif final is None or not final.dicom_file_count:
            self._set_status(_msg('text.0475'), True)
        else:
            self._set_status(_msg('text.0476', value1=len(final.series), value2=final.dicom_file_count)
                             + (_msg('text.0477', value1=final.skipped_file_count) if final.skipped_file_count else "")
                             + (_msg('import.alreadyLoaded', count=final.existing_file_count) if final.existing_file_count else ""))
            self._import_clean_success = not (final.skipped_file_count or final.existing_file_count)

    @Slot(object)
    def _handle_scan_failed(self, error) -> None:
        if not self._closing:
            self._import_clean_success = False
            self._set_status(error_message(error), True)

    @_TextProperty(str, notify=_i18n_statusMessage, notify_name='_i18n_statusMessage', source_notify='statusMessageChanged')
    def statusMessage(self): return self._status_message

    @Property(bool, notify=statusMessageChanged)
    def importError(self): return self._import_error

    @Slot(object)
    def _set_status(self, message, error=False):
        if self._closing: return
        self._status_message, self._import_error = message, error
        self.statusMessageChanged.emit()

    @Slot()
    def cancelImport(self):
        if self._scan_thread:
            self._set_status(_msg('text.0478'))
            self._scan_thread.requestInterruption()

    @Slot("QVariantList", result=bool)
    def canImportUrls(self, urls):
        return bool(urls) and not self._closing and not self._scanning and not self._workspace_is_restoring() and all(
            QUrl(url).isLocalFile() and QUrl(url).toLocalFile() for url in urls)

    @Slot("QVariantList", result=bool)
    def importUrls(self, urls):
        if not self.canImportUrls(urls): return False
        self._start_import([QUrl(url).toLocalFile() for url in urls])
        return True

    @Slot()
    def openImportDialog(self):
        if self._closing or self._workspace_is_restoring():
            return
        if self._scanning:
            self.cancelImport()
            return
        paths = select_import_paths(self._last_import_directory)
        if paths:
            from pathlib import Path
            chosen = Path(paths[0])
            self._last_import_directory = str(chosen if chosen.is_dir() else chosen.parent)
            self._start_import(paths)

    def cleanup_imports(self):
        self._import_store.cleanup()

    @Slot()
    def _clean_scan_thread(self) -> None:
        thread = self._scan_thread
        # finished is emitted before the worker's deferred deletion completes.
        # Keep its Python wrapper alive until the native thread has fully exited.
        if thread is not None:
            thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self._set_scanning(False)
        # Close only after the worker exits, so the native busy-window close guard
        # cannot veto a clean result. All other outcomes stay open for review.
        if self._import_clean_success and not self._closing:
            self.closeImportTask()

        if thread is not None:
            thread.deleteLater()

    def _set_scanning(self, scanning: bool) -> None:
        if self._scanning == scanning:
            return

        self._scanning = scanning
        self.scanningChanged.emit()
        if not scanning and not self._closing:
            self._thumbnail_timer.start()

    def _update_series_record(self, process:DicomFolderScanSnapshot | None) -> None:
        if process is None or self._closing:
            return
        for each_series in process.series:
            if each_series.series_instance_uid in self._removed_series_uids:
                continue
            self._scan_series_record[each_series.series_instance_uid] = each_series
        self.seriesItemsChanged.emit()
        self.viewSupportChanged.emit()
        self.sidebarItemsChanged.emit()
        self.fusionDialogChanged.emit()
        if self._thumbnail_service is not None:
            self._thumbnail_timer.start()

    def _refresh_sidebar_model(self):
        # Models keep message IDs; only their data() method localizes values.
        rows = build_sidebar_rows(self._scan_series_record.values(), self._patient_search,
                                  self._collapsed_groups, self._thumbnails)
        self._sidebar_model.update_rows(rows, self._patient_search)
        # The compact rail keeps the search scope but exposes series inside folded groups.
        if self._collapsed_groups and not self._patient_search.strip():
            rows = build_sidebar_rows(self._scan_series_record.values(), self._patient_search,
                                      set(), self._thumbnails)
        self._compact_sidebar_model.update_rows(
            [row for row in rows if row["kind"] == "series"], self._patient_search)

    @Property(QObject, constant=True)
    def compactSidebarModel(self):
        return self._compact_sidebar_model

    @Property(QObject, constant=True)
    def sidebarModel(self):
        return self._sidebar_model

    @Property(bool, notify=seriesItemsChanged)
    def hasSeries(self):
        return bool(self._scan_series_record)

    @_TextProperty('QVariantList', notify=_i18n_sidebarItems, notify_name='_i18n_sidebarItems', source_notify='sidebarItemsChanged')
    def sidebarItems(self):
        return build_sidebar_rows(self._scan_series_record.values(), self._patient_search,
                                  self._collapsed_groups, self._thumbnails)

    @Property(str, notify=selectionChanged)
    def activeSeriesUid(self):
        return self._active_series_uid

    @Property(bool, notify=selectionChanged)
    def activeSeriesSupportsFourD(self) -> bool:
        return self.seriesSupportsFourD(self._active_series_uid)

    @Slot(str, result=bool)
    def seriesSupportsFourD(self, series_uid: str) -> bool:
        series = self._scan_series_record.get(series_uid)
        return bool(series is not None and series.supports_four_d)
    @Property(str, notify=selectionChanged)
    def activeSeriesModality(self) -> str:
        series = self._scan_series_record.get(self._active_series_uid)
        return series.modality.strip().upper() if series is not None else ""

    @_TextProperty('QVariantMap', notify=_i18n_activeMrViewErrors, notify_name='_i18n_activeMrViewErrors', source_notify='viewSupportChanged')
    def activeMrViewErrors(self):
        return {view: self.seriesViewError(self._active_series_uid, view)
                for view in ('2d', 'montage', 'mpr', '3d', '4d', 'fusion')}

    @Slot(str, str, result=str)
    def seriesViewError(self, series_uid, view):
        from qt_dicom_viewer.core.mr import mr_view_error
        from qt_dicom_viewer.core.ct import ct_view_error
        from qt_dicom_viewer.i18n.messages import localize
        series = self._scan_series_record.get(series_uid)
        error = ct_view_error(series, view) or mr_view_error(series, view)
        if not error and view == "4d" and series is not None and not series.supports_four_d:
            error = _msg("playback.unsupported4D")
        return str(localize(error))

    @Slot(str, result=str)
    def seriesModality(self, series_uid: str) -> str:
        series = self._scan_series_record.get(series_uid)
        return series.modality.strip().upper() if series is not None else ""

    @Slot(str)
    def selectSeries(self, series_uid):
        if series_uid in self._scan_series_record:
            self._active_series_uid = series_uid
            self._selected_series_uids = [series_uid]
            self.selectionChanged.emit()

    @Property('QVariantList', notify=selectionChanged)
    def selectedSeriesUids(self):
        return list(self._selected_series_uids)

    @Slot(str, bool)
    def selectSeriesWithModifiers(self, uid, additive):
        if not additive:
            self.selectSeries(uid)
        elif uid in self._scan_series_record:
            if uid in self._selected_series_uids:
                self._selected_series_uids.remove(uid)
            else:
                self._selected_series_uids.append(uid)
            self._active_series_uid = self._selected_series_uids[-1] if self._selected_series_uids else ""
            self.selectionChanged.emit()

    @Slot(str)
    def selectContextSeries(self, uid):
        if uid in self._selected_series_uids:
            self._active_series_uid = uid
            self.selectionChanged.emit()
        elif not self._selected_series_uids:
            self.selectSeries(uid)

    @Property(bool, notify=fusionDialogChanged)
    def fusionDialogOpen(self):
        return self._fusion_dialog_open

    @_TextProperty(str, notify=_i18n_fusionError, notify_name='_i18n_fusionError', source_notify='fusionDialogChanged')
    def fusionError(self):
        return self._fusion_error

    @Property(str, notify=fusionDialogChanged)
    def fusionPartnerUid(self):
        return self._fusion_partner_uid

    @staticmethod
    def _same_patient(a, b):
        return bool(a.patient_id and b.patient_id and
                    (a.patient_id, a.patient_id_issuer) == (b.patient_id, b.patient_id_issuer))

    @_TextProperty('QVariantMap', notify=_i18n_fusionAnchor, notify_name='_i18n_fusionAnchor', source_notify='fusionDialogChanged')
    def fusionAnchor(self):
        record = self._scan_series_record.get(self._fusion_anchor_uid)
        return self._fusion_record_item(record) if record else {}

    @Property(str, notify=fusionDialogChanged)
    def fusionTargetModality(self):
        return "CT" if self.seriesModality(self._fusion_anchor_uid) == "PT" else "PET"

    @Property(bool, notify=fusionDialogChanged)
    def fusionShowAllPatients(self):
        return self._fusion_show_all

    @Slot(bool)
    def setFusionShowAllPatients(self, enabled):
        self._fusion_show_all = bool(enabled)
        if self._fusion_partner_uid not in {r["seriesUid"] for r in self.fusionCandidates}:
            self._fusion_partner_uid = ""
        self._fusion_error = ""
        self.fusionDialogChanged.emit()

    def _fusion_record_item(self, record):
        from qt_dicom_viewer.core.pet_fusion import fusion_series_error
        return dict(seriesUid=record.series_instance_uid, patientName=record.patient_name,
                    patientId=record.patient_id, studyDate=record.study_date,
                    description=record.series_description or record.modality,
                    modality="PET" if record.modality.upper() == "PT" else record.modality,
                    count=record.dicom_file_count,
                    thumbnailUrl=self._thumbnails.get(record.series_instance_uid, ""),
                    error=fusion_series_error(record))

    @Property(bool, notify=fusionDialogChanged)
    def fusionCanConfirm(self):
        from qt_dicom_viewer.core.pet_fusion import fusion_series_error
        a = self._scan_series_record.get(self._fusion_anchor_uid)
        b = self._scan_series_record.get(self._fusion_partner_uid)
        return bool(a and b and {a.modality.upper(), b.modality.upper()} == {"CT", "PT"}
                    and not fusion_series_error(a) and not fusion_series_error(b))

    @_TextProperty(str, notify=_i18n_fusionIdentityWarning, notify_name='_i18n_fusionIdentityWarning', source_notify='fusionDialogChanged')
    def fusionIdentityWarning(self):
        a = self._scan_series_record.get(self._fusion_anchor_uid)
        b = self._scan_series_record.get(self._fusion_partner_uid)
        if a is None or b is None:
            return ""
        if a.patient_id and b.patient_id and (a.patient_id, a.patient_id_issuer) == (b.patient_id, b.patient_id_issuer):
            if a.study_instance_uid and a.study_instance_uid == b.study_instance_uid:
                return ""
            return _msg('text.0479', value1=a.study_date or _msg('text.0257'), value2=b.study_date or _msg('text.0257'))
        return (_msg('text.0480', value1=a.patient_name, value2=a.patient_id or _msg('text.0481'), value3=b.patient_name, value4=b.patient_id or _msg('text.0481')))

    @Property('QVariantMap', notify=sidebarItemsChanged)
    def fusionThumbnails(self):
        # Update images independently of the candidates model: a late thumbnail
        # must not recreate delegates or move the user's scroll position.
        return dict(self._thumbnails)

    @_TextProperty('QVariantList', notify=_i18n_fusionCandidates, notify_name='_i18n_fusionCandidates', source_notify='fusionDialogChanged')
    def fusionCandidates(self):
        anchor = self._scan_series_record.get(self._fusion_anchor_uid)
        if anchor is None:
            return []
        target = "CT" if anchor.modality.upper() == "PT" else "PT"
        records = [r for r in self._scan_series_record.values() if r.modality.upper() == target
                   and (self._fusion_show_all or self._same_patient(anchor, r))]
        def rank(r):
            same = self._same_patient(anchor, r)
            return (0 if same and r.study_instance_uid == anchor.study_instance_uid else 1 if same else 2,
                    0 if anchor.frame_of_reference_uid and anchor.frame_of_reference_uid == r.frame_of_reference_uid else 1,
                    r.study_date, r.series_description, r.series_instance_uid)
        items = []
        for record in sorted(records, key=rank):
            item = self._fusion_record_item(record)
            same = self._same_patient(anchor, record)
            item["relationship"] = (_msg('text.0482') if same and anchor.study_instance_uid
                                    and anchor.study_instance_uid == record.study_instance_uid else
                                    _msg('text.0483') if same else _msg('text.0484'))
            item["spatialStatus"] = (_msg('text.0485') if anchor.frame_of_reference_uid
                                     and anchor.frame_of_reference_uid == record.frame_of_reference_uid
                                     else _msg('text.0486'))
            items.append(item)
        return items

    @Slot()
    def requestFusionView(self):
        self._fusion_error = ""
        self._fusion_partner_uid = ""
        self._fusion_show_all = False
        selected = self._selected_series_uids or ([self._active_series_uid] if self._active_series_uid else [])
        self._fusion_anchor_uid = selected[0] if selected else ""
        self._fusion_dialog_open = True
        if len(selected) not in (1, 2):
            self._fusion_error = _msg('text.0487')
            self._fusion_anchor_uid = ""
        elif len(selected) == 2:
            self._fusion_partner_uid = selected[1]
            a = self._scan_series_record.get(selected[0])
            b = self._scan_series_record.get(selected[1])
            self._fusion_show_all = bool(a and b and not self._same_patient(a, b))
            self.confirmFusion(False)
        elif self.seriesModality(selected[0]) not in ("CT", "PT"):
            self._fusion_error = _msg('text.0488')
            self._fusion_anchor_uid = ""
        else:
            from qt_dicom_viewer.core.pet_fusion import fusion_series_error
            self._fusion_error = fusion_series_error(self._scan_series_record[selected[0]])
            self._fusion_partner_uid = next((item["seriesUid"] for item in self.fusionCandidates
                                             if not item["error"]), "")
        self.fusionDialogChanged.emit()

    @Slot(str)
    def selectFusionPartner(self, uid):
        if uid not in {item["seriesUid"] for item in self.fusionCandidates if not item["error"]}:
            self._fusion_error = _msg('text.0489')
            self._fusion_partner_uid = ""
            self.fusionDialogChanged.emit()
            return
        self._fusion_partner_uid = uid
        self._fusion_error = ""
        self.fusionDialogChanged.emit()

    @Slot(bool)
    def confirmFusion(self, identity_confirmed):
        from qt_dicom_viewer.core.pet_fusion import fusion_series_error
        records = [self._scan_series_record.get(uid) for uid in (self._fusion_anchor_uid, self._fusion_partner_uid)]
        if any(r is None for r in records):
            self._fusion_error = _msg('text.0490')
        elif {r.modality.upper() for r in records} != {"CT", "PT"}:
            self._fusion_error = _msg('text.0491')
        else:
            self._fusion_error = next((error for r in records if (error := fusion_series_error(r))), "")
            if not self._fusion_error and (not self.fusionIdentityWarning or identity_confirmed):
                ct = next(r for r in records if r.modality.upper() == "CT")
                pet = next(r for r in records if r.modality.upper() == "PT")
                if self._series_catalog.get_series(ct.series_instance_uid) and self._series_catalog.get_series(pet.series_instance_uid):
                    self._fusion_dialog_open = False
                    self.fusionCreateRequested.emit(ct.series_instance_uid, pet.series_instance_uid)
                else:
                    self._fusion_error = _msg('text.0492')
        self.fusionDialogChanged.emit()

    @Slot()
    def cancelFusion(self):
        self._fusion_dialog_open = False
        self._fusion_partner_uid = ""
        self.fusionDialogChanged.emit()

    @Property(str, notify=patientSearchChanged)
    def patientSearch(self):
        return self._patient_search

    @Slot(str)
    def setPatientSearch(self, value):
        if value != self._patient_search:
            self._patient_search = value
            self.patientSearchChanged.emit()
            self.sidebarItemsChanged.emit()

    @Slot(str)
    def toggleGroup(self, key):
        if key in self._collapsed_groups:
            self._collapsed_groups.remove(key)
        else:
            self._collapsed_groups.add(key)
        self.sidebarItemsChanged.emit()

    @Slot()
    def _request_thumbnails(self):
        if self._closing or self._scanning or self._thumbnail_service is None:
            return
        for series in self._scan_series_record.values():
            if series.instances:
                instance = series.instances[len(series.instances) // 2]
                self._thumbnail_service.submit(ThumbnailRequest(series.series_instance_uid, instance.path, instance.frame_index))

    @Slot(object, object)
    def _accept_thumbnail(self, request, image):
        if self._closing or image.isNull():
            return
        series = self._scan_series_record.get(request.series_uid)
        if not series or not series.instances:
            return
        representative = series.instances[len(series.instances) // 2]
        if representative.path != request.path or representative.frame_index != request.frame_index:
            return
        image_id = "thumbnail-" + request.series_uid
        self._image_provider.set_image(image_id, image)
        self._thumbnail_version += 1
        self._thumbnails[request.series_uid] = f"image://dicom/{image_id}/{self._thumbnail_version}"
        self.sidebarItemsChanged.emit()

    @Slot()
    def shutdown(self):
        self._closing = True
        self.closeImportTask()
        self._thumbnail_timer.stop()
        if self._thumbnail_service is not None:
            self._thumbnail_service.shutdown()
        if self._scan_thread is not None:
            self._scan_thread.requestInterruption()
            self._scan_thread.quit()
            self._scan_thread.wait()

    @Slot(object)
    def acceptPacsImport(self, snapshot: DicomFolderScanSnapshot):
        if self._closing:
            return
        for series in snapshot.series:
            self._removed_series_uids.discard(series.series_instance_uid)
        self.update_series_session(snapshot)
        self._update_series_record(snapshot)
        self.setPatientSearch("")
        self._collapsed_groups.clear()
        self.sidebarItemsChanged.emit()
        if snapshot.series:
            first_uid = snapshot.series[0].series_instance_uid
            self.selectSeries(first_uid)
            self.openSeriesView(first_uid, "2d")

    @_TextProperty('QVariantList', notify=_i18n_seriesItems, notify_name='_i18n_seriesItems', source_notify='seriesItemsChanged')
    def seriesItems(self):
       return [{
            "patientName": summary.patient_name,
            "seriesInstanceUid": summary.series_instance_uid,
            "dicomFileCount": summary.dicom_file_count,
            "modality": summary.modality,
            "supports4D": summary.supports_four_d,
        } for series_id,summary  in self._scan_series_record.items()]

    @Property(bool, notify=scanningChanged)
    def scanning(self) -> bool:
        return self._scanning


    @Slot(str)
    def startSeriesDrag(self, uid):
        if self._series_catalog.get_series(uid) is None:
            return
        from PySide6.QtCore import QMimeData, Qt
        from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor
        mime = QMimeData()
        mime.setData("application/x-voxenra-series", uid.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        from qt_dicom_viewer.ui.controller.appearance_controller import current_colors
        colors = current_colors()
        preview = QPixmap(48, 48)
        preview.fill(QColor(colors["selectionBackground"]))
        painter = QPainter(preview)
        painter.setPen(QColor(colors["primaryColor"]))
        painter.drawRect(3, 3, 41, 41)
        painter.drawText(preview.rect(), Qt.AlignCenter, "2D")
        painter.end()
        drag.setPixmap(preview)
        drag.exec(Qt.CopyAction)

    @Slot(str, str)
    def openSeriesView(self, active_series_uid: str, tab_type: str):
        if active_series_uid not in self._scan_series_record:
            return
        series = self._series_catalog.get_series(active_series_uid)
        if series is None:
            return
        if tab_type == "4d" and not series.supports_four_d:
            return
        if series.modality.upper() == "PT" and tab_type not in ("2d", "tag", "mpr", "3d"):
            return
        self.tabCreateRequested.emit(active_series_uid, tab_type)

    @Slot(str, result=bool)
    def openSeriesDirectory(self, series_uid: str) -> bool:
        series = self._scan_series_record.get(series_uid)
        source = series.first_file if series is not None else None
        if source is None:
            return False
        directory = source.parent
        if not directory.is_dir():
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    @Slot(str)
    def removeSeries(self, series_uid: str) -> None:
        self._remove_series([series_uid])

    @Slot()
    def removeSelectedSeries(self) -> None:
        if not self._scanning:
            self._remove_series(self._selected_series_uids)

    @Slot()
    def clearSeries(self) -> None:
        if self._scanning:
            return
        search_changed = bool(self._patient_search)
        self._patient_search = ""
        self._collapsed_groups.clear()
        if search_changed:
            self.patientSearchChanged.emit()
        self._remove_series(list(self._scan_series_record))
        if not self._scan_series_record:
            self._refresh_sidebar_model()

    def _remove_series(self, series_uids) -> None:
        removed = set(series_uids).intersection(self._scan_series_record)
        if not removed:
            return
        self._removed_series_uids.update(removed)
        self._thumbnail_timer.stop()
        for uid in removed:
            del self._scan_series_record[uid]
            if self._thumbnail_service is not None:
                self._thumbnail_service.cancel(uid)
            self._thumbnails.pop(uid, None)
            if self._image_provider is not None:
                self._image_provider.remove_image("thumbnail-" + uid)

        self._selected_series_uids = [uid for uid in self._selected_series_uids if uid not in removed]
        if self._active_series_uid in removed:
            self._active_series_uid = self._selected_series_uids[-1] if self._selected_series_uids else ""
        if self._fusion_anchor_uid in removed or self._fusion_partner_uid in removed:
            self._fusion_dialog_open = False
            self._fusion_anchor_uid = self._fusion_partner_uid = ""
            self._fusion_error = ""
        self.selectionChanged.emit()
        self.fusionDialogChanged.emit()
        self.seriesItemsChanged.emit()
        self.sidebarItemsChanged.emit()
        if self._thumbnail_service is not None and not self._scanning and self._scan_series_record:
            self._thumbnail_timer.start()
