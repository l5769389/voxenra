from dataclasses import replace
import json
import zipfile

import numpy as np
import pytest

from qt_dicom_viewer.core.workspace_state import dumps, loads, atomic_write
from qt_dicom_viewer.core.workspace_document import FORMAT, VERSION, source_manifest, read_document, load_referenced_series
from qt_dicom_viewer.core.local_import import LocalImportStore
from qt_dicom_viewer.model import DicomFolderScanSnapshot, MeasurementKind, ImagePoint
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import phantom_series
from test_measurement_controller import _create_length, _position, _drag, _context


def test_codec_data_only_roundtrip_and_rejects_bad_masks(tmp_path):
    mask = np.arange(120).reshape(4, 5, 6) % 3 == 0
    source = {"mask": mask, "matrix": np.eye(4), "tuple": (1, 2.5, "中文")}
    data = loads(dumps(source))
    np.testing.assert_equal(data["mask"], mask)
    np.testing.assert_equal(data["matrix"], np.eye(4))
    assert data["tuple"] == source["tuple"]
    with pytest.raises(ValueError): loads(b'{"$type":"__import__","fields":{}}')
    with pytest.raises(ValueError): loads(b'{"$mask":"bad", "shape":[1,2,3]}')
    dest = tmp_path / "test.voxworkspace"
    atomic_write(dest, dumps(source))
    assert dest.read_bytes() == dumps(source)


def populated_app(tmp_path, *, settings_path=False):
    record = phantom_series(tmp_path, 1, "PRIVATE-ID", "1.2.3.1", "20260903")
    app = AppController(DicomImageProvider(), settings_path=settings_path)
    snapshot = DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [record])
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    app.workspaceController.createTab(record.series_instance_uid, "CT", "2d")
    wait_until(lambda: app.workspaceController.activeViewport.loadState == "ready")
    return app, record


def draw_length(view):
    controller = view._measure_controller
    context = view._measurement_context(3, 2, kind=MeasurementKind.LENGTH)
    controller.begin(_position(0, 0), context)
    controller.update(_drag(_position(0, 0), _position(10, 0)))
    controller.end(_position(10, 0))
    return next(iter(controller._measurements))


def test_save_restore_view_and_measurements(qt_app, tmp_path):
    app, record = populated_app(tmp_path)
    path = tmp_path / "session.voxworkspace"
    try:
        view = app.workspaceController.activeViewport
        view._state = replace(view._state, zoom=2.0, pan_x=12.5, rotation_degrees=90.0)
        mid = draw_length(view)
        view._measure_controller._label_positions[mid] = ImagePoint(21, 13)
        app.workspaceController.activeTab.historyController.capture()
        manager = app.workspaceDocumentController
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert read_document(path)["tabs"][0]["views"]
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        restored = app.workspaceController.activeViewport
        assert restored is not view
        assert restored._state.zoom == 2.0
        assert restored._state.pan_x == 12.5
        assert restored._state.rotation_degrees == 90.0
        assert restored._measure_controller._measurements[mid].length_mm == 8
        assert restored._measure_controller._label_positions[mid] == ImagePoint(21, 13)
        assert not app.workspaceController.activeTab.historyController.canUndo
    finally:
        app.shutdown()


def test_history_commit_edit_undo_redo_and_draft_cancel(qt_app, tmp_path):
    app, record = populated_app(tmp_path)
    try:
        tab = app.workspaceController.activeTab
        controller, history = tab.activeViewport._measure_controller, tab.historyController
        mid = draw_length(tab.activeViewport)
        history.capture()
        assert history.canUndo
        controller.begin(_position(10, 0), tab.activeViewport._measurement_context(3, 2, kind=MeasurementKind.LENGTH))
        controller.update(_drag(_position(10, 0), _position(15, 0)))
        history.capture()
        assert len(history._undo) == 1
        controller.end(_position(15, 0))
        history.capture()
        assert controller._measurements[mid].length_mm == 12
        history.undo()
        assert controller._measurements[mid].length_mm == 8
        history.undo()
        assert not controller._measurements
        history.redo()
        history.redo()
        assert controller._measurements[mid].length_mm == 12
    finally:
        app.shutdown()


def test_archive_manifest_survives_cleanup_and_relocation(qt_app, tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    phantom_series(original, 1, "PRIVATE", "1.2.3.1", "20260903")
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for p in original.iterdir(): z.write(p, p.name)
    store = LocalImportStore()
    from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
    try:
        files = store.prepare([archive])
        snapshots = list(DicomFolderScanner().scan_files(files, folder=tmp_path))
        document = {"format": FORMAT, "version": VERSION, "tabs": [],
                    "series": [source_manifest(s, store, tmp_path / "save.voxworkspace") for s in snapshots[-1].series]}
        assert document["series"][0]["sources"][0]["path"] == str(archive)
    finally: store.cleanup()
    new_path = tmp_path / "moved.zip"
    archive.rename(new_path)
    fresh = LocalImportStore()
    try:
        snapshot, missing = load_referenced_series(document, tmp_path / "save.voxworkspace", fresh)
        assert missing
        snapshot, missing = load_referenced_series(document, tmp_path / "save.voxworkspace", fresh, extra_paths=[new_path])
        assert missing == []
        assert len(snapshot.series[0].instances) == 3
    finally: fresh.cleanup()


def test_workspace_replacement_does_not_resurrect_previous_archive_instances(qt_app, tmp_path):
    from PySide6.QtCore import QUrl

    original = tmp_path / 'original'
    original.mkdir()
    record = phantom_series(original, 1, 'PRIVATE', '1.2.3.1', '20260903')
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as out:
        for instance in record.instances:
            out.write(instance.path, instance.path.name)
    empty_path = tmp_path / 'empty.voxworkspace'
    saved_path = tmp_path / 'replacement.voxworkspace'
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        manager, panel = app.workspaceDocumentController, app.panelController
        assert manager.save_to(empty_path)
        wait_until(lambda: not manager.busy)
        assert panel.importUrls([QUrl.fromLocalFile(str(archive))])
        wait_until(lambda: not panel.scanning)
        assert not panel.importError, panel.statusMessage
        archived_record = app._series_catalog.get_series(record.series_instance_uid)
        assert archived_record.dicom_file_count == 3
        app.workspaceController.createTab(record.series_instance_uid, 'CT', '2d')
        wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
        assert manager.restore_from(empty_path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert not app.workspaceController._tab_dict
        assert not panel.hasSeries
        assert not app._series_catalog.snapshot()
        assert panel.importUrls([QUrl.fromLocalFile(str(record.first_file))])
        wait_until(lambda: not panel.scanning)
        replacement = app._series_catalog.get_series(record.series_instance_uid)
        assert replacement.dicom_file_count == 1
        assert replacement.instances[0].path == record.first_file
        assert manager.save_to(saved_path)
        wait_until(lambda: not manager.busy)
        saved = read_document(saved_path)['series'][0]
        assert len(saved['instances']) == 1
        assert [source['path'] for source in saved['sources']] == [str(record.first_file)]
    finally:
        app.shutdown()
    assert archive.is_file()
    assert all(not instance.path.exists() for instance in archived_record.instances)
    fresh = AppController(DicomImageProvider(), settings_path=False)
    try:
        manager = fresh.workspaceDocumentController
        assert manager.restore_from(saved_path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError and not manager.hasMissingSources, manager.message
        assert fresh._series_catalog.get_series(record.series_instance_uid).dicom_file_count == 1
    finally:
        fresh.shutdown()


@pytest.mark.parametrize('archived', [False, True])
def test_open_resave_restart_preserves_original_sources(qt_app, tmp_path, archived):
    """Exercise the controller's provenance handoff, not just the manifest codec."""
    from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
    original = tmp_path / 'dicom'
    original.mkdir()
    phantom_series(original, 1, 'PRIVATE', '1.2.3.1', '20260903')
    source = original
    if archived:
        source = tmp_path / 'dicom.zip'
        with zipfile.ZipFile(source, 'w') as archive:
            for path in original.iterdir():
                archive.write(path, path.name)
    path = tmp_path / 'session.voxworkspace'
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        store = app.panelController._import_store
        files = store.prepare([source])
        snapshot = list(DicomFolderScanner().scan_files(files, folder=tmp_path))[-1]
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        app.workspaceController.createTab(snapshot.series[0].series_instance_uid, 'CT', '2d')
        wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
        manager = app.workspaceDocumentController
        manager._autosave.stop()
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        first_sources = read_document(path)['series']
        for _ in range(2):
            assert manager.restore_from(path)
            wait_until(lambda: not manager.busy, timeout=20000)
            assert not manager.isError, manager.message
            assert manager.save_to(path)
            wait_until(lambda: not manager.busy)
            assert not manager.isError, manager.message
            assert read_document(path)['series'] == first_sources
    finally:
        app.shutdown()
    # All session extracts have now been deleted, as on a real application exit.
    fresh = AppController(DicomImageProvider(), settings_path=False)
    try:
        manager = fresh.workspaceDocumentController
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError and not manager.hasMissingSources, manager.message
        assert fresh.workspaceController.activeLoadState.status == 'ready'
        assert len(fresh.panelController._scan_series_record) == 1
    finally:
        fresh.shutdown()


@pytest.mark.parametrize('kind', ['mpr', 'montage', '3d', 'tag', 'settings'])
def test_all_ct_tab_kinds_roundtrip(qt_app, tmp_path, kind):
    app, series = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        if kind == 'settings': workspace.openSettings()
        else: workspace.createTab(series.series_instance_uid, kind, kind)
        tab = workspace.activeTab
        state = workspace._load_states.get(tab.tab_config.tab_id)
        if state: wait_until(lambda: state.status in ('ready', 'error'), timeout=20000)
        assert not state or state.status == 'ready', state.message
        path = tmp_path / (kind + '.voxworkspace')
        manager = app.workspaceDocumentController
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        assert workspace.activeTab.tab_config.tab_type.value == kind
    finally: app.shutdown()


def test_measurement_csv_privacy_pdf_and_busy_export(qt_app, tmp_path):
    app, record = populated_app(tmp_path)
    try:
        view = app.workspaceController.activeViewport
        draw_length(view)
        report = app.exportController.measurementReport
        csv_path = tmp_path / 'results.csv'
        assert report.export_to(csv_path)
        wait_until(lambda: not report.busy)
        assert not report.isError, report.message
        assert report.resultPath == str(csv_path)
        text = csv_path.read_text('utf-8-sig')
        assert 'PRIVATE-ID' not in text and record.patient_name not in text and record.series_instance_uid not in text
        assert '患者 1' in text and '长度' in text
        pdf = tmp_path / 'results.pdf'
        assert report.export_to(pdf, format='pdf', include_images=True)
        wait_until(lambda: not report.busy)
        assert not report.isError, report.message
        assert pdf.read_bytes().startswith(b'%PDF-')
        assert report.resultPath == str(pdf)
        assert len(pdf.read_bytes()) > 3000
        assert report.export_to(csv_path, anonymous=False)
        wait_until(lambda: not report.busy)
        assert 'PRIVATE-ID' in csv_path.read_text('utf-8-sig')
    finally: app.shutdown()

from test_pet_fusion import paired_series


@pytest.mark.parametrize('kind', ['mpr', '3d', 'fusion', 'fusion3d'])
def test_pet_workspace_roundtrip(qt_app, tmp_path, paired_series, kind, monkeypatch):
    _, ct, pet = paired_series
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet])
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        workspace = app.workspaceController
        if kind.startswith('fusion'): workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        else: workspace.createTab(pet.series_instance_uid, 'PET', kind)
        tab = workspace.activeTab
        wait_until(lambda: workspace._load_states[tab.tab_config.tab_id].status == 'ready', timeout=20000)
        if kind == 'fusion3d':
            tab.matrix[0, 3] = 1.5
            tab.request_render()
            wait_until(lambda: tab._last_result.request.transform[3] == 1.5)
            source = tab
            workspace.createFusionVolumeTab(source)
            tab = workspace.activeTab
            from PySide6.QtWidgets import QMessageBox
            with monkeypatch.context() as closing:
                closing.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Close)
                workspace.closeTab(source.tab_config.tab_id)
        elif kind == '3d':
            tab.activeViewport.setPetUpper(0.15)
        path = tmp_path / 'pet.voxworkspace'
        manager = app.workspaceDocumentController
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        assert len(workspace._tab_dict) == 1
        if kind == '3d': assert workspace.activeViewport.petUpper == .15
        if kind == 'fusion3d': assert workspace.activeViewport.scene.request.transform[3] == 1.5
    finally: app.shutdown()


def test_four_d_phase_and_shared_window_restored(qt_app, tmp_path):
    from test_four_d import _cross_series_four_d
    from qt_dicom_viewer.model import WindowLevel, WindowLevelChange
    records = _cross_series_four_d(tmp_path)
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        workspace = app.workspaceController
        workspace.createTab(records[0].series_instance_uid, '4D', '4d')
        tab = workspace.activeTab
        wait_until(lambda: workspace._load_states[tab.tab_config.tab_id].status == 'ready')
        tab.setPhaseIndex(2)
        wait_until(lambda: tab._current_phase_index == 2 and not tab._active_mpr_requests)
        tab._set_mpr_window(WindowLevelChange(WindowLevel(45, 222), True))
        wait_until(lambda: not tab._active_mpr_requests)
        tab.focusSingleViewport(tab.activeViewport.viewportId)
        path = tmp_path / '4d.voxworkspace'
        manager = app.workspaceDocumentController
        manager.save_to(path); wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        manager.restore_from(path); wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        restored = workspace.activeTab
        assert restored._current_phase_index == 2
        assert restored.focusedViewportId == restored.activeViewport.viewportId
        for v in restored.viewports_by_id.values():
            assert v._state.window == WindowLevel(45, 222)
            assert v._state.inverted
    finally: app.shutdown()


def test_roi_stats_annotation_delete_paste_and_history(qt_app, tmp_path):
    from qt_dicom_viewer.model import ImagePoint
    app, series = populated_app(tmp_path)
    try:
        view, tab = app.workspaceController.activeViewport, app.workspaceController.activeTab
        measure, annotations, history = view._measure_controller, view._text_annotation_controller, tab.historyController
        context = view._measurement_context(3, 2, kind=MeasurementKind.RECT)
        mid = measure.paste_points([ImagePoint(30, 30), ImagePoint(50, 50)], context)
        history.capture()
        metrics = measure._measurements[mid].metrics
        assert metrics.pixel_count > 0 and metrics.area_mm2 == pytest.approx(20 * .7 * 20 * .8)
        count = len(history._undo)
        measure.refresh_roi_metrics(view._modality_pixel.copy(), view._frame_meta)
        history.capture()
        assert len(history._undo) == count
        annotations.beginAnnotation(25, 25)
        annotations.updateAnnotation(40, 40)
        history.capture()
        assert len(history._undo) == count
        annotations.finishAnnotation(40, 40)
        history.capture()
        assert len(history._undo) == count+1
        aid = annotations.selectedAnnotationId
        annotations.deleteSelected()
        history.capture()
        history.undo()
        assert aid in annotations._annotations
        history.undo()
        assert not annotations._annotations
        history.undo()
        assert not measure._measurements
        history.redo()
        assert measure._measurements[mid].metrics == metrics
    finally: app.shutdown()


def test_mpr_voi_and_volume_crop_history_and_save(qt_app, tmp_path):
    app, series = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        workspace.createTab(series.series_instance_uid, 'MPR', 'mpr')
        tab = workspace.activeTab
        wait_until(lambda: workspace._load_states[tab.tab_config.tab_id].status == 'ready')
        voi, view = tab._voi_controller, tab.activeViewport
        tab.toolController.activateTool('voi')
        voi.begin(view, 25, 25, .1)
        voi.finish(view, 40, 40)
        wait_until(lambda: not voi.busy)
        tab.historyController.capture()
        original = voi.records[0]['region']
        tab.historyController.undo()
        assert voi.records == []
        tab.historyController.redo()
        wait_until(lambda: not voi.busy)
        assert voi.records[0]['region'] == original
        workspace.createTab(series.series_instance_uid, '3D', '3d')
        volume_tab = workspace.activeTab
        volume = volume_tab.activeViewport
        wait_until(lambda: volume.loadState == 'ready')
        mask = np.ones_like(volume.volume.modality_pixels, dtype=bool)
        mask[:, :20] = False
        volume.crop_mask = mask
        volume._update_mask()
        volume_tab.historyController.capture()
        volume_tab.historyController.undo()
        assert volume.crop_mask is None
        volume_tab.historyController.redo()
        np.testing.assert_equal(volume.crop_mask, mask)
        path = tmp_path / 'edits.voxworkspace'
        manager = app.workspaceDocumentController
        manager.save_to(path); wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        manager.restore_from(path); wait_until(lambda: not manager.busy, timeout=20000)
        assert not manager.isError, manager.message
        np.testing.assert_equal(workspace.activeViewport.crop_mask, mask)
        mpr = next(t for t in workspace._tab_dict.values() if t.tab_config.tab_type.value == 'mpr')
        assert mpr._voi_controller.records[0]['region'] == original
    finally: app.shutdown()


def test_invalid_document_preserves_current_tabs_and_recovery_is_not_deleted(qt_app, tmp_path):
    app, series = populated_app(tmp_path)
    try:
        manager = app.workspaceDocumentController
        path = tmp_path / 'bad.voxworkspace'
        manager.save_to(path); wait_until(lambda: not manager.busy)
        doc = json.loads(path.read_bytes())
        doc['tabs'][0]['views'] = []
        path.write_text(json.dumps(doc))
        original = app.workspaceController.activeTab
        manager.restore_from(path); wait_until(lambda: not manager.busy)
        assert manager.isError
        assert app.workspaceController.activeTab is original
    finally: app.shutdown()
    recovery = tmp_path / 'workspace-recovery.voxworkspace'
    recovery.write_text('existing recovery data')
    app = AppController(DicomImageProvider(), settings_path=tmp_path / 'settings.json')
    try: assert app.workspaceDocumentController.recoveryAvailable
    finally: app.shutdown()
    assert recovery.read_text() == 'existing recovery data'


def test_csv_formula_guard_and_missing_values():
    from qt_dicom_viewer.core.measurement_report import csv_bytes
    import csv, io
    encoded = csv_bytes([dict(patient='=CMD()', patient_id=' @SUM(1)', length_mm=None, mean=-3.5)])
    rows = list(csv.reader(io.StringIO(encoded.decode('utf-8-sig'))))
    assert rows[1][0] == "'=CMD()"
    assert rows[1][1] == "' @SUM(1)"
    assert rows[1][9] == ''
    assert rows[1][16] == '-3.50'


def test_application_quit_respects_unsaved_cancel_and_discard(qt_app, tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent
    app, _ = populated_app(tmp_path)
    try:
        manager = app.workspaceDocumentController
        manager.mark_dirty()
        monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: ('cancel', False))
        assert manager.eventFilter(qt_app, QEvent(QEvent.Quit))
        monkeypatch.setattr(manager, '_ask_exit_behavior', lambda: ('discard', False))
        assert not manager.eventFilter(qt_app, QEvent(QEvent.Quit))
        assert manager.requestClose()
    finally: app.shutdown()


def test_recovery_copy_keeps_dirty_state_and_cancelled_load_keeps_workspace(qt_app, tmp_path, monkeypatch):
    from threading import Event
    import qt_dicom_viewer.ui.controller.workspace_document_controller as module
    from qt_dicom_viewer.core.local_import import ImportCancelled
    app, _ = populated_app(tmp_path, settings_path=tmp_path / 'display-settings.json')
    release, entered = Event(), Event()
    try:
        manager = app.workspaceDocumentController
        manager._recovery_path = tmp_path / 'recovery.voxworkspace'
        manager.mark_dirty()
        manager._save_recovery()
        wait_until(lambda: not manager.busy)
        assert manager.dirty and manager._recovery_path.is_file()
        assert not manager.recoveryAvailable  # Current-session autosave is not a previous crash.
        assert read_document(manager._recovery_path)['tabs']
        original = app.workspaceController.activeTab
        def delayed(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            assert kwargs['cancelled']()
            raise ImportCancelled('已取消恢复工作区。')
        monkeypatch.setattr(module, 'load_referenced_series', delayed)
        assert manager.restore_from(manager._recovery_path)
        assert entered.wait(2)
        manager.cancel(); release.set()
        wait_until(lambda: not manager.busy)
        assert app.workspaceController.activeTab is original
    finally:
        release.set()
        app.shutdown()
    assert not manager._recovery_path.exists()


def test_codec_limits_combined_mask_memory(monkeypatch):
    import qt_dicom_viewer.core.workspace_state as codec
    payload = codec.dumps([np.zeros((2, 2, 2), dtype=bool), np.ones((2, 2, 2), dtype=bool)])
    monkeypatch.setattr(codec, 'MAX_MASK_VOXELS', 12)
    with pytest.raises(ValueError, match='总量'):
        codec.loads(payload)


def test_codec_rejects_combined_masks_before_writing(monkeypatch):
    import qt_dicom_viewer.core.workspace_state as codec
    monkeypatch.setattr(codec, 'MAX_MASK_VOXELS', 12)
    within_limit = {'tabs': [{'mask': np.ones((1, 2, 2), bool)},
                             {'mask': np.zeros((2, 2, 2), bool)}]}
    restored = codec.loads(codec.dumps(within_limit))
    np.testing.assert_array_equal(restored['tabs'][1]['mask'], within_limit['tabs'][1]['mask'])
    too_large = {'tabs': [{'mask': np.ones((2, 2, 2), bool)},
                          {'mask': np.zeros((2, 2, 2), bool)}]}
    with pytest.raises(ValueError, match='总量'):
        codec.dumps(too_large)
    # Dirty detection must still work for a workspace that needs fewer masks
    # before it can be saved; fingerprints never allocate restorable masks.
    assert codec.fingerprint(too_large) != codec.fingerprint(within_limit)


def test_oversized_mask_save_preserves_document_and_unsaved_edits(qt_app, tmp_path, monkeypatch):
    import qt_dicom_viewer.core.workspace_state as codec
    app, series = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        workspace.createTab(series.series_instance_uid, '3D', '3d')
        view = workspace.activeViewport
        wait_until(lambda: view.loadState == 'ready')
        manager = app.workspaceDocumentController
        path = tmp_path / 'safe.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        previous = path.read_bytes()
        view.crop_mask = np.ones_like(view.volume.modality_pixels, dtype=bool)
        view._bed_mask = view.crop_mask.copy()
        view._bed_enabled = True
        view._update_mask()
        monkeypatch.setattr(codec, 'MAX_MASK_VOXELS', view.crop_mask.size * 3 // 2)
        manager._close_after_save = True
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert manager.isError and '总量' in manager.message
        assert manager.dirty
        assert not manager._close_after_save
        assert path.read_bytes() == previous
        assert read_document(path)['format'] == FORMAT
        assert workspace.activeViewport is view and view.hasCrop
    finally:
        app.shutdown()


def test_mr_workspace_preserves_active_series_with_multiple_selected(qt_app, tmp_path):
    from test_mr import write_mr_series
    records = [write_mr_series(tmp_path / str(n)) for n in range(3)]
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        panel = app.panelController
        snapshot = DicomFolderScanSnapshot(tmp_path, 12, 12, 0, records)
        panel.update_series_session(snapshot)
        panel._update_series_record(snapshot)
        for record in records:
            panel.selectSeriesWithModifiers(record.series_instance_uid, True)
        expected = records[1].series_instance_uid
        panel.selectContextSeries(expected)
        path = tmp_path / 'mr-selection.voxworkspace'
        manager = app.workspaceDocumentController
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert read_document(path)['activeSeries'] == expected
        panel.selectSeries(records[0].series_instance_uid)
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert panel.selectedSeriesUids == [r.series_instance_uid for r in records]
        assert panel.activeSeriesUid == expected
        panel.openSeriesView(panel.activeSeriesUid, 'tag')
        assert app.workspaceController.activeTab.tab_config.series_metas[0].series_uid == expected
        # Older files omit the field: retain the most recently selected item.
        document = read_document(path)
        document.pop('activeSeries')
        atomic_write(path, dumps(document))
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert panel.activeSeriesUid == records[-1].series_instance_uid
    finally:
        app.shutdown()
