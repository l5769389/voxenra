"""Export viewport pixels or source DICOM, anonymously by default; sources stay read-only."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from datetime import datetime
from functools import partial
from pathlib import Path
import shutil
import tempfile
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot, QRunnable, QThreadPool, QSaveFile, QIODevice
from PySide6.QtGui import QImage, QPainter
import pydicom
from shiboken6 import isValid
from qt_dicom_viewer.core.dicom_anonymizer import Anonymizer, check_pixel_identity
from PySide6.QtQuick import QQuickItem
from qt_dicom_viewer.ui.file_location import reveal_path
from qt_dicom_viewer.i18n.widgets import QFileDialog


def copy_dicom_series(series, destination, cancelled=None, progress=lambda value: None, *, anonymous=False):
    """Stage a new export directory; never overwrite or partially publish an export."""
    destination = Path(destination)
    output = destination / ("dicom-export-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8])
    files, seen, counts, groups = [], set(), {}, {}
    for record in series:
        instances = list(record.instances)
        instances.extend(instance for phase in getattr(record, "phases", ()) for instance in phase.instances)
        for instance in instances:
            source = Path(instance.path).resolve()
            if source not in seen:
                seen.add(source)
                uid = getattr(instance, "series_instance_uid", record.series_instance_uid)
                group = groups.setdefault(uid, len(groups) + 1)
                counts[group] = counts.get(group, 0) + 1
                files.append((source, group, counts[group]))
    anonymizer = Anonymizer() if anonymous else None
    staging = Path(tempfile.mkdtemp(prefix=".dicom-export-", dir=destination))
    try:
        if not files:
            raise ValueError(_msg('text.0449'))
        for index, (source, series_number, number) in enumerate(files):
            if cancelled and cancelled.is_set():
                raise InterruptedError(_msg('text.0450'))
            folder = staging / f"series-{series_number:02d}"
            folder.mkdir(exist_ok=True)
            target = folder / f"{number:06d}.dcm"
            if anonymizer:
                dataset = pydicom.dcmread(source)
                anonymizer.apply(dataset)
                dataset.save_as(target, enforce_file_format=True)
            else:
                shutil.copyfile(source, target)
            progress((index + 1) / len(files))
        if cancelled and cancelled.is_set():
            raise InterruptedError(_msg('text.0450'))
        if output.exists():
            raise FileExistsError(_msg('text.0451'))
        staging.rename(output)
        return output, len(files)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


class _ExportSignals(QObject):
    finished = Signal(object, bool, str)
    progress = Signal(float)


class _CopyJob(QRunnable):
    def __init__(self, series, destination, cancel, anonymous):
        super().__init__()
        self.series, self.destination, self.cancel = series, destination, cancel
        self.anonymous = anonymous
        self.signals = _ExportSignals()

    def run(self):
        result_path = ""
        try:
            path, count = copy_dicom_series(self.series, self.destination, self.cancel, self.signals.progress.emit, anonymous=self.anonymous)
            message, error = _msg('text.0452', value1=count), False
            result_path = str(path.resolve())
        except InterruptedError:
            message, error = _msg('text.0450'), False
        except (OSError, ValueError) as exc:
            message, error = (error_message(exc) if error_message(exc).startswith(_msg('text.0141')) else _msg('text.0453')), True
        except Exception:
            message, error = _msg('text.0453'), True
        self.signals.finished.emit(message, error, result_path)


class _PixelCheckJob(QRunnable):
    """Header checks must not block the GUI when exporting a large volume."""
    def __init__(self, series, cancel):
        super().__init__()
        self.series, self.cancel = series, cancel
        self.signals = _ExportSignals()

    def run(self):
        try:
            paths = set()
            for record in self.series:
                groups = (record, *getattr(record, "phases", ()))
                paths.update(Path(i.path) for group in groups for i in group.instances)
            if not paths:
                raise ValueError(_msg('text.0454'))
            for path in paths:
                if self.cancel.is_set():
                    self.signals.finished.emit(_msg('text.0450'), False, "")
                    return
                check_pixel_identity(pydicom.dcmread(path, stop_before_pixels=True))
            self.signals.finished.emit("", False, "")
        except Exception as exc:
            self.signals.finished.emit(error_message(exc) if error_message(exc).startswith(_msg('text.0141'))
                else _msg('text.0455'), True, "")


class ExportController(QObject):
    _i18n_message = Signal()
    changed = Signal()

    def __init__(self, workspace, catalog, parent=None):
        super().__init__(parent)
        self.workspace, self.catalog = workspace, catalog
        self._busy, self._error, self._message, self._progress = False, False, "", 0.0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._cancel = Event()
        self._job = self._grab = None
        self._png_path = ""
        self._result_path = ""
        self._grab_callback = None
        self._grab_id = None
        self._png_context = None
        self._anonymous_item = None
        self._png_anonymous = True
        self._png_revision = None
        from .measurement_report_controller import MeasurementReportController
        self._measurement_report = MeasurementReportController(workspace, catalog, self)
        from .dicom_results_controller import DicomResultsController
        self._dicom_results = DicomResultsController(workspace,catalog,self)
        self._observed_view = None
        for name in ("activeTabChanged", "activeViewportChanged"):
            signal = getattr(workspace, name, None)
            if signal is not None:
                signal.connect(self._watch_active_view)
        signal = getattr(workspace, "loadingStatesChanged", None)
        if signal is not None:
            signal.connect(self.changed)
        self._watch_active_view()

    @Slot()
    def _watch_active_view(self):
        previous = self._observed_view
        if previous is not None and isValid(previous):
            for name in ("loadStateChanged", "exportReadinessChanged"):
                signal = getattr(previous, name, None)
                if signal is not None:
                    signal.disconnect(self.changed)
        self._observed_view = getattr(self.workspace, "activeViewport", None)
        if self._observed_view is not None:
            for name in ("loadStateChanged", "exportReadinessChanged"):
                signal = getattr(self._observed_view, name, None)
                if signal is not None:
                    signal.connect(self.changed)
        self.changed.emit()

    def _png_ready_to_capture(self):
        opening = getattr(self.workspace, "activeLoadState", None)
        if opening is not None and opening.status != "ready":
            return False
        viewport = self.workspace.activeViewport
        return bool(viewport is not None and isValid(viewport)
                    and getattr(viewport, "loadState", "ready") == "ready"
                    and getattr(viewport, "exportReady", True))

    @Property(bool, notify=changed)
    def canExportPng(self):
        return not self._busy and self._png_ready_to_capture()

    @Property(QObject, constant=True)
    def dicomResults(self):
        return self._dicom_results

    @Property(QObject, constant=True)
    def measurementReport(self):
        return self._measurement_report

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(bool, notify=changed)
    def isError(self): return self._error

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='changed')
    def message(self): return self._message

    @Property(str, notify=changed)
    def resultPath(self): return self._result_path

    @Slot(result=bool)
    def openResultLocation(self):
        if reveal_path(self._result_path):
            return True
        self._message, self._error = _msg('text.0394'), True
        self.changed.emit()
        return False

    @Property(float, notify=changed)
    def progress(self): return self._progress

    def _start(self, message):
        self._busy, self._error, self._message, self._progress = True, False, message, 0.0
        self._result_path = ""
        self.changed.emit()

    @Slot(object, bool, str)
    def _finish(self, message, error=False, path=""):
        self._busy, self._message, self._error = False, message, error
        self._result_path = path if not error else ""
        self._restore_capture()
        if self._grab is not None:
            self._grab.ready.disconnect(self._grab_callback)
        self._grab_id = self._grab_callback = None
        self._grab = self._job = None
        self._png_context = None
        self.changed.emit()

    @Slot(float)
    def _set_progress(self, progress):
        self._progress = progress
        self.changed.emit()

    def current_series(self):
        tab = self.workspace.activeTab
        if not tab or self.workspace.activeTabType in ("tag", "settings", "pacs", "manual"):
            return []
        # A fusion workspace exports both source series in separate directories.
        return [record for meta in tab.tab_config.series_metas
                if (record := self.catalog.get_series(meta.series_uid)) is not None]

    @Slot()
    @Slot(bool)
    def exportDicom(self, anonymous=True):
        if self._busy:
            return
        series = self.current_series()
        if not series:
            self._finish(_msg('text.0456'), True)
            return
        folder = QFileDialog.getExistingDirectory(None, _msg('text.0457'))
        if not folder:
            self._finish(_msg('text.0458'))
            return
        self.export_dicom_to(series, folder, anonymous=anonymous)

    def export_dicom_to(self, series, folder, *, anonymous=True):
        if self._busy:
            return
        self._cancel = Event()
        self._start(_msg('text.0459'))
        self._job = _CopyJob(tuple(series), folder, self._cancel, anonymous)
        self._job.signals.finished.connect(self._finish)
        self._job.signals.progress.connect(self._set_progress)
        self._pool.start(self._job)

    @Slot(QObject, float)
    @Slot(QObject, float, bool)
    def exportPng(self, item, pixel_ratio=1.0, anonymous=True):
        if self._busy:
            return
        viewport = self.workspace.activeViewport
        if not self._png_ready_to_capture():
            self._finish(_msg('text.0460'), True)
            return
        path, _ = QFileDialog.getSaveFileName(None, _msg('text.0461'), "viewport.png", _msg('text.0462'))
        if not path:
            self._finish(_msg('text.0458'))
            return
        if not Path(path).suffix:
            path += ".png"
        self._start(_msg('text.0463'))
        self._cancel = Event()
        self._png_anonymous = anonymous
        self._png_context = (viewport, item, pixel_ratio, path)
        self._png_revision = getattr(viewport, "exportRevision", None)
        if anonymous:
            self._job = _PixelCheckJob(tuple(self.current_series()), self._cancel)
            self._job.signals.finished.connect(self._pixel_check_finished)
            self._pool.start(self._job)
        else:
            self._capture_png()

    @Slot(object, bool, str)
    def _pixel_check_finished(self, message, error, _path=""):
        self._job = None
        if message or self._cancel.is_set():
            self._finish(message or _msg('text.0450'), error)
        else:
            self._capture_png()

    def _capture_png(self):
        viewport, item, _pixel_ratio, path = self._png_context
        try:
            if (not isValid(viewport) or self.workspace.activeViewport is not viewport
                    or not self._png_ready_to_capture()
                    or getattr(viewport, "exportRevision", None) != self._png_revision):
                raise ValueError(_msg('text.0464'))
            if viewport.viewportType == "volume":
                self._save_png(viewport.snapshot_image(), path)
            elif isinstance(item, QQuickItem) and isValid(item) and item.isVisible() and item.width() > 0 and item.height() > 0:
                # Qt captures at the window's native DPR. Do not multiply the
                # target size by DPR again or reparent its PySide window wrapper.
                if self._png_anonymous:
                    if item.metaObject().indexOfProperty("anonymousExport") < 0:
                        raise ValueError(_msg('text.0465'))
                    self._anonymous_item = (item, item.property("anonymousExport"))
                    item.setProperty("anonymousExport", True)
                self._grab = item.grabToImage()
                if self._grab is None:
                    raise ValueError(_msg('text.0466'))
                self._png_path = path
                self._grab_id = uuid4().hex
                self._grab_callback = partial(self._png_ready, self._grab_id)
                self._grab.ready.connect(self._grab_callback)
            else:
                raise ValueError(_msg('text.0467'))
        except (OSError, ValueError, RuntimeError) as exc:
            self._finish(_msg('text.0468', value1=exc), True)

    def _png_ready(self, grab_id):
        if self._grab is not None and grab_id == self._grab_id:
            if (self._png_context is None
                    or self.workspace.activeViewport is not self._png_context[0]
                    or not self._png_ready_to_capture()
                    or getattr(self._png_context[0], "exportRevision", None) != self._png_revision):
                self._finish(_msg('text.0464'), True)
                return
            image = self._grab.image()
            self._restore_capture()
            self._save_png(image, self._png_path)

    def _restore_capture(self):
        if self._anonymous_item is not None:
            item, previous = self._anonymous_item
            self._anonymous_item = None
            if isValid(item):
                item.setProperty("anonymousExport", previous)

    def _save_png(self, image, path):
        if self._png_anonymous and not image.isNull():
            # Repaint into a fresh image to exclude any inherited PNG text metadata.
            clean = QImage(image.size(), QImage.Format_ARGB32)
            clean.fill(0)
            painter = QPainter(clean)
            # An explicit target rectangle preserves physical pixels even when
            # grabToImage returns a Retina/HiDPI image with DPR greater than 1.
            painter.drawImage(clean.rect(), image)
            painter.end()
            image = clean
        output = QSaveFile(str(path))
        if image.isNull() or not output.open(QIODevice.WriteOnly):
            self._finish(_msg('text.0469'), True)
            return
        if not image.save(output, "PNG") or not output.commit():
            output.cancelWriting()
            self._finish(_msg('text.0470'), True)
            return
        self._finish(_msg('text.0471'), path=str(Path(path).resolve()))

    @Slot()
    def cancel(self):
        if self._job:
            self._cancel.set()
        elif self._grab:
            self._finish(_msg('text.0450'))

    def shutdown(self):
        self._dicom_results.shutdown()
        self._measurement_report.shutdown()
        self._restore_capture()
        self._cancel.set()
        self._pool.waitForDone()
