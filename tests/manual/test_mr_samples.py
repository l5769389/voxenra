"""Opt-in regression against original public MR DICOM samples.

VOXENRA_MR_SAMPLE_DIR=/path/to/Voxenra-MR-TestData PYTHONPATH=src:tests \
    python -m pytest tests/manual/test_mr_samples.py -q
See docs/mr-test-data.md for fixed upstream versions and file checksums.
"""
import hashlib
import itertools
import json
import os
from pathlib import Path

import numpy as np
import pydicom
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.core.mpr_layout import MPR_LAYOUTS
from qt_dicom_viewer.core.series_export import ExportRequest, export_series
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.model import MeasurementKind, MprPlane, WindowLevel
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click, descendants
from test_measurement_controller import _position, _drag

T1_FOLDERS = ('01_T1_Brain_HFS', '02_T1_Brain_HFDR')


@pytest.fixture(scope='module')
def sample_root():
    value = os.getenv('VOXENRA_MR_SAMPLE_DIR')
    if not value:
        pytest.skip('Set VOXENRA_MR_SAMPLE_DIR to the public sample directory')
    root = Path(value)
    assert root.is_dir(), root
    return root


def scan(path):
    return list(DicomFolderScanner().scan(path))[-1]


def ready(ws):
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready', timeout=15000)


def import_local(app, paths):
    assert app.panelController.importUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    wait_until(lambda: not app.panelController.scanning, timeout=15000)
    assert not app.panelController.importError


def test_original_files_still_match_upstream(sample_root):
    manifest = json.loads((sample_root/'manifest.json').read_text())
    assert sum(item['path'].endswith('.dcm') for item in manifest['files']) == 84
    for item in manifest['files']:
        data = (sample_root/item['path']).read_bytes()
        assert len(data) == item['size']
        assert hashlib.sha256(data).hexdigest() == item['sha256']


@pytest.mark.parametrize('folder', T1_FOLDERS)
def test_patient_space_and_mpr_values_match_source(sample_root, folder):
    series = scan(sample_root/folder).series[0]
    datasets = [pydicom.dcmread(i.path) for i in series.instances]
    volume = VolumeManager().get_or_build(series)
    assert len(datasets) == 35
    # DICOM positions are the independent spatial reference, including HFDR.
    for k, ds in enumerate(datasets):
        actual = volume.geometry.voxel_to_patient @ [k, 31, 73, 1]
        position = np.asarray(ds.ImagePositionPatient, dtype=float)
        column_dir, row_dir = np.asarray(ds.ImageOrientationPatient, dtype=float).reshape(2, 3)
        expected = position + column_dir * float(ds.PixelSpacing[1]) * 73 + row_dir * float(ds.PixelSpacing[0]) * 31
        np.testing.assert_allclose(actual[:3], expected, atol=2e-4)
        np.testing.assert_array_equal(volume.modality_pixels[k], ds.pixel_array)
    assert volume.geometry.slice_spacing == pytest.approx(4.8, abs=2e-4)
    assert volume.geometry.slice_spacing != float(datasets[0].SliceThickness)
    source = np.stack([ds.pixel_array for ds in datasets]).astype(float)
    for plane in MprPlane:
        sliced = MprReslicer().reslice(volume, plane)
        rows, columns = sliced.modality_pixels.shape
        for y, x in itertools.product((rows//4, rows//2, rows*3//4), (columns//4, columns//2, columns*3//4)):
            patient = sliced.geometry.image_point_to_patient(column=x, row=y)
            coord = (volume.geometry.patient_to_voxel @ [*patient, 1])[:3]
            assert np.all(coord >= -1e-4) and np.all(coord <= np.array(source.shape)-1+1e-4)
            coord = np.clip(coord, 0, np.array(source.shape)-1)
            lo = np.floor(coord).astype(int)
            hi = np.minimum(lo+1, np.array(source.shape)-1)
            fraction = coord-lo
            expected = 0.0
            for corner in itertools.product((0,1), repeat=3):
                index = tuple(hi[a] if corner[a] else lo[a] for a in range(3))
                weight = np.prod([fraction[a] if corner[a] else 1-fraction[a] for a in range(3)])
                expected += source[index] * weight
            assert sliced.modality_pixels[y,x] == pytest.approx(expected, abs=.02)


@pytest.mark.parametrize('folder', T1_FOLDERS)
def test_local_view_measurement_window_and_mpr_layouts(scene, sample_root, tmp_path, folder):
    window, app, warnings = scene
    import_local(app, [sample_root/folder])
    ws = app.workspaceController
    uid = scan(sample_root/folder).series[0].series_instance_uid
    app.panelController.selectSeries(uid)
    click(window,find(window,'openView-2d'))
    ready(ws)
    view = ws.activeViewport
    for index in (0,34,17):
        view.apply_slice_index(index)
        wait_until(lambda: view._frame_meta.slice_index == index)
    pixels = view._modality_pixel.copy()
    context = view._measurement_context(2, 2, kind=MeasurementKind.RECT)
    measure = view.measurementController
    measure.begin(_position(100,80),context)
    measure.update(_drag(_position(100,80),_position(140,100)))
    measure.end(_position(140,100))
    metrics = measure.measurementItems[0]['metrics']
    assert metrics['width_mm'] == pytest.approx(40*1.015625)
    assert metrics['height_mm'] == pytest.approx(20*1.015625)
    assert metrics['mean'] == pytest.approx(pixels[80:101,100:141].mean(),abs=.001)
    assert metrics['unit'] == 'a.u.'
    view.applyWindowPreset(750,1500)
    view.toggleInverted()
    wait_until(lambda: view.current_window == WindowLevel(750,1500) and view.inverted)
    np.testing.assert_array_equal(view._modality_pixel,pixels)
    assert measure.measurementItems[0]['metrics'] == metrics
    single_tab = ws.activeTab
    uid = single_tab.tab_config.series_metas[0].series_uid
    ws.createTab(uid, 'MR', 'mpr')
    ready(ws)
    mpr = ws.activeTab
    for size in ((1000,650),(1400,900)):
        window.resize(*size)
        for layout in MPR_LAYOUTS:
            if layout == 'quad':
                continue
            mpr.mprLayout.setLayout(layout)
            QTest.qWait(35)
            for v in mpr.viewports_by_id.values():
                canvas=find(window,'imageViewport-'+v.viewportId)
                assert canvas.width()>20 and canvas.height()>20
    # Native 3D is verified separately; headless tests retain 2D layouts.
    assert any(item['value']=='quad' for item in mpr.mprLayout.options)
    # Repeated tab handoffs must not leave stale grid placements or reference tools.
    for _ in range(5):
        ws.openManual('mr')
        QTest.qWait(25)
        ws.createTab(uid,'MR','2d')
        ready(ws)
        ws.createTab(uid,'MR','mpr')
        ready(ws)
    assert window.grabWindow().save(str(tmp_path/(folder+'-mpr.png')))
    assert not warnings,warnings


def test_real_compare_independent_window_and_workspace_restore(scene, sample_root, tmp_path):
    window,app,warnings=scene
    import_local(app,[sample_root/f for f in T1_FOLDERS])
    ws=app.workspaceController
    uids=[scan(sample_root/f).series[0].series_instance_uid for f in T1_FOLDERS]
    ws.createCompareTab(*uids)
    ready(ws)
    tab=ws.activeTab
    left,right=tab.viewports_by_id.values()
    assert not tab.syncOperations['window'] and not tab.syncOperations['invert']
    original=right.current_window
    left.applyWindowPreset(500,1000)
    left.toggleInverted()
    wait_until(lambda:left.current_window==WindowLevel(500,1000) and left.inverted)
    assert right.current_window==original and not right.inverted
    tab.setScrollMode('relative')  # HFS and HFDR are different acquisitions/spaces.
    tab.setSliceIndex(17)
    wait_until(lambda:left._frame_meta.slice_index==17 and right._frame_meta.slice_index==17)
    manager=app.workspaceDocumentController
    path=tmp_path/'mr-comparison.voxworkspace'
    assert manager.save_to(path)
    wait_until(lambda:not manager.busy)
    assert not manager.isError,manager.message
    assert manager.restore_from(path)
    wait_until(lambda:not manager.busy,timeout=20000)
    assert not manager.isError,manager.message
    ready(ws)
    tab=ws.activeTab
    assert ws.activeTabType=='compare2d'
    left,right=tab.viewports_by_id.values()
    assert not tab.syncOperations['window'] and not tab.syncOperations['invert']
    assert left.current_window==WindowLevel(500,1000) and left.inverted
    assert right.current_window==original and not right.inverted
    assert left._frame_meta.slice_index==right._frame_meta.slice_index==17
    wait_until(lambda: all(any(i.objectName() == 'imageViewport-' + v.viewportId and i.isVisible() and i.width() > 0
                               for i in descendants(window.contentItem())) for v in (left,right)))
    QTest.qWait(150)
    assert window.grabWindow().save(str(tmp_path/'mr-compare-restored.png'))
    assert not warnings,warnings


@pytest.mark.parametrize('folder', ('90_Unsupported_Mosaic',))
def test_unsupported_local_import_has_reason_and_tag(scene,sample_root,folder):
    window,app,warnings=scene
    import_local(app,[sample_root/folder])
    series=scan(sample_root/folder).series[0]
    uid=series.series_instance_uid
    app.panelController.selectSeries(uid)
    QTest.qWait(80)
    for view in ('2d','montage','mpr','3d','4d'):
        assert find(window,'openView-'+view).isEnabled() == (view != '4d')
        assert app.panelController.seriesViewError(uid,view)
    ws=app.workspaceController
    ws.createTab(uid,'Unsupported MR','2d')
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status=='error')
    assert ws.activeTabType == '2d'
    assert 'Mosaic' in ws.activeLoadState.errorMessage
    assert not app.exportController.canExportPng
    assert find(window,'cancelWorkspaceLoad').isVisible()
    assert not any(i.objectName()=='retryWorkspaceLoad' for i in descendants(window.contentItem()))
    click(window,find(window,'openView-tag'))
    wait_until(lambda: ws.activeTabType=='tag')
    assert not warnings,warnings


def test_real_series_export_preserves_pixels_and_metadata(qt_app,sample_root,tmp_path):
    series=scan(sample_root/T1_FOLDERS[0]).series[0]
    paths=tuple(i.path for i in series.instances)
    result=export_series(ExportRequest(paths,tmp_path/'exports',anonymous=True))
    exported=scan(result.directory).series[0]
    assert len(exported.instances)==35
    for original,copy in zip(series.instances,exported.instances):
        source,output=pydicom.dcmread(original.path),pydicom.dcmread(copy.path)
        assert output.PatientIdentityRemoved=='YES'
        assert output.SOPClassUID==source.SOPClassUID and output.Modality=='MR'
        assert output.PixelData==source.PixelData
        assert output.ImagePositionPatient==source.ImagePositionPatient
        assert output.ImageOrientationPatient==source.ImageOrientationPatient
        assert output.RepetitionTime==source.RepetitionTime and output.EchoTime==source.EchoTime
    VolumeManager().get_or_build(exported)
    pngs=export_series(ExportRequest(paths,tmp_path/'exports',format='png'))
    files=sorted(pngs.directory.glob('*.png'))
    assert len(files)==35
    assert all(QImage(str(p)).width()==256 and QImage(str(p)).height()==256 for p in files)


def test_real_mouse_roi_and_current_view_export(scene,sample_root,tmp_path,monkeypatch):
    from test_measurement_qml import _scene, _mouse_drag
    window,app,warnings=scene
    uid=scan(sample_root/T1_FOLDERS[0]).series[0].series_instance_uid
    import_local(app,[sample_root/T1_FOLDERS[0]])
    ws=app.workspaceController
    ws.createTab(uid,'MR','2d')
    ready(ws)
    view=ws.activeViewport
    view.apply_slice_index(17)
    wait_until(lambda:view._frame_meta.slice_index==17)
    view._tool_controller.selectInteraction('measure:rect')
    wait_until(lambda:any(i.objectName()=='dicomPixelLayer' and i.isVisible() for i in descendants(window.contentItem())))
    layer=next(i for i in descendants(window.contentItem()) if i.objectName()=='dicomPixelLayer' and i.isVisible())
    assert not window.grabWindow().isNull()
    _mouse_drag(window,_scene(layer,110,90),_scene(layer,150,130))
    items=view.measurementController.measurementItems
    assert len(items)==1 and items[0]['metrics']['unit']=='a.u.'
    assert items[0]['metrics']['width_mm']==pytest.approx(40*1.015625,abs=1)
    assert any(i.objectName()=='roiMetricCard' and i.isVisible() for i in descendants(window.contentItem()))
    click(window,find(window,'primaryTool-export'))
    destination=tmp_path/'mr-current-view.png'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.export_controller.QFileDialog.getSaveFileName',lambda *args:(str(destination),'PNG'))
    click(window,find(window,'exportPng'))
    wait_until(lambda:not app.exportController.busy)
    assert not app.exportController.isError,app.exportController.message
    exported = QImage(str(destination))
    item = find(window, 'rightPanel').property('exportItem')
    assert not exported.isNull()
    assert exported.width() == round(item.width() * window.devicePixelRatio())
    assert exported.height() == round(item.height() * window.devicePixelRatio())
    # The entire opaque viewport must survive anonymous high-DPI export.
    assert exported.pixelColor(exported.width()-1, exported.height()-1).alpha() == 255
    assert view.measurementController.measurementItems==items
    assert not warnings,warnings


def test_real_mpr_projection_rotation_and_linked_window(scene,sample_root,tmp_path):
    window,app,warnings=scene
    uid=scan(sample_root/T1_FOLDERS[0]).series[0].series_instance_uid
    import_local(app,[sample_root/T1_FOLDERS[0]])
    ws=app.workspaceController
    ws.createTab(uid,'MR','mpr')
    ready(ws)
    tab=ws.activeTab
    views=list(tab.viewports_by_id.values())
    def settled():
        wait_until(lambda:not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids,timeout=10000)
    settled()
    originals=[v._modality_pixel.copy() for v in views]
    for plane in MprPlane:
        tab.toolController.setMprThickness(plane.value,10)
    tab.toolController.setMprProjectionEnabled(True)
    for mode in ('mip','minip','mean','sum'):
        tab.toolController.setMprProjectionMode(mode)
        settled()
        for view,original in zip(views,originals):
            values=view._modality_pixel
            assert values.shape==original.shape and np.isfinite(values).any()
            if mode=='mip':
                assert np.nanmin(values-original)>=-.01
            if mode=='minip':
                assert np.nanmax(values-original)<=.01
    tab.toolController.resetMprProjection()
    settled()
    for v,original in zip(views,originals):
        np.testing.assert_allclose(v._modality_pixel,original,equal_nan=True)
    center=tab._target_mpr_state.frame.center_patient
    tab._handle_mpr_3d_rotation_requested((0,0,1),np.deg2rad(17))
    settled()
    assert tab._target_mpr_state.frame.center_patient==center
    assert all(v._plane_geometry.frame==tab._target_mpr_state.frame for v in views)
    views[0].applyWindowPreset(450,900)
    views[0].toggleInverted()
    settled()
    assert all(v.current_window==WindowLevel(450,900) and v.inverted for v in views)
    assert all(v._frame_meta.pixel_value_meta.unit=='a.u.' for v in views)
    assert window.grabWindow().save(str(tmp_path/'mr-oblique-mpr.png'))
    assert not warnings,warnings
