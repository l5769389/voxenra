"""Temporal source IDs remain unambiguous and stable across catalog growth."""
import numpy as np
import pydicom
import pytest

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.series_import import merge_import_snapshot
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.model import ImagePoint, MeasurementKind
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.controller.dicom_results_controller import capture_dicom_results
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_four_d import _cross_series_four_d, _scan_series


def scan_records(root, records):
    return list(DicomFolderScanner().scan_files(
        [i.path for r in records for i in r.instances], folder=root))[-1]


def test_mixed_numeric_phase_values_load_each_original_volume(tmp_path):
    records = _cross_series_four_d(tmp_path, description_base='Mixed')
    for record, suffix in zip(records, ('0', '0.5', '2')):
        for instance in record.instances:
            ds = pydicom.dcmread(instance.path)
            ds.SeriesDescription = 'Mixed_ph' + suffix
            ds.save_as(instance.path, enforce_file_format=True)
    records = _scan_series(tmp_path)
    manager = VolumeManager()
    for record, expected in zip(records, (10, 20, 30)):
        volume = manager.get_or_build(record, record.initial_phase_identifier)
        np.testing.assert_array_equal(volume.modality_pixels, expected)
    assert all(r.phase_identifiers == (1, 2, 3) for r in records)


@pytest.mark.parametrize('single_catalog_record', [False, True])
def test_earlier_phase_import_preserves_ids_pixels_cache_and_reimports(tmp_path, single_catalog_record):
    records = _cross_series_four_d(tmp_path, source_keyword='AcquisitionTime',
                                   source_values=('110000', '120000', '100000'))
    initial = scan_records(tmp_path, records[:2])
    catalog = {r.series_instance_uid: r for r in (initial.series[:1] if single_catalog_record else initial.series)}
    anchor_uid = records[0].series_instance_uid
    manager = VolumeManager()
    cached = manager.get_or_build(catalog[anchor_uid], 1)
    for batch in ([records[2]], [records[0]], [records[2]], records):
        merged = merge_import_snapshot(scan_records(tmp_path, batch), catalog)
        catalog.update({r.series_instance_uid: r for r in merged.series})
        current = catalog[anchor_uid]
        assert manager.get_or_build(current, 1) is cached
        for identifier, expected in ((1, 10), (2, 20), (3, 30)):
            np.testing.assert_array_equal(manager.get_or_build(current, identifier).modality_pixels, expected)
        assert all(r.phase_identifiers == (3, 1, 2) for r in catalog.values())


def test_open_four_d_roi_and_seg_keep_sources_after_earlier_phase_import(qt_app, tmp_path):
    records = _cross_series_four_d(tmp_path, source_keyword='AcquisitionTime',
                                   source_values=('110000', '120000', '100000'))
    app = AppController(DicomImageProvider(), settings_path=False,
                        pacs_config_path=tmp_path/'pacs.json', pacs_import_root=tmp_path/'downloads')
    try:
        initial = scan_records(tmp_path, records[:2])
        app.panelController.update_series_session(initial)
        uid = records[0].series_instance_uid
        app.workspaceController.createTab(uid, 'Original phases', '4d')
        tab = app.workspaceController.activeTab
        wait_until(lambda: tab.voiController._phase_ready and not tab._active_mpr_requests)
        tab.toolController.activateTool('measure')
        view = tab.activeViewport
        measure = view.measurementController
        context = view._measurement_context(1, .1, kind=MeasurementKind.FREEHAND)
        identifier = measure.paste_points([ImagePoint(.5,.5), ImagePoint(2.5,.5), ImagePoint(2.,1.5)], context)
        assert identifier
        controller = app.exportController.dicomResults
        assert controller.convertSelectedRoi()
        wait_until(lambda: not controller.busy)
        assert not controller.isError, controller.message
        merged = merge_import_snapshot(scan_records(tmp_path, records[2:]), app._series_catalog.snapshot())
        app.panelController.update_series_session(merged)
        planar, segments = capture_dicom_results(app.workspaceController, app._series_catalog)
        expected = {i.sop_instance_uid for i in records[0].instances}
        assert {i.sop_instance_uid for i in planar[0].instances} == expected
        assert {i.sop_instance_uid for i in segments[0].instances} == expected
        # Existing tab index and ROI/SEG scope remain anchored to its original sources.
        assert tab._phase_identifiers == (1,2)
        for index, expected_pixel in ((1,20), (0,10)):
            tab.setPhaseIndex(index)
            wait_until(lambda: tab._current_phase_index == index and tab.voiController._phase_ready
                       and not tab._active_mpr_requests)
            np.testing.assert_array_equal(view._modality_pixel, expected_pixel)
        wait_until(lambda: not tab.voiController.busy and bool(tab.voiController.evaluations))
        assert controller.export_to(tmp_path), controller.message
        wait_until(lambda: not controller.busy)
        assert not controller.isError, controller.message
        from pathlib import Path
        out = Path(controller.resultPath)
        seg = pydicom.dcmread(out/'SEG-001.dcm')
        seg_refs = {str(frame.DerivationImageSequence[0].SourceImageSequence[0].ReferencedSOPInstanceUID)
                    for frame in seg.PerFrameFunctionalGroupsSequence}
        assert seg_refs and seg_refs <= expected
        sr = pydicom.dcmread(out/'SR-001.dcm')
        refs = {str(ref.ReferencedSOPInstanceUID) for study in sr.CurrentRequestedProcedureEvidenceSequence
                for source in study.ReferencedSeriesSequence if str(source.SeriesInstanceUID)==uid
                for ref in source.ReferencedSOPSequence}
        assert refs == expected
        app.workspaceController.createTab(records[2].series_instance_uid, 'All phases', '4d')
        fresh = app.workspaceController.activeTab
        wait_until(lambda: fresh.voiController._phase_ready and not fresh._active_mpr_requests)
        assert fresh._phase_identifiers == (3,1,2)
        fresh.setPhaseIndex(0)
        wait_until(lambda: fresh._current_phase_index==0 and fresh.voiController._phase_ready
                   and not fresh._active_mpr_requests)
        np.testing.assert_array_equal(fresh.activeViewport._modality_pixel, 30)
    finally:
        app.shutdown()


def test_fractional_phase_insert_keeps_existing_explicit_integer_ids(tmp_path):
    records = _cross_series_four_d(tmp_path, description_base='Mixed')
    for record, suffix in zip(records, ('0', '0.5', '2')):
        for instance in record.instances:
            ds = pydicom.dcmread(instance.path)
            ds.SeriesDescription = 'Mixed_ph' + suffix
            ds.save_as(instance.path, enforce_file_format=True)
    initial = scan_records(tmp_path, [records[0], records[2]])
    catalog = {r.series_instance_uid: r for r in initial.series}
    assert all(r.phase_identifiers == (0,2) for r in catalog.values())
    merged = merge_import_snapshot(scan_records(tmp_path, records[1:2]), catalog)
    catalog.update({r.series_instance_uid: r for r in merged.series})
    manager = VolumeManager()
    for record in catalog.values():
        assert record.phase_identifiers == (0,3,2)
        for phase, expected in ((0,10),(3,20),(2,30)):
            np.testing.assert_array_equal(manager.get_or_build(record, phase).modality_pixels, expected)


def test_previously_independent_phase_groups_keep_each_anchors_identity(tmp_path):
    records = _cross_series_four_d(tmp_path, phase_count=4, source_keyword='AcquisitionTime',
                                   source_values=('110000', '120000', '090000', '100000'))
    first = scan_records(tmp_path, records[:2])
    second = scan_records(tmp_path, records[2:])
    catalog = {r.series_instance_uid: r for r in [*first.series, *second.series]}
    merged = merge_import_snapshot(scan_records(tmp_path, records[:1]), catalog)
    catalog.update({r.series_instance_uid: r for r in merged.series})
    manager = VolumeManager()
    for anchor, expected_values in ((records[0], (10,20)), (records[2], (30,40))):
        series = catalog[anchor.series_instance_uid]
        for phase, expected in enumerate(expected_values, start=1):
            np.testing.assert_array_equal(manager.get_or_build(series, phase).modality_pixels, expected)


def test_scan_worker_previews_keep_new_phase_ids_without_counting_new_files_as_existing(tmp_path):
    from qt_dicom_viewer.ui.workers.dicom_scan_worker import DicomScanWorker

    records = _cross_series_four_d(tmp_path, phase_count=4, source_keyword='AcquisitionTime',
                                   source_values=('110000', '120000', '100000', '090000'))
    initial = scan_records(tmp_path, records[:2])
    catalog = {r.series_instance_uid: r for r in initial.series}
    worker = DicomScanWorker([tmp_path], base_series=catalog)
    try:
        preview = worker._merge_snapshot(scan_records(tmp_path, records[2:3]))
        catalog.update({r.series_instance_uid: r for r in preview.series})
        uid = records[2].series_instance_uid
        assert catalog[uid].initial_phase_identifier == 3
        final = worker._merge_snapshot(scan_records(tmp_path, records[2:]))
        catalog.update({r.series_instance_uid: r for r in final.series})
        assert preview.existing_file_count == final.existing_file_count == 0
        np.testing.assert_array_equal(VolumeManager().get_or_build(catalog[uid], 3).modality_pixels, 30)
        assert catalog[uid].phase_identifiers == (4,3,1,2)
    finally:
        worker.store.cleanup()
