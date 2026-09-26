from dataclasses import replace
import pytest
import numpy as np
from test_mtf_controller import (qt_app, mtf_viewport, capture_tasks, draw, finish, deliver_frame)
from test_water_qa_controller import qa_view, wait_qa
from qt_dicom_viewer.core.workspace_state import dumps, loads


@pytest.mark.parametrize('target', ['mtf', 'fwhm'])
def test_analysis_roundtrip_freezes_parameters_and_rejects_changed_pixels(mtf_viewport, monkeypatch, target):
    view, frame = mtf_viewport
    view._tool_controller.selectService('service:' + target)
    controller = view.mtfController if target == 'mtf' else view.fwhmController
    jobs = capture_tasks(view, monkeypatch, controller)
    draw(view, (25, 61), (102, 66)) if target == 'fwhm' else draw(view)
    finish(view, jobs[-1])
    saved_result = controller.currentResult
    saved = loads(dumps(controller.persistent_state()))
    assert saved['records'] and next(iter(saved['records'].values()))['timestamp']
    controller.reset()
    controller.restore_state(saved)
    assert controller.currentResult == saved_result
    assert len(jobs) == 1
    controller.settingsController.setValue('services', 'rampThicknessAngle', 45)
    controller.settingsController.setValue('services', 'mtfGaussianEquivalent', True)
    assert controller.currentResult == saved_result
    controller.set_current_slice(1)
    controller.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel)
    assert controller.currentResult == saved_result and len(jobs) == 1
    controller.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel + 1)
    assert controller.status == 'error' and not controller.currentResult
    assert controller.persistent_state()['records'] == saved['records']
    controller.recalculate()
    assert len(jobs) == 2
    request = jobs[-1][0]
    controller._receive_result(request, None, 'Simulated failure')
    assert controller.status == 'error'
    assert controller.persistent_state()['records'] == saved['records']


def test_qa_restores_edited_and_copied_rois_without_recalculation(qa_view, qt_app, monkeypatch):
    view, frame = qa_view
    controller = view.qaController
    view._tool_controller.selectService('service:qa')
    wait_qa(qt_app, controller)
    assert controller.copyRoi('center')
    extra = controller.currentResult['rois'][-1]
    assert len(controller.currentResult['rois']) == 6
    saved_result = controller.currentResult
    saved = loads(dumps(controller.persistent_state()))
    controller.reset()
    jobs = []
    monkeypatch.setattr(controller, '_submit', lambda *args: jobs.append(args))
    controller.restore_state(saved)
    assert controller.currentResult == saved_result
    controller.set_current_slice(1)
    controller.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel)
    assert controller.currentResult == saved_result and not jobs
    assert controller.currentResult['rois'][-1]['key'] == extra['key']
    controller.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel + 1)
    assert controller.status == 'error' and not controller.currentResult
    assert controller.persistent_state()['records'] == saved['records']
    controller.analyze()
    assert len(jobs) == 1
    controller._receive_result(jobs[0][0], jobs[0][1], None, 'Simulated failure')
    assert controller.persistent_state()['records'] == saved['records']


def test_mtf_navigation_does_not_mark_analysis_edited(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    controller = view.mtfController
    jobs = capture_tasks(view, monkeypatch)
    edits = []
    controller.recordsChanged.connect(lambda: edits.append(True))
    draw(view)
    finish(view, jobs[-1])
    count = len(edits)
    controller.set_current_slice(1)
    controller.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel)
    assert len(edits) == count


@pytest.mark.parametrize('kind', ['mtf', 'fwhm', 'qa'])
def test_workspace_file_reopens_completed_analysis(qt_app, tmp_path, kind):
    import pydicom
    from test_series_sidebar import phantom_series
    from test_bead_mtf import gaussian
    from test_water_qa import water_image
    from test_dicom_tags import wait_until
    from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    phantom_series(tmp_path, 1, 'QA-TEST', '1.2.3.1', '20260903')
    pixels = water_image(mean=2) if kind == 'qa' else gaussian(sigma_x=.2, sigma_y=.15)
    for path in tmp_path.glob('*.dcm'):
        ds = pydicom.dcmread(path)
        ds.Rows, ds.Columns = pixels.shape
        ds.PixelSpacing = [1, 1] if kind == 'qa' else [.15, .1]
        ds.RescaleSlope, ds.RescaleIntercept = 1, 0
        ds.PixelRepresentation, ds.BitsStored, ds.HighBit = 1, 16, 15
        ds.PixelData = np.rint(pixels).astype('<i2').tobytes()
        ds.save_as(path, enforce_file_format=True)
    snapshots = list(DicomFolderScanner().scan_files(list(tmp_path.glob('*.dcm')), folder=tmp_path))
    snapshot = snapshots[-1]
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        app.workspaceController.createTab(snapshot.series[0].series_instance_uid, 'QA', '2d')
        wait_until(lambda: app.workspaceController.activeViewport.loadState == 'ready')
        view = app.workspaceController.activeViewport
        controller = getattr(view, '_' + kind + '_controller')
        if kind == 'qa':
            controller.analyze()
        else:
            assert controller.applyRoi(63, 63, 8, .75 if kind == 'fwhm' else 8)
        wait_until(lambda: controller.status != 'calculating')
        assert controller.status == 'ready', controller.error
        result = controller.currentResult
        records = controller.persistent_state()
        path = tmp_path/'analysis.voxworkspace'
        manager = app.workspaceDocumentController
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        restored = getattr(app.workspaceController.activeViewport, '_' + kind + '_controller')
        wait_until(lambda: restored.status == 'ready')
        assert restored.currentResult == result
        assert restored.persistent_state()['records'] == records['records']
        assert not manager.dirty
    finally:
        app.shutdown()


def test_method_change_only_recalculates_current_slice(mtf_viewport, monkeypatch):
    view, frame = mtf_viewport
    controller = view.mtfController
    jobs = capture_tasks(view, monkeypatch)
    draw(view)
    finish(view, jobs[-1])
    original = controller.currentResult
    second = replace(frame, frame_meta=replace(frame.frame_meta, slice_index=1))
    controller.set_current_slice(1)
    controller.set_frame(second.series_uid, second.frame_meta, second.modality_pixel)
    draw(view)
    finish(view, jobs[-1])
    changes = []
    controller.recordsChanged.connect(lambda: changes.append(True))
    controller.setAnalysisMethod('gaussian')
    assert changes
    finish(view, jobs[-1])
    count = len(jobs)
    controller.set_current_slice(0)
    controller.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel)
    assert controller.currentResult == original
    assert controller.analysisMethod == 'tukey_fft'
    assert len(jobs) == count
