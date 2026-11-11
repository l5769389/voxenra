"""Keep distinct files with reused dataset UIDs and distinct file-meta UIDs."""
from pathlib import Path
import shutil

import pydicom
import pytest

from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.local_import import LocalImportStore
from voxplane.core.workspace_document import source_manifest, load_referenced_series
from voxplane.core.workspace_state import dumps, loads
from voxplane.ui.workers.dicom_scan_worker import DicomScanWorker
from voxplane.ui.controller.tab.tag_controller import TagController
from voxplane.service.tag_read_service import TagReadService
from test_dicom_tags import qt_app, wait_until
from test_local_import import make_series


def conflicting_files(tmp_path):
    series = make_series(tmp_path, 3)
    paths = [i.path for i in series.instances]
    shared_uid = '1.2.826.0.1.3680043.10.999.9999'
    for index, path in enumerate(paths):
        ds = pydicom.dcmread(path)
        ds.ImagePositionPatient = [0, 0, float(index)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        pixels = ds.pixel_array.copy()
        pixels[:] = index
        ds.PixelData = pixels.tobytes()
        source_uid = ds.file_meta.MediaStorageSOPInstanceUID
        ds.SOPInstanceUID = shared_uid
        # Preserve the inconsistent source header, as in the reported files.
        ds.save_as(path, enforce_file_format=False)
        header = pydicom.dcmread(path, stop_before_pixels=True)
        assert header.file_meta.MediaStorageSOPInstanceUID == source_uid
        assert header.SOPInstanceUID == shared_uid
    return paths, shared_uid


def scan(paths, root):
    return list(DicomFolderScanner().scan_files(paths, folder=root, can_publish=lambda: False))[-1]


def test_distinct_file_meta_uids_survive_and_exact_copies_are_skipped(tmp_path):
    paths, shared_uid = conflicting_files(tmp_path)
    before = {p: p.read_bytes() for p in paths}
    copy = tmp_path / 'copy.dcm'
    shutil.copy2(paths[0], copy)
    result = scan([*paths, copy], tmp_path)
    assert (result.total_file_count, result.dicom_file_count, result.skipped_file_count) == (4, 3, 1)
    assert len(result.series) == 1
    instances = result.series[0].instances
    assert len(instances) == len({i.frame_identity for i in instances}) == 3
    assert {i.sop_instance_uid for i in instances} == {shared_uid}
    assert len({i.media_storage_sop_instance_uid for i in instances}) == 3
    assert all(p.read_bytes() == before[p] for p in paths)


def test_incremental_merge_and_reimport_keep_all_colliding_instances(qt_app, tmp_path):
    paths, _ = conflicting_files(tmp_path)
    first, rest = scan(paths[:1], tmp_path), scan(paths[1:], tmp_path)
    store = LocalImportStore(tmp_path / 'cache')
    try:
        worker = DicomScanWorker(paths[1:], store, base_series={first.series[0].series_instance_uid: first.series[0]})
        merged = worker._merge_snapshot(rest)
        assert len(merged.series[0].instances) == 3
        worker = DicomScanWorker(paths, store, base_series={merged.series[0].series_instance_uid: merged.series[0]})
        repeated = worker._merge_snapshot(scan(paths, tmp_path))
        assert len(repeated.series[0].instances) == 3
    finally:
        store.cleanup()


def test_tag_pages_preserve_colliding_source_objects(qt_app, tmp_path):
    paths, shared_uid = conflicting_files(tmp_path)
    series = scan(paths, tmp_path).series[0]
    service = TagReadService()
    controller = TagController('uid-collision', series, service)
    try:
        assert controller.pageCount == 3
        controller.start()
        wait_until(lambda: not controller.loading)
        for page, instance in enumerate(series.instances, 1):
            controller.setPage(page)
            wait_until(lambda: not controller.loading)
            assert not controller.errorMessage
            assert controller.filePath == str(instance.path)
            assert controller.sopInstanceUid == shared_uid
    finally:
        controller.dispose()
        service.shutdown()


@pytest.mark.parametrize('legacy', [False, True])
def test_workspace_restores_every_colliding_source_without_modification(tmp_path, legacy):
    paths, _ = conflicting_files(tmp_path)
    before = {p: p.read_bytes() for p in paths}
    series = scan(paths, tmp_path).series[0]
    store = LocalImportStore(tmp_path / 'cache')
    target = tmp_path / 'review.voxworkspace'
    try:
        manifest = source_manifest(series, store, target)
        assert len(manifest['instances']) == len(manifest['sources']) == 3
        assert all('media_storage_sop_instance_uid' in sig for sig in manifest['instances'])
        if legacy:
            for signature in manifest['instances']:
                signature.pop('media_storage_sop_instance_uid')
        document = loads(dumps({'series': [manifest]}))
        restored, missing = load_referenced_series(document, target, store)
        assert missing == []
        assert restored.dicom_file_count == 3
        assert [i.frame_identity for i in restored.series[0].instances] == [i.frame_identity for i in series.instances]
        assert all(p.read_bytes() == before[p] for p in paths)
    finally:
        store.cleanup()


def test_legacy_workspace_does_not_guess_between_ambiguous_sources(tmp_path):
    paths, _ = conflicting_files(tmp_path)
    for path in paths:
        dataset = pydicom.dcmread(path)
        dataset.ImagePositionPatient = [0, 0, 0]
        dataset.save_as(path, enforce_file_format=False)
    series = scan(paths, tmp_path).series[0]
    store = LocalImportStore(tmp_path / 'cache')
    target = tmp_path / 'old-review.voxworkspace'
    try:
        manifest = source_manifest(series, store, target)
        for signature in manifest['instances']:
            signature.pop('media_storage_sop_instance_uid')
        restored, missing = load_referenced_series({'series': [manifest]}, target, store)
        assert missing == [series.series_instance_uid]
        assert restored.series == []
    finally:
        store.cleanup()
