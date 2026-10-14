from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
import logging
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Slot, Signal, QThread

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.local_import import LocalImportStore, ImportCancelled, ImportErrorDetail
from qt_dicom_viewer.core.series_import import merge_import_snapshot

logger = logging.getLogger(__name__)


class DicomScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)
    process = Signal(object)
    status = Signal(object)
    progress = Signal(int, int, int, int)
    process_report_interval = 0.75

    def __init__(self, paths, store=None, *, base_series=None):
        super().__init__()
        self.paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
        self.store = store or LocalImportStore()
        self._base_series = dict(base_series or {})
        self._phase_reference_series = dict(self._base_series)
        self._process_pending = Event()

    def acknowledge_process(self):
        self._process_pending.clear()

    def _merge_snapshot(self, result):
        # All sorting, duplicate merging and phase linking happen off the GUI thread.
        merged = merge_import_snapshot(result, self._base_series,
                                       phase_reference_series=self._phase_reference_series)
        self._phase_reference_series.update({s.series_instance_uid: s for s in merged.series})
        return merged

    @Slot()
    def run(self):
        latest = None
        cancelled = QThread.currentThread().isInterruptionRequested
        try:
            files = self.store.prepare(self.paths, cancelled=cancelled, progress=self.status.emit)
            self.status.emit(_msg('text.0546'))
            last_progress = 0.0

            def report(processed, dicom, skipped):
                nonlocal last_progress
                now = time.monotonic()
                if now - last_progress >= 0.15 or processed == len(files):
                    last_progress = now
                    self.progress.emit(processed, len(files), dicom, skipped)

            for result in DicomFolderScanner().scan_files(
                files, folder=Path(self.paths[0]).parent, cancelled=cancelled,
                snapshot_interval=self.process_report_interval,
                can_publish=lambda: not self._process_pending.is_set(), progress=report,
            ):
                latest = self._merge_snapshot(result)
                if not self._process_pending.is_set():
                    # At most one preview waits in the GUI event queue.
                    self._process_pending.set()
                    self.process.emit(latest)
            self.finished.emit(latest)
        except ImportCancelled:
            self.finished.emit(latest)
        except ImportErrorDetail as error:
            logger.exception("Local import rejected")
            self.failed.emit(error_message(error))
        except Exception:
            logger.exception("Local import failed")
            self.failed.emit(_msg('text.0547'))
