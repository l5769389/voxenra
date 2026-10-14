from pathlib import Path
from threading import Event
from types import SimpleNamespace
from dataclasses import replace
import numpy as np
import pydicom
import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import QPointF

from qt_dicom_viewer.ui.controller.dicom_results_controller import (
    DicomResultsController,
)
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from test_dicom_results import source as source, segmentation, freehand
from test_dicom_tags import qt_app as qt_app, wait_until
from test_pacs_qml import scene as scene
from test_tag_qml import find, click


@pytest.fixture(params=[(1, 2, 3), (7, 19, 42), (0, 1, 2)])
def temporal_source(source, tmp_path, request):
    """Real scanned phase sources with identical geometry and distinct SOPs."""
    from pydicom.uid import generate_uid
    from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner

    original, _ = source
    folder = tmp_path / "temporal"
    folder.mkdir()
    for phase in request.param:
        phase_series_uid = generate_uid()
        for index, instance in enumerate(original.instances):
            dataset = pydicom.dcmread(instance.path)
            dataset.SOPInstanceUID = generate_uid()
            dataset.file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID
            dataset.SeriesInstanceUID = phase_series_uid
            dataset.SeriesNumber = phase
            dataset.SeriesDescription = "Temporal exchange"
            dataset.TemporalPositionIdentifier = phase
            dataset.NumberOfTemporalPositions = 3
            dataset.save_as(folder / f"phase-{phase}-{index}.dcm", enforce_file_format=True)
    snapshot = list(DicomFolderScanner().scan_files(
        list(folder.glob("*.dcm")), folder=folder, can_publish=lambda: False
    ))[-1]
    series = min(snapshot.series, key=lambda record: record.series_number)
    assert series.phase_identifiers == request.param
    return series


def phase_workspace(series, phase_index):
    from qt_dicom_viewer.core.volume_manager import VolumeManager

    volume = VolumeManager().get_or_build(series, series.phase_identifiers[phase_index])
    workspace, catalog, result = workspace_for(series, volume)
    tab = workspace.activeTab
    tab._phase_identifiers = series.phase_identifiers
    tab.tab_config = SimpleNamespace(tab_type="4d")
    voi = tab._voi_controller
    voi._phase, voi._phase_ready = phase_index, True
    result.record["phase"] = phase_index
    view = next(iter(tab.viewports_by_id.values()))
    view._voi_volume = volume
    view._tool_controller = SimpleNamespace(mpr_projection_settings=SimpleNamespace(enabled=False))
    tab.activeViewport = view
    return workspace, catalog, result


@pytest.mark.parametrize("phase_index", [0, 1, 2])
def test_four_d_snapshot_preserves_phase_source_and_saved_index(temporal_source, phase_index):
    from qt_dicom_viewer.core.workspace_state import dumps, loads
    from qt_dicom_viewer.ui.controller.dicom_results_controller import capture_dicom_results

    workspace, catalog, result = phase_workspace(temporal_source, phase_index)
    restored = loads(dumps(result.record))
    workspace.activeTab._voi_controller.current_records = [restored]
    _, segments = capture_dicom_results(workspace, catalog, report=False)
    expected = temporal_source.phases[phase_index].instances
    assert segments[0].instances == expected
    assert segments[0].record["phase"] == phase_index


@pytest.mark.parametrize("phase_index", [0, 1, 2])
def test_four_d_mask_target_uses_phase_identifier(qt_app, temporal_source, phase_index):
    workspace, catalog, _ = phase_workspace(temporal_source, phase_index)
    controller = DicomResultsController(workspace, catalog)
    try:
        assert controller._mask_target()[-1] == temporal_source.phases[phase_index].instances
    finally:
        controller.shutdown()


def test_mpr_exchange_uses_native_source_in_linked_temporal_series(qt_app, temporal_source):
    from qt_dicom_viewer.ui.controller.dicom_results_controller import capture_dicom_results

    native_instances = temporal_source.phases[1].instances
    series = replace(
        temporal_source,
        series_instance_uid=native_instances[0].series_instance_uid,
        instances=native_instances,
    )
    workspace, catalog, result = phase_workspace(series, 1)
    tab = workspace.activeTab
    tab.tab_config.tab_type = "mpr"
    tab._phase_identifiers = ()
    tab._voi_controller._phase = result.record["phase"] = None
    _, segments = capture_dicom_results(workspace, catalog, report=False)
    assert segments[0].instances == native_instances
    controller = DicomResultsController(workspace, catalog)
    try:
        assert controller._mask_target()[-1] == native_instances
    finally:
        controller.shutdown()


def test_four_d_seg_export_import_roundtrip_keeps_source_phase(qt_app, temporal_source, tmp_path):
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.core.segmentation_masks import mask_record
    from test_segmentation_import import full_mask

    series = temporal_source
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 12, 12, 0, [series])
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        app.workspaceController.createTab(series.series_instance_uid, "Phase exchange", "4d")
        tab = app.workspaceController.activeTab
        voi, controller = tab.voiController, app.exportController.dicomResults
        for phase_index in (0, 1, 2):
            tab.setPhaseIndex(phase_index)
            wait_until(lambda: voi._phase_ready and bool(voi.sources) and not tab.activeViewport.render_pending)
            volume = tab.activeViewport._voi_volume
            mask = np.zeros(volume.modality_pixels.shape, dtype=bool)
            mask[:, 2:5, 2:5] = True
            record, evaluation = mask_record(volume, mask, (0, 0, 0), name="Phase mask", phase=phase_index)
            voi.add_masks([record], {record["id"]: evaluation})
            assert controller.export_to(tmp_path, kind="seg"), controller.message
            wait_until(lambda: not controller.busy)
            assert not controller.isError, controller.message
            path = Path(controller.resultPath) / "SEG-001.dcm"
            dataset = pydicom.dcmread(path)
            referenced = {
                str(group.DerivationImageSequence[0].SourceImageSequence[0].ReferencedSOPInstanceUID)
                for group in dataset.PerFrameFunctionalGroupsSequence
            }
            assert referenced == {i.sop_instance_uid for i in series.phases[phase_index].instances}
            voi.clear("")
            assert controller.import_from(path), controller.message
            wait_until(lambda: not controller.busy)
            assert not controller.isError, controller.message
            assert len(voi.current_records) == 1
            imported = voi.current_records[0]
            assert imported["phase"] == phase_index
            np.testing.assert_array_equal(full_mask(imported, mask.shape), mask)
    finally:
        app.shutdown()


def workspace_for(series, volume):
    r = segmentation(series, volume)
    roi = freehand(series, volume)
    voi = SimpleNamespace(
        current_records=[r.record],
        evaluations={r.record["id"]: r.evaluation},
        busy=False,
        _draft=None,
    )
    measure = SimpleNamespace(
        committed_measurements=[roi.measurement],
        has_active_transaction=False,
        _measurement_frames={roi.measurement.measurement_id: roi.frame},
    )
    view = SimpleNamespace(_measure_controller=measure, viewportRole="image")
    workspace = SimpleNamespace(
        activeTab=SimpleNamespace(viewports_by_id={"a": view}, _voi_controller=voi)
    )
    catalog = SimpleNamespace(get_series=lambda uid: series)
    return workspace, catalog, r


def test_background_snapshot_survives_edit_tab_close_and_preserves_metrics(
    qt_app, source, tmp_path, monkeypatch
):
    series, volume = source
    workspace, catalog, r = workspace_for(series, volume)
    controller = DicomResultsController(workspace, catalog)
    import qt_dicom_viewer.core.dicom_results as module

    actual = module.write_results
    entered, release = Event(), Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return actual(*args, **kwargs)

    monkeypatch.setattr(module, "write_results", blocked)
    try:
        assert controller.export_to(tmp_path) and entered.wait(3)
        assert not controller.export_to(tmp_path)
        r.evaluation.mask[:] = False
        r.record["name"] = "changed"
        workspace.activeTab = None
        release.set()
        wait_until(lambda: not controller.busy)
        assert not controller.isError, controller.message
        output = Path(controller.resultPath)
        assert len(list(output.glob("*.dcm"))) == 3
        assert (
            pydicom.dcmread(output / "SEG-001.dcm").SegmentSequence[0].SegmentLabel
            == "测试分割"
        )
    finally:
        release.set()
        controller.shutdown()


def test_draft_and_missing_evaluation_rejected_before_write(qt_app, source, tmp_path):
    series, volume = source
    workspace, catalog, _ = workspace_for(series, volume)
    controller = DicomResultsController(workspace, catalog)
    try:
        workspace.activeTab._voi_controller._draft = {"editing": True}
        assert not controller.export_to(tmp_path)
        assert controller.isError and not controller.busy
        workspace.activeTab._voi_controller._draft = None
        workspace.activeTab._voi_controller.evaluations.clear()
        assert not controller.export_to(tmp_path)
    finally:
        controller.shutdown()


def test_actual_export_panel_buttons_write_seg_and_linked_sr(
    scene, source, tmp_path, monkeypatch
):
    window, app, warnings = scene
    series, volume = source
    snapshot = DicomFolderScanSnapshot(
        tmp_path, len(series.instances), len(series.instances), 0, [series]
    )
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    workspace = app.workspaceController
    workspace.createTab(series.series_instance_uid, "DICOM results", "mpr")
    tab = workspace.activeTab
    wait_until(lambda: bool(tab.voiController.sources))
    r = segmentation(series, volume)
    r.record.update(phase=None, visible=True)
    tab.voiController.records = [r.record]
    tab.voiController.evaluations = {r.record["id"]: r.evaluation}
    monkeypatch.setattr(
        "qt_dicom_viewer.ui.controller.dicom_results_controller.QFileDialog.getExistingDirectory",
        lambda *args: str(tmp_path),
    )
    window.resize(1280, 720)
    app.settingsController.setValue("layout", "rightPanelWidth", 220)
    QTest.qWait(80)
    tab.toolController.activateTool("export")
    QTest.qWait(80)
    flickable = find(window, "toolDetailFlickable")

    def reveal(name):
        button = find(window, name)
        point = button.mapToScene(QPointF(0, button.height()))
        bottom = flickable.mapToScene(QPointF(0, flickable.height())).y()
        if point.y() > bottom:
            flickable.setProperty(
                "contentY", flickable.property("contentY") + point.y() - bottom + 8
            )
        QTest.qWait(50)
        start = button.mapToScene(QPointF(0, 0))
        end = button.mapToScene(QPointF(button.width(), button.height()))
        assert 0 <= start.x() < end.x() <= window.width()
        assert 0 <= start.y() < end.y() <= window.height()
        return button

    controller = app.exportController.dicomResults
    click(window, reveal("exportSegmentation"))
    wait_until(lambda: not controller.busy)
    assert controller.resultPath and not controller.isError, controller.message
    assert len(list(Path(controller.resultPath).glob("SEG-*.dcm"))) == 1
    click(window, reveal("exportStructuredReport"))
    wait_until(lambda: not controller.busy)
    assert controller.resultPath and not controller.isError, controller.message
    assert len(list(Path(controller.resultPath).glob("*.dcm"))) == 2
    assert not warnings, warnings


def test_real_mpr_projection_export_rejected_even_after_disabling(
    qt_app, source, tmp_path
):
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.model import ImagePoint, MeasurementKind

    series, _ = source
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series])
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        app.workspaceController.createTab(series.series_instance_uid, "MPR", "mpr")
        tab = app.workspaceController.activeTab
        wait_until(lambda: bool(tab.voiController.sources))
        view = tab.activeViewport
        tab.toolController.setMprThickness("axial", 6)
        tab.toolController.setMprProjectionEnabled(True)
        measure = view._measure_controller
        wait_until(
            lambda: measure.frame_key is not None and len(measure.frame_key) == 7
        )
        context = view._measurement_context(1, 0.1, kind=MeasurementKind.FREEHAND)
        identifier = measure.paste_points(
            [ImagePoint(1, 1), ImagePoint(4, 1), ImagePoint(3, 4)], context
        )
        assert identifier
        tab.toolController.setMprProjectionEnabled(False)
        wait_until(lambda: len(measure.frame_key) == 6)
        export = app.exportController.dicomResults
        assert export.export_to(tmp_path)
        wait_until(lambda: not export.busy)
        assert export.isError and not export.resultPath
        assert not list(tmp_path.glob("voxenra-results-*"))
    finally:
        app.shutdown()


def test_four_d_planar_export_references_recorded_phase_after_switch(qt_app, temporal_source, tmp_path):
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.model import ImagePoint, MeasurementKind
    from qt_dicom_viewer.ui.controller.dicom_results_controller import capture_dicom_results

    series = temporal_source
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        app.panelController.update_series_session(DicomFolderScanSnapshot(tmp_path, 12, 12, 0, [series]))
        app.workspaceController.createTab(series.series_instance_uid, 'Temporal', '4d')
        tab = app.workspaceController.activeTab
        wait_until(lambda: tab.voiController._phase_ready and not tab._active_mpr_requests)
        tab.setPhaseIndex(1)
        wait_until(lambda: tab._current_phase_index == 1 and tab.voiController._phase_ready
                   and not tab._active_mpr_requests)
        tab.toolController.activateTool('measure')
        view = tab.activeViewport
        measure = view.measurementController
        context = view._measurement_context(1, .1, kind=MeasurementKind.FREEHAND)
        identifier = measure.paste_points([ImagePoint(1, 1), ImagePoint(4, 1), ImagePoint(3, 4)], context)
        assert identifier
        tab.setPhaseIndex(2)
        wait_until(lambda: tab._current_phase_index == 2 and tab.voiController._phase_ready
                   and not tab._active_mpr_requests)
        planar, _ = capture_dicom_results(app.workspaceController, app._series_catalog)
        assert len(planar) == 1
        assert planar[0].instances == tuple(series.phases[1].instances)
        export = app.exportController.dicomResults
        assert export.export_to(tmp_path)
        wait_until(lambda: not export.busy)
        assert not export.isError, export.message
        sr = pydicom.dcmread(Path(export.resultPath) / 'SR-001.dcm')
        referenced = {str(ref.ReferencedSOPInstanceUID)
                      for study in sr.CurrentRequestedProcedureEvidenceSequence
                      for evidence_series in study.ReferencedSeriesSequence
                      for ref in evidence_series.ReferencedSOPSequence}
        assert referenced == {i.sop_instance_uid for i in series.phases[1].instances}
    finally:
        app.shutdown()


@pytest.mark.parametrize('context', [("phase", 999), ("phase", None),
                                    ("projection", "max", 10, "phase", 7), ("phase", 7, "unknown")])
def test_four_d_planar_export_rejects_unresolved_or_projected_context(qt_app, temporal_source, tmp_path, context):
    workspace, catalog, _ = phase_workspace(temporal_source, 1)
    measure = workspace.activeTab.activeViewport._measure_controller
    identifier = measure.committed_measurements[0].measurement_id
    measure._measurement_frames[identifier] += (context,)
    export = DicomResultsController(workspace, catalog)
    try:
        export.export_to(tmp_path)
        wait_until(lambda: not export.busy)
        assert export.isError and not export.resultPath
        assert not list(tmp_path.glob('voxenra-results-*'))
    finally:
        export.shutdown()
