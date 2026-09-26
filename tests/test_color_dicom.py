"""Color DICOM: exact source color, frame identity and no scalar quantification."""
from pathlib import Path
from dataclasses import replace
import numpy as np
import pytest
import pydicom
from pydicom.uid import SecondaryCaptureImageStorage, generate_uid
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_mr import mr_dataset
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.export_images import frame_image
from qt_dicom_viewer.core.pixel_codecs import decode_pixels
from qt_dicom_viewer.core.display_mapping import map_display
from qt_dicom_viewer.core.volume_manager import VolumeManager, VolumeBuildError
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.model import WindowLevel, StackRenderRequest, MontageRenderRequest, TabType
from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController


def color_dataset(kind='RGB', frames=1, calibrated=False):
    ds = mr_dataset(np.zeros((32, 48), np.int16))
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.Modality = 'OT'
    ds.SeriesDescription = 'Synthetic color ' + kind
    ds.PhotometricInterpretation = kind
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    # These must never be applied to color channels / palette indices.
    ds.RescaleSlope, ds.RescaleIntercept = 2, -1024
    for key in ('ImageOrientationPatient', 'ImagePositionPatient', 'PixelSpacing'):
        del ds[key]
    if calibrated:
        ds.PixelSpacing = [0.5, 0.75]
    if kind == 'PALETTE COLOR':
        ds.SamplesPerPixel = 1
        pixels = np.zeros((frames,32,48), np.uint8)
        pixels[:,:,24:] = 1
        for channel,values in [('Red',[255,0]),('Green',[0,255]),('Blue',[0,0])]:
            setattr(ds, channel+'PaletteColorLookupTableDescriptor', [2,0,8])
            setattr(ds, channel+'PaletteColorLookupTableData', bytes(values))
    else:
        ds.SamplesPerPixel, ds.PlanarConfiguration = 3, 0
        pixels = np.zeros((frames,32,48,3), np.uint8)
        pixels[:,:,:24] = [255,0,0] if kind == 'RGB' else [76,85,255]
        pixels[:,:,24:] = [0,255,0] if kind == 'RGB' else [150,44,21]
        if frames > 1:
            pixels[1] = [0,0,255]
    if frames > 1:
        ds.NumberOfFrames = frames
    ds.PixelData = pixels.tobytes()
    return ds


def scan_color(tmp_path, **kwargs):
    ds = color_dataset(**kwargs)
    path = tmp_path/'color.dcm'
    ds.save_as(path, enforce_file_format=True)
    snapshot = list(DicomFolderScanner().scan(tmp_path))[-1]
    return ds, path, snapshot


@pytest.mark.parametrize('kind', ['RGB', 'YBR_FULL', 'PALETTE COLOR'])
def test_color_exact_source_export_and_stale_window(tmp_path, kind):
    ds,path,snapshot = scan_color(tmp_path,kind=kind)
    loader = DicomLoader()
    header, pixels = loader.read_frame(path)
    result = loader.load_dataset(header, WindowLevel(-100,1), True, modality_pixels=pixels)
    assert result.image.shape == (32,48,3) and result.image.dtype == np.uint8
    assert result.modality_pixel is None and not result.inverted
    assert result.pixel_value_meta.quantification == 'color'
    np.testing.assert_allclose(result.image[0,0], [255,0,0],atol=1)
    np.testing.assert_allclose(result.image[0,47], [0,255,0],atol=1)
    image = frame_image(decode_pixels(path), header)
    assert image.pixelColor(0,0).getRgb()[:3] == tuple(result.image[0,0])
    np.testing.assert_array_equal(map_display(result.image,None,result.pixel_value_meta,
        intent=DisplayMappingIntent('custom',-100,100,''),color_map='hot-iron'),result.image)
    catalog = SeriesCatalog(); catalog.update(snapshot)
    meta = catalog.get_series_display_meta(snapshot.series[0].series_instance_uid)
    assert meta.is_color and not meta.supports_ct_analysis and not meta.color_calibrated


def test_palette_16_bit_output_and_planar_rgb(tmp_path):
    ds = color_dataset('PALETTE COLOR')
    for channel, values in [('Red',[65535,0]),('Green',[0,65535]),('Blue',[0,0])]:
        setattr(ds, channel+'PaletteColorLookupTableDescriptor',[2,0,16])
        setattr(ds, channel+'PaletteColorLookupTableData',np.array(values,dtype='<u2').tobytes())
    result = DicomLoader().load_dataset(ds,None,False)
    np.testing.assert_array_equal(result.image[0,0],[255,0,0])
    ds = color_dataset()
    original = decode_pixels(ds).copy()
    ds.PlanarConfiguration = 1
    ds.PixelData = original.transpose(2,0,1).tobytes()
    np.testing.assert_array_equal(DicomLoader().load_dataset(ds,None,False).image,original)


def test_multiframe_worker_frame_identity_and_montage(qt_app,tmp_path):
    ds,path,snapshot = scan_color(tmp_path,frames=2)
    series = snapshot.series[0]
    assert len(series.instances) == 2
    assert [i.frame_index for i in series.instances] == [0,1]
    catalog = SeriesCatalog();catalog.update(snapshot)
    worker = DicomRenderWorker(catalog,VolumeManager())
    results,errors = [],[]
    worker.render_finished.connect(results.append,Qt.DirectConnection)
    worker.render_failed.connect(errors.append,Qt.DirectConnection)
    for cls in (StackRenderRequest,MontageRenderRequest):
        for index in (0,1,0):
            worker.handleRenderRequest(cls(request_id=str(index),viewport_id='v',series_uid=series.series_instance_uid,
                                          slice_index=index,window=None,inverted=False))
            assert not errors,errors
            r=results[-1]
            assert r.frame_meta.instance_meta.frame_index == index
            np.testing.assert_array_equal(r.image[0,0],[0,0,255] if index else [255,0,0])
            assert r.modality_pixel is None
    with pytest.raises(VolumeBuildError):
        VolumeManager()._build_volume(series)


@pytest.mark.parametrize('calibrated',[False,True])
def test_color_tool_gates_and_restore(qt_app,calibrated):
    tool = ToolController(tab_type=TabType.TWO_D,modality='OT',is_color=True,color_calibrated=calibrated)
    actions={i['toolType'] for i in tool.tools}
    assert {'pan','zoom','rotate','export','annotate'} <= actions
    assert not {'window','pseudocolor','service','segmentation','voi'} & actions
    assert ('measure' in actions) == calibrated
    assert tool.activeInteraction == 'pan'
    tool.activateTool('window');tool.selectInteraction('window');tool.selectService('service:mtf')
    tool.restore_selection(dict(version=1,tool='window',interaction='window'))
    assert tool.activeInteraction == 'pan'


def test_color_real_qml_switch_frames_and_export(scene,tmp_path):
    window,app,warnings = scene
    ds,path,snapshot = scan_color(tmp_path,frames=2)
    app.panelController.acceptPacsImport(snapshot)
    work = app.workspaceController
    wait_until(lambda: work.activeViewport is not None and work.activeViewport.loadState == 'ready')
    view=work.activeViewport
    assert view.imageSource and view._modality_pixel is None
    assert not view.showScaleBar and not view.supportsCtWindow
    assert view._frame_meta.pixel_value_meta.quantification == 'color'
    view.setSliceIndex(1)
    wait_until(lambda: view.loadState == 'ready' and view._frame_meta.slice_index == 1)
    assert view._frame_meta.instance_meta.frame_index == 1
    assert window.grabWindow().save(str(tmp_path/'color-frame-blue.png'))
    view.setSliceIndex(0)
    wait_until(lambda: view.loadState == 'ready' and view._frame_meta.slice_index == 0)
    assert window.grabWindow().save(str(tmp_path/'color-frame-red-green.png'))
    assert not warnings,warnings


def test_color_workspace_restores_frame_and_calibrated_measurement(qt_app,tmp_path):
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from test_workspace_persistence import draw_length
    ds,path,snapshot = scan_color(tmp_path,frames=2,calibrated=True)
    app = AppController(DicomImageProvider(),settings_path=False)
    try:
        app.panelController.acceptPacsImport(snapshot)
        work = app.workspaceController
        wait_until(lambda: work.activeViewport is not None and work.activeViewport.loadState == 'ready')
        view=work.activeViewport
        view.setSliceIndex(1)
        wait_until(lambda: view.loadState == 'ready' and view._frame_meta.slice_index == 1)
        mid=draw_length(view)
        assert view._measure_controller._measurements[mid].length_mm == 7.5
        from threading import Event
        from qt_dicom_viewer.ui.controller.measurement_report_controller import capture_results
        from qt_dicom_viewer.ui.report_reference_images import render_references
        rows,pictures,_ = capture_results(work,app._series_catalog,include_images=True,anonymous=False)
        images,errors = render_references(pictures,app._series_catalog,Event(),lambda _:None)
        assert len(images) == 1 and not errors
        assert images[0][1].pixelColor(20,20).getRgb()[:3] == (0,0,255)
        tool=work.activeTab.toolController
        tool.activateTool('measure');tool.selectInteraction('measure:curve')
        manager=app.workspaceDocumentController
        dest=tmp_path/'color.voxworkspace'
        assert manager.save_to(dest)
        wait_until(lambda: not manager.busy)
        assert not manager.isError,manager.message
        assert manager.restore_from(dest)
        wait_until(lambda: not manager.busy,timeout=20000)
        assert not manager.isError,manager.message
        restored=work.activeViewport
        wait_until(lambda: restored.loadState == 'ready')
        assert restored._frame_meta.instance_meta.frame_index == 1
        assert restored._frame_meta.pixel_value_meta.quantification == 'color'
        assert restored._modality_pixel is None
        assert restored._measure_controller._measurements[mid].length_mm == 7.5
        assert work.activeTab.toolController.activeInteraction == 'measure:curve'
        assert not work.activeTab.playing
    finally:
        app.shutdown()


def test_mixed_2d_layout_updates_color_tools(scene,tmp_path):
    from test_mr import write_mr_series
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window,app,warnings=scene
    ds,path,snapshot=scan_color(tmp_path)
    app.panelController.acceptPacsImport(snapshot)
    work=app.workspaceController
    wait_until(lambda: work.activeViewport is not None and work.activeViewport.loadState == 'ready')
    tab=work.activeTab; layout=tab.twoDLayout
    gray=write_mr_series(tmp_path/'gray')
    extra=DicomFolderScanSnapshot(tmp_path,4,4,0,[gray])
    app.panelController.update_series_session(extra);app.panelController._update_series_record(extra)
    layout.setLayout('2x2');assert layout.loadSeries(1,gray.series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    assert 'window' in {i['toolType'] for i in tab.toolController.tools}
    tab.toolController.activateTool('window')
    layout.activateCell(0)
    assert tab.toolController.activeInteraction == 'pan'
    assert 'window' not in {i['toolType'] for i in tab.toolController.tools}
    layout.activateCell(1)
    assert 'window' in {i['toolType'] for i in tab.toolController.tools}
    assert not warnings,warnings
