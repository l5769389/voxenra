from __future__ import annotations
from qt_dicom_viewer.i18n import message as _msg

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.series_import import merge_import_snapshot
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from .client import DicomWebClient, PacsError, check_cancel
if TYPE_CHECKING:
    from .dimse_client import DimseClient


@dataclass
class PacsImportResult:
    folder: Path
    snapshot: DicomFolderScanSnapshot

    def discard(self):
        shutil.rmtree(self.folder, ignore_errors=True)


def import_series(client: DicomWebClient | DimseClient, selections: list[dict], root: Path, progress, *, base_series=None) -> PacsImportResult:
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="import-", dir=root))
    try:
        if client.profile.protocol == 'dimse':
            count = client.retrieve_series(selections, folder, progress)
        else:
            requests = []
            for series in selections:
                check_cancel(client.cancel)
                progress(0, _msg('text.0334'))
                instances = client.instance_uids(series["studyUid"], series["uid"])
                expected = str(series.get("instances", ""))
                if expected.isdigit() and int(expected) != len(instances):
                    raise PacsError(_msg('text.0335'))
                requests.extend((series["studyUid"], series["uid"], sop) for sop in instances)
            for index, (study, series, sop) in enumerate(requests):
                client.download_instance(study, series, sop, folder / f"{index:06d}.dcm")
                progress((index + 1) / len(requests), _msg('text.0336', value1=index + 1, value2=len(requests)))
            count = len(requests)
        snapshot = None
        for snapshot in DicomFolderScanner().scan(folder):
            check_cancel(client.cancel)
        if snapshot is None or snapshot.dicom_file_count != count or snapshot.skipped_file_count:
            raise PacsError(_msg('text.0337'))
        check_cancel(client.cancel)
        snapshot = merge_import_snapshot(snapshot, base_series or {})
        check_cancel(client.cancel)
        return PacsImportResult(folder, snapshot)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
