from __future__ import annotations
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty

from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Property, QRunnable, QStandardPaths, QThreadPool, Signal, Slot

from qt_dicom_viewer.pacs.client import DicomWebClient, PacsError
from qt_dicom_viewer.pacs.transport import create_client
from qt_dicom_viewer.pacs.config import PacsConfigStore, PacsProfile
from qt_dicom_viewer.pacs.importer import PacsImportResult, import_series


class _Signals(QObject):
    finished = Signal(int, object, object)
    progress = Signal(int, float, object)


class _Job(QRunnable):
    def __init__(self, number, action, cancel):
        super().__init__()
        # The controller retains jobs through queued completion and may remove
        # a cancelled queued job with tryTake(). Avoid auto-delete/ABA races.
        self.setAutoDelete(False)
        self.number, self.action, self.cancel = number, action, cancel
        self.signals = _Signals()
        self.result = None

    def run(self):
        result, error = None, ""
        try:
            result = self.action(lambda value, message: self.signals.progress.emit(self.number, value, message))
        except (PacsError, ValueError) as exc:
            error = error_message(exc)
        except OSError:
            error = _msg('text.0496')
        except Exception:
            error = _msg('text.0497')
        if self.cancel.is_set() and isinstance(result, PacsImportResult):
            result.discard()
            result = None
        self.result = result
        self.signals.finished.emit(self.number, result, error)


class PacsController(QObject):
    _i18n_defaultName = Signal()
    _i18n_draftTestResult = Signal()
    _i18n_enabledProfiles = Signal()
    _i18n_message = Signal()
    _i18n_profiles = Signal()
    _i18n_series = Signal()
    _i18n_studies = Signal()


    stateChanged = Signal()
    profilesChanged = Signal()
    studiesChanged = Signal()
    seriesChanged = Signal()
    importStarted = Signal(object)
    imported = Signal(object)

    def __init__(self, parent=None, *, config_path=None, import_root=None, series_catalog=None, import_blocker=None):
        super().__init__(parent)
        self._series_catalog = series_catalog
        self._import_blocker = import_blocker or (lambda: "")
        config_root = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
        self._store = PacsConfigStore(Path(config_path) if config_path else config_root / "pacs.json")
        self._import_root = Path(import_root) if import_root else Path(
            QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / "pacs-imports"
        self._message, self._error = "", False
        try:
            self._profiles, self._default, self._local_enabled, self._pacs_enabled = self._store.load()
        except (ValueError, OSError) as exc:
            self._profiles, self._default, self._local_enabled, self._pacs_enabled = [], "", True, True
            self._message, self._error = error_message(exc) if isinstance(exc, ValueError) else _msg('text.0498'), True
        self._selected_profile = self._default
        self._statuses = {}
        self._test_results = {}
        self._test_target = "draft"
        self._studies, self._series, self._selected = [], [], set()
        self._study_uid = ""
        self._filters = {}
        self._study_offset, self._series_offset, self._limit = 0, 0, 50
        self._has_study_next, self._has_series_next = False, False
        self._busy, self._operation, self._progress = False, "", 0.0
        self._pool = QThreadPool(self)
        # One spare worker lets a retry proceed while a cancelled socket times out.
        # Keep the bound fixed even when the user repeatedly cancels.
        self._pool.setMaxThreadCount(2)
        self._jobs = {}
        self._job, self._cancel, self._number, self._closing = None, Event(), 0, False
        self._success = None
        self._tested_profile_id = ""
        self._tested_draft = None
        self._tested_feedback = {}

    @_TextProperty('QVariantList', notify=_i18n_profiles, notify_name='_i18n_profiles', source_notify='profilesChanged')
    def profiles(self):
        return [{**p.public_dict(), "isDefault": p.id == self._default,
                 "needsSecret": p.auth != "none" and not p.secret,
                 "status": self._statuses.get(p.id, _msg('text.0499')),
                 "testResult": self._test_results.get(p.id, {})} for p in self._profiles]

    @_TextProperty('QVariantMap', notify=_i18n_draftTestResult, notify_name='_i18n_draftTestResult', source_notify='stateChanged')
    def draftTestResult(self):
        return self._test_results.get("draft", {})

    def _test_feedback(self, state, message):
        self._tested_feedback = {"state": state, "message": message}
        self._test_results[self._test_target] = dict(self._tested_feedback)
        if self._test_target != "draft":
            self._statuses[self._test_target] = {"testing": _msg('text.0500'), "success": _msg('text.0501'),
                                                "error": _msg('text.0502'), "cancelled": _msg('text.0503')}[state]
        self.profilesChanged.emit()
        self.stateChanged.emit()

    @Slot()
    def clearDraftTest(self):
        if not self._busy:
            self._test_results.pop("draft", None)
            self._tested_draft = None
            self.stateChanged.emit()

    @_TextProperty('QVariantList', notify=_i18n_enabledProfiles, notify_name='_i18n_enabledProfiles', source_notify='profilesChanged')
    def enabledProfiles(self):
        return [row for row in self.profiles if row["enabled"]]

    @_TextProperty(str, notify=_i18n_defaultName, notify_name='_i18n_defaultName', source_notify='profilesChanged')
    def defaultName(self):
        return next((p.name for p in self._profiles if p.id == self._default), _msg('text.0504'))

    @Property(bool, notify=profilesChanged)
    def localEnabled(self):
        return self._local_enabled

    @Property(bool, notify=profilesChanged)
    def pacsEnabled(self):
        return self._pacs_enabled

    @Property(str, notify=stateChanged)
    def selectedProfileId(self):
        return self._selected_profile

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._busy

    @Property(str, notify=stateChanged)
    def operation(self):
        return self._operation

    @Property(float, notify=stateChanged)
    def progress(self):
        return self._progress

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='stateChanged')
    def message(self):
        return self._message

    @Property(bool, notify=stateChanged)
    def isError(self):
        return self._error

    @_TextProperty('QVariantList', notify=_i18n_studies, notify_name='_i18n_studies', source_notify='studiesChanged')
    def studies(self):
        return self._studies

    @_TextProperty('QVariantList', notify=_i18n_series, notify_name='_i18n_series', source_notify='seriesChanged')
    def series(self):
        return [{**row, "selected": row["uid"] in self._selected} for row in self._series]

    @Property('QVariantList', notify=stateChanged)
    def selectedSeriesUids(self):
        return sorted(self._selected)

    @Property(str, notify=stateChanged)
    def selectedStudyUid(self):
        return self._study_uid

    @Property(int, notify=stateChanged)
    def selectedCount(self):
        return len(self._selected)

    @Property(int, notify=stateChanged)
    def studyPage(self):
        return self._study_offset // self._limit + 1

    @Property(int, notify=stateChanged)
    def seriesPage(self):
        return self._series_offset // self._limit + 1

    @Property(bool, notify=stateChanged)
    def hasStudyNext(self):
        return self._has_study_next

    @Property(bool, notify=stateChanged)
    def hasSeriesNext(self):
        return self._has_series_next

    @Property('QVariantMap', notify=stateChanged)
    def filterInputs(self):
        return self._filters

    @Property(int, notify=stateChanged)
    def pageSize(self):
        return self._limit

    def _notify(self, message, error=False):
        self._message, self._error = message, error
        self.stateChanged.emit()

    def _profile(self, profile_id):
        profile = next((p for p in self._profiles if p.id == profile_id), None)
        if profile is None:
            raise ValueError(_msg('text.0505'))
        return profile

    def _commit(self, profiles, default, local=None, pacs=None):
        local = self._local_enabled if local is None else local
        pacs = self._pacs_enabled if pacs is None else pacs
        enabled_ids = [p.id for p in profiles if p.enabled]
        if default not in enabled_ids:
            default = next(iter(enabled_ids), "")
        try:
            self._store.save(profiles, default, local, pacs)
        except OSError:
            self._notify(_msg('text.0506'), True)
            return False
        self._profiles, self._default = profiles, default
        self._local_enabled, self._pacs_enabled = local, pacs
        if self._selected_profile not in enabled_ids:
            self._selected_profile = default
        self._clear_results()
        self.profilesChanged.emit()
        self._notify("")
        return True

    def _clear_results(self):
        self._studies, self._series, self._selected, self._study_uid = [], [], set(), ""
        self._study_offset = self._series_offset = 0
        self._has_study_next = self._has_series_next = False
        self.studiesChanged.emit()
        self.seriesChanged.emit()

    def _draft(self, data):
        data = dict(data)
        if data.get("id") and not data.get("secret") and not data.get("clearSecret"):
            original = self._profile(data["id"])
            if (data.get("auth"), str(data.get("url", "")).strip().rstrip("/"),
                str(data.get("username", "")).strip()) == (original.auth, original.url, original.username):
                data["secret"] = original.secret
        return PacsProfile.from_dict(data)

    @Slot("QVariantMap", result=bool)
    def saveProfile(self, data):
        if self._busy:
            return False
        try:
            profile = self._draft(data)
            if any(p.id != profile.id and p.name.casefold() == profile.name.casefold() for p in self._profiles):
                raise ValueError(_msg('text.0507'))
        except (ValueError, TypeError) as exc:
            self._notify(error_message(exc), True)
            return False
        rows = [profile if p.id == profile.id else p for p in self._profiles]
        if not any(p.id == profile.id for p in self._profiles):
            rows.append(profile)
        original = next((p for p in self._profiles if p.id == profile.id), None)
        if self._commit(rows, self._default):
            if self._connection_matches(profile, self._tested_draft):
                self._statuses[profile.id] = _msg('text.0501' if self._tested_feedback['state'] == 'success' else 'text.0502')
                self._test_results[profile.id] = dict(self._tested_feedback)
            elif not self._connection_matches(profile, original):
                self._statuses.pop(profile.id, None)
                self._test_results.pop(profile.id, None)
            self.profilesChanged.emit()
            return True
        return False

    @Slot(str)
    def deleteProfile(self, profile_id):
        if not self._busy:
            self._commit([p for p in self._profiles if p.id != profile_id], self._default)

    @Slot(str, bool)
    def setProfileEnabled(self, profile_id, enabled):
        if not self._busy:
            self._commit([replace(p, enabled=enabled) if p.id == profile_id else p for p in self._profiles], self._default)

    @Slot(str)
    def setDefault(self, profile_id):
        if not self._busy and any(p.id == profile_id and p.enabled for p in self._profiles):
            self._commit(self._profiles, profile_id)

    @Slot(bool, bool)
    def setSources(self, local, pacs):
        if self._busy:
            return
        if not local and not pacs:
            self._notify(_msg('text.0508'), True)
            self.profilesChanged.emit()
            return
        self._commit(self._profiles, self._default, local, pacs)

    @Slot(str)
    def selectProfile(self, profile_id):
        if not self._busy and profile_id != self._selected_profile and any(
                p.id == profile_id and p.enabled for p in self._profiles):
            self._selected_profile = profile_id
            self._clear_results()
            self._notify("")

    def _start(self, operation, action, success):
        if self._busy or self._closing:
            return
        self._number += 1
        self._cancel = Event()
        self._busy, self._operation, self._progress = True, operation, 0.0
        self._success = success
        self._notify({"test": _msg('text.0509'), "studies": _msg('text.0510'),
                      "series": _msg('text.0511'), "import": _msg('text.0512')}[operation])
        cancel = self._cancel
        self._job = _Job(self._number, lambda progress: action(cancel, progress), cancel)
        self._jobs[self._number] = self._job
        self._job.signals.finished.connect(self._finished)
        self._job.signals.progress.connect(self._on_progress)
        self._pool.start(self._job)

    @Slot(int, float, object)
    def _on_progress(self, number, progress, message):
        if number == self._number and not self._closing and not self._cancel.is_set():
            self._progress = progress
            self._notify(message)

    @Slot(int, object, object)
    def _finished(self, number, result, error):
        self._jobs.pop(number, None)
        if number != self._number or self._closing or self._cancel.is_set():
            if isinstance(result, PacsImportResult):
                result.discard()
            if number == self._number:
                self._busy = False
                self._job = None
                if self._operation == "test":
                    self._test_feedback("cancelled", _msg('text.0513'))
                self._notify(_msg('text.0338'))
            return
        self._busy, self._job = False, None
        if error:
            if self._operation == "test":
                self._test_feedback("error", error)
            self._notify(error, True)
        else:
            self._success(result)
        self.stateChanged.emit()

    @staticmethod
    def _connection_matches(left, right):
        return right is not None and all(getattr(left, key) == getattr(right, key)
                                         for key in ("protocol", "url", "auth", "username", "secret", "timeout",
                                                     "host", "port", "called_ae", "calling_ae", "listen_host", "listen_port"))

    def _test(self, profile):
        self._tested_draft = profile
        self._tested_profile_id = next((p.id for p in self._profiles if p == profile), "")
        def done(message):
            self._tested_draft = profile
            if self._tested_profile_id:
                self._statuses[self._tested_profile_id] = _msg('text.0501')
                self.profilesChanged.emit()
            self._test_feedback("success", message)
            self._notify(message)
        self._test_feedback("testing", _msg('text.0509'))
        self._start("test", lambda cancel, progress: create_client(profile, cancel).test_connection(), done)

    @Slot(str)
    def testProfile(self, profile_id):
        if self._busy:
            return
        self._test_target = profile_id
        self._tested_draft = None
        try:
            self._test(self._profile(profile_id))
        except ValueError as exc:
            self._test_feedback("error", error_message(exc))
            self._notify(error_message(exc), True)

    @Slot("QVariantMap")
    def testDraft(self, data):
        if self._busy:
            return
        self._test_target = "draft"
        self._tested_draft = None
        try:
            self._test(self._draft(data))
        except (ValueError, TypeError) as exc:
            self._test_feedback("error", error_message(exc))
            self._notify(error_message(exc), True)

    @Slot("QVariantMap", int)
    def queryStudies(self, filters, limit):
        if self._busy:
            return
        self._filters = dict(filters)
        self._limit = limit if limit in (20, 50, 100) else 50
        self._clear_results()
        self._query_studies(0)

    @Slot(int)
    def changeStudyPage(self, direction):
        if not self._busy and ((direction < 0 and self._study_offset > 0) or (direction > 0 and self._has_study_next)):
            self._query_studies(max(0, self._study_offset + (1 if direction > 0 else -1) * self._limit))

    def _query_studies(self, offset):
        try:
            profile = self._profile(self._selected_profile)
            if not profile.enabled or not self._pacs_enabled:
                raise ValueError(_msg('text.0514'))
        except ValueError as exc:
            self._notify(error_message(exc), True)
            return
        self._studies, self._series, self._selected, self._study_uid = [], [], set(), ""
        self._has_study_next = self._has_series_next = False
        self._series_offset = 0
        self.studiesChanged.emit()
        self.seriesChanged.emit()
        def done(rows):
            self._study_offset = offset
            self._studies = rows[:self._limit]
            self._has_study_next = len(rows) >= self._limit
            self.studiesChanged.emit()
            self._notify(_msg('text.0515', value1=len(self._studies)) if rows else _msg('text.0516'))
        self._start("studies", lambda cancel, progress: create_client(profile, cancel).studies(
            self._filters, offset, self._limit), done)

    @Slot(str)
    def selectStudy(self, study_uid):
        if self._busy or not any(row["uid"] == study_uid for row in self._studies):
            return
        self._study_uid, self._series_offset = study_uid, 0
        self._query_series(0)

    @Slot(int)
    def changeSeriesPage(self, direction):
        if not self._busy and ((direction < 0 and self._series_offset > 0) or (direction > 0 and self._has_series_next)):
            self._query_series(max(0, self._series_offset + (1 if direction > 0 else -1) * self._limit))

    def _query_series(self, offset):
        profile = self._profile(self._selected_profile)
        self._series, self._selected, self._has_series_next = [], set(), False
        self.seriesChanged.emit()
        def done(rows):
            self._series_offset = offset
            self._series = rows[:self._limit]
            self._has_series_next = len(rows) >= self._limit
            self.seriesChanged.emit()
            self._notify(_msg('text.0517', value1=len(self._series)) if rows else _msg('text.0518'))
        self._start("series", lambda cancel, progress: create_client(profile, cancel).series(
            self._study_uid, offset, self._limit), done)

    @Slot(str, bool)
    def selectSeries(self, series_uid, selected):
        if self._busy or not any(row["uid"] == series_uid for row in self._series):
            return
        self._selected.add(series_uid) if selected else self._selected.discard(series_uid)
        self.stateChanged.emit()

    @Slot(bool)
    def selectAllSeries(self, selected):
        if not self._busy:
            self._selected = {row["uid"] for row in self._series} if selected else set()
            self.stateChanged.emit()

    @Slot()
    def importSelected(self):
        if self._busy or self._closing or not self._selected or not self._pacs_enabled:
            return
        if reason := self._import_blocker():
            self._notify(reason, True)
            return
        profile = self._profile(self._selected_profile)
        rows = [row for row in self._series if row["uid"] in self._selected]
        # The app serializes catalog writers before this GUI-thread snapshot.
        # Downloading, sorting and rebuilding temporal groups stay in the worker.
        base_series = self._series_catalog.snapshot() if self._series_catalog is not None else {}
        self.importStarted.emit(tuple(row["uid"] for row in rows))
        def done(result):
            self.imported.emit(result.snapshot)
            self._notify(_msg('text.0519', value1=len(rows), value2=result.snapshot.dicom_file_count))
            self._selected.clear()
        self._start("import", lambda cancel, progress: import_series(
            create_client(profile, cancel), rows, self._import_root, progress,
            base_series=base_series), done)

    @Slot()
    def cancel(self):
        if self._busy:
            self._cancel.set()
            if self._operation == "test":
                job = self._job
                # Queued tests never need to run; retain running jobs until their
                # queued completion arrives, but detach their generation now.
                if job is not None and self._pool.tryTake(job):
                    self._jobs.pop(self._number, None)
                self._number += 1
                self._busy, self._job, self._success = False, None, None
                self._tested_draft = None
                self._test_feedback("cancelled", _msg('text.0513'))
                self._notify(_msg('text.0338'))
            else:
                self._notify(_msg('text.0520'))

    @Slot()
    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._cancel.set()
        for job in self._jobs.values():
            job.cancel.set()
        self._pool.waitForDone()
        # A worker may finish before its queued GUI callback is delivered.
        # Such a result has not been handed to the catalog and must be discarded.
        for job in self._jobs.values():
            if isinstance(job.result, PacsImportResult):
                job.result.discard()
        self._jobs.clear()
