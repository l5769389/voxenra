"""Cross-batch temporal imports and explicit sidebar restoration."""
from threading import Event

import pydicom
import pytest

from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.series_import import merge_import_snapshot
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from test_dicom_tags import qt_app, wait_until
from test_four_d import _cross_series_four_d


@pytest.mark.parametrize('expected_count', [None, 3])
def test_sequential_first_import_links_cross_series_phases(tmp_path, expected_count):
    records = _cross_series_four_d(tmp_path)
    catalog = {}
    for record in records:
        if expected_count:
            for instance in record.instances:
                ds = pydicom.dcmread(instance.path)
                ds.NumberOfTemporalPositions = expected_count
                ds.save_as(instance.path, enforce_file_format=True)
        incoming = list(DicomFolderScanner().scan_files(
            [i.path for i in record.instances], folder=tmp_path))[-1]
        merged = merge_import_snapshot(incoming, catalog)
        catalog.update({s.series_instance_uid: s for s in merged.series})
        assert merged.dicom_file_count == 2
        assert merged.existing_file_count == 0
    assert len(catalog) == 3
    assert all(s.phase_identifiers == (0, 1, 2) for s in catalog.values())
    assert all([len(p.instances) for p in s.phases] == [2, 2, 2] for s in catalog.values())


@pytest.mark.parametrize('single_catalog_record', [False, True])
def test_local_reimport_restores_only_requested_hidden_series(qt_app, tmp_path, single_catalog_record):
    records = _cross_series_four_d(tmp_path)
    panel = PanelController(series_catalog=SeriesCatalog())
    snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0,
                                       records[:1] if single_catalog_record else records)
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    panel.clearSeries()
    try:
        assert panel._start_import([str(i.path) for i in records[0].instances])
        wait_until(lambda: not panel.scanning)
        assert set(panel._scan_series_record) == {records[0].series_instance_uid}
        assert panel._scan_series_record[records[0].series_instance_uid].phase_identifiers == (0, 1, 2)
        # Explicitly importing the removed peer restores exactly that source.
        assert panel._start_import([str(i.path) for i in records[1].instances])
        wait_until(lambda: not panel.scanning)
        assert set(panel._scan_series_record) == {r.series_instance_uid for r in records[:2]}
    finally:
        panel.shutdown()


def test_local_import_keeps_concurrent_removal(qt_app, tmp_path, monkeypatch):
    records = _cross_series_four_d(tmp_path)
    panel = PanelController(series_catalog=SeriesCatalog())
    snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records)
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    entered, release = Event(), Event()
    prepare = panel._import_store.prepare

    def paused_prepare(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(panel._import_store, 'prepare', paused_prepare)
    try:
        assert panel._start_import([str(i.path) for i in records[0].instances])
        wait_until(entered.is_set)
        panel.removeSeries(records[0].series_instance_uid)
        release.set()
        wait_until(lambda: not panel.scanning)
        assert set(panel._scan_series_record) == {r.series_instance_uid for r in records[1:]}
    finally:
        release.set()
        panel.shutdown()


def test_merge_does_not_publish_unchanged_unrelated_series(tmp_path):
    from dataclasses import replace

    records = _cross_series_four_d(tmp_path)
    from qt_dicom_viewer.core.dicom_scanner import _build_series_record
    unrelated = _build_series_record([
        replace(i, series_instance_uid='unrelated', series_description='Independent')
        for i in records[0].instances])
    catalog = {r.series_instance_uid: r for r in [*records, unrelated]}
    incoming = list(DicomFolderScanner().scan_files(
        [i.path for i in records[0].instances], folder=tmp_path))[-1]
    merged = merge_import_snapshot(incoming, catalog)
    assert unrelated.series_instance_uid not in {s.series_instance_uid for s in merged.series}


def test_pacs_snapshot_incoming_metadata_does_not_restore_unrequested_peers(qt_app, tmp_path):
    records = _cross_series_four_d(tmp_path)
    panel = PanelController(series_catalog=SeriesCatalog())
    initial = DicomFolderScanSnapshot(tmp_path, 2, 2, 0, records[:1])
    panel.update_series_session(initial)
    panel._update_series_record(initial)
    incoming = list(DicomFolderScanner().scan_files(
        [i.path for i in records[0].instances], folder=tmp_path))[-1]
    merged = merge_import_snapshot(incoming, panel._series_catalog.snapshot())
    try:
        panel.acceptPacsImport(merged)
        assert set(panel._scan_series_record) == {records[0].series_instance_uid}
    finally:
        panel.shutdown()
