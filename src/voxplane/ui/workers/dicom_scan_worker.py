from voxplane.i18n.messages import error_message
from voxplane.i18n import message as _msg
import logging
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Slot, Signal, QThread

from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.local_import import LocalImportStore, ImportCancelled, ImportErrorDetail
from voxplane.core.series_import import merge_import_snapshot

logger = logging.getLogger(__name__)


class DicomScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)
    process = Signal(object)
    status = Signal(object)
    progress = Signal(int, int, int, int)
    process_report_interval = 0.75

    def __init__(self, paths, store=None, *, base_series=None, excluded_recent_roots=()):
        super().__init__()
        self.paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
        self.store = store or LocalImportStore()
        self._base_series = dict(base_series or {})
        self._phase_reference_series = dict(self._base_series)
        self._process_pending = Event()
        self._excluded_recent_roots = excluded_recent_roots
        self.recent_paths = []
        self.recent_directory = ''

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
            # Resolve/probe inputs here, never on startup or the GUI thread.
            selected = dict.fromkeys(Path(path).expanduser().resolve() for path in self.paths)
            directories = {path for path in selected if path.is_dir()}
            excluded = [Path(root).resolve() for root in self._excluded_recent_roots]
            found = set()

            def image_found(path):
                source = self.store.source_for(path)
                private_roots = [*excluded, *([self.store._root] if self.store._root else [])]
                if any(source.is_relative_to(root) for root in private_roots):
                    return
                if source in selected:
                    found.add(source)
                found.update(parent for parent in source.parents if parent in directories)

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
                image_found=image_found,
            ):
                latest = self._merge_snapshot(result)
                if not self._process_pending.is_set():
                    # At most one preview waits in the GUI event queue.
                    self._process_pending.set()
                    self.process.emit(latest)
            if not cancelled():
                accepted = [path for path in selected if path in found]
                self.recent_paths = [str(path) for path in accepted]
                if accepted:
                    first = accepted[0]
                    self.recent_directory = str(first if first in directories else first.parent)
            self.finished.emit(latest)
        except ImportCancelled:
            self.finished.emit(latest)
        except ImportErrorDetail as error:
            logger.exception("Local import rejected")
            self.failed.emit(error_message(error))
        except Exception:
            logger.exception("Local import failed")
            self.failed.emit(_msg('text.0547'))
