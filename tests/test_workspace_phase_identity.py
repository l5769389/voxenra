"""Workspace round trips preserve source identities after earlier phases are appended."""
from dataclasses import replace

import pytest

from qt_dicom_viewer.core.workspace_document import source_manifest, read_document, FORMAT, VERSION
from qt_dicom_viewer.core.workspace_state import dumps
from qt_dicom_viewer.core.local_import import LocalImportStore
from qt_dicom_viewer.model import DicomFolderScanSnapshot, ImagePoint, MeasurementKind
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.controller.dicom_results_controller import capture_dicom_results
from test_four_d import _cross_series_four_d
from test_dicom_tags import qt_app, wait_until


def test_workspace_preserves_phase_sources_and_existing_tab_subset(qt_app, tmp_path):
    records = _cross_series_four_d(tmp_path / 'input', source_keyword='AcquisitionTime',
                                   source_values=('100000', '110000', '120000'))
    # This is the state when the two later acquisitions were imported first.
    phases = tuple(replace(p, phase_identifier=i) for i, p in enumerate(records[0].phases[1:], 1))
    initial = [replace(r, phases=phases) for r in records[1:]]
    app = AppController(DicomImageProvider(), settings_path=False, pacs_config_path=tmp_path/'pacs.json')
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 4, 4, 0, initial)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        app.workspaceController.createTab(initial[0].series_instance_uid, 'Existing two phases', '4d')
        tab = app.workspaceController.activeTab
        wait_until(lambda: tab.voiController._phase_ready and not tab._active_mpr_requests)
        tab.toolController.activateTool('measure')
        view = tab.activeViewport
        measure = view.measurementController
        identifier = measure.paste_points([ImagePoint(.5,.5), ImagePoint(2.5,.5), ImagePoint(2,1.5)],
            view._measurement_context(1, .1, kind=MeasurementKind.FREEHAND))
        exchange = app.exportController.dicomResults
        assert exchange.convertSelectedRoi(), exchange.message
        wait_until(lambda: not exchange.busy)
        assert not exchange.isError, exchange.message
        # Adding the earlier source keeps the two existing identifiers intact.
        remapped = tuple(replace(p, phase_identifier=i) for i, p in zip((3,1,2), records[0].phases))
        current = [replace(r, phases=remapped) for r in records]
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, current)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        expected_uid = initial[0].series_instance_uid
        before = capture_dicom_results(app.workspaceController, app._series_catalog)
        assert {i.series_instance_uid for i in before[0][0].instances} == {expected_uid}
        path = tmp_path/'temporal.voxworkspace'
        document = app.workspaceDocumentController
        assert document.save_to(path)
        wait_until(lambda: not document.busy)
        assert not document.isError, document.message
        assert document.restore_from(path)
        wait_until(lambda: not document.busy, timeout=20000)
        assert not document.isError, document.message
        restored = app.workspaceController.activeTab
        wait_until(lambda: restored.voiController._phase_ready and not restored.voiController.busy
                   and not restored._active_mpr_requests)
        assert restored._phase_identifiers == (1,2)
        assert restored._current_phase_index == 0
        assert app._series_catalog.get_series(expected_uid).phase_identifiers == (3,1,2)
        planar, segments = capture_dicom_results(app.workspaceController, app._series_catalog)
        assert planar[0].measurement.measurement_id == identifier
        assert {i.series_instance_uid for i in planar[0].instances} == {expected_uid}
        assert {i.series_instance_uid for i in segments[0].instances} == {expected_uid}
        assert restored.voiController.records[0]['phase'] == 0
        assert restored.voiController.records[0]['mask'].any()
        assert restored.activeViewport._modality_pixel.mean() == pytest.approx(20)
        restored.setPhaseIndex(1)
        wait_until(lambda: restored._current_phase_index == 1 and restored.voiController._phase_ready
                   and not restored._active_mpr_requests)
        assert restored.activeViewport._modality_pixel.mean() == pytest.approx(30)
    finally:
        app.shutdown()


@pytest.mark.parametrize('bad', ['duplicate_id', 'duplicate_frame', 'out_of_range', 'bool_index'])
def test_workspace_rejects_ambiguous_phase_manifest(tmp_path, bad):
    records = _cross_series_four_d(tmp_path/'input')
    store = LocalImportStore()
    try:
        record = source_manifest(records[0], store, tmp_path/'invalid.voxworkspace')
        # Explicit source indexes, independent of the scanner's phase numbers.
        indexes = {i.frame_identity: n for n, i in enumerate(
            {i.frame_identity:i for g in (records[0], *records[0].phases) for i in g.instances}.values())}
        record['phases'] = [{'identifier':p.phase_identifier,
                             'instances':[indexes[i.frame_identity] for i in p.instances]}
                            for p in records[0].phases]
        if bad == 'duplicate_id': record['phases'][1]['identifier'] = record['phases'][0]['identifier']
        elif bad == 'duplicate_frame': record['phases'][1]['instances'] = list(record['phases'][0]['instances'])
        elif bad == 'out_of_range': record['phases'][0]['instances'][0] = len(record['instances'])
        else: record['phases'][0]['instances'][0] = True
        path = tmp_path/'invalid.voxworkspace'
        path.write_bytes(dumps({'format':FORMAT, 'version':VERSION, 'series':[record], 'tabs':[]}))
        with pytest.raises(ValueError): read_document(path)
    finally:
        store.cleanup()
