"""Classic MR support: source values, display semantics and reconstruction gates."""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset, Dataset
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian, MRImageStorage, EnhancedMRImageStorage, RLELossless, generate_uid

from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.export_images import frame_image
from qt_dicom_viewer.core.mr import automatic_mr_window, mr_series_error, mr_view_error, read_mr_parameters
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.core.compare import supports_compare
from qt_dicom_viewer.model import (DicomFolderScanSnapshot, MprPlane, TabType, TabConfig, ToolType,
    WindowLevel, StackRenderRequest, MontageRenderRequest, MprRenderRequest, SeriesDisplayMeta)
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from qt_dicom_viewer.ui.controller.tab.tab_controller import TabController
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController, tool_available
from qt_dicom_viewer.ui.controller.tab.compare_tab_controller import CompareTabController
from qt_dicom_viewer.ui.controller.viewport.operation.window_level_operation import WindowLevelOperation, MR_WINDOW_LEVEL_CONFIG
from qt_dicom_viewer.model import Point, PointerPosition, Offset, DragUpdateEvent
from qt_dicom_viewer.model.interaction import WindowLevelContext
from test_dicom_tags import qt_app


def mr_dataset(pixels=None):
    pixels = np.asarray(pixels if pixels is not None else np.arange(64*64).reshape(64,64), dtype=np.int16)
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(None, {}, file_meta=meta, preamble=bytes(128))
    ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = [generate_uid() for _ in range(3)]
    ds.PatientName, ds.PatientID = 'SYNTHETIC^MR', 'MR-TEST'
    ds.Modality, ds.SeriesDescription = 'MR', 'Synthetic T2'
    ds.ImageType = ['ORIGINAL', 'PRIMARY', 'M']
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16,16,15,1
    ds.PixelData = pixels.tobytes()
    ds.RescaleSlope, ds.RescaleIntercept = 1,0
    ds.PixelSpacing, ds.SliceThickness = [0.8,0.8], 2
    ds.ImageOrientationPatient, ds.ImagePositionPatient = [1,0,0,0,1,0], [0,0,0]
    ds.RepetitionTime, ds.EchoTime, ds.FlipAngle, ds.MagneticFieldStrength = 3000,80,90,3
    return ds


def write_mr_series(directory, count=4, *, change=None):
    directory.mkdir(parents=True, exist_ok=True)
    study, series, frame = [generate_uid() for _ in range(3)]
    for i in range(count):
        ds = mr_dataset()
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study,series,frame
        ds.ImagePositionPatient, ds.InstanceNumber = [0,0,2*i], count-i
        if change:
            change(ds,i)
        ds.save_as(directory/f'{i}.dcm', enforce_file_format=True)
    return list(DicomFolderScanner().scan(directory))[-1].series[0]


@pytest.mark.parametrize('encoding', [ExplicitVRLittleEndian, ImplicitVRLittleEndian, RLELossless])
def test_classic_mr_decode_rescale_padding_units_and_export(tmp_path, encoding):
    ds=mr_dataset([[-30000,0],[100,200]])
    ds.PixelPaddingValue=-30000
    ds.RescaleSlope, ds.RescaleIntercept = .001,-.1
    if encoding == RLELossless:
        ds.compress(encoding, generate_instance_uid=False)
    else:
        ds.file_meta.TransferSyntaxUID=encoding
    path=tmp_path/'image.dcm'
    ds.save_as(path,enforce_file_format=True)
    ds=pydicom.dcmread(path)
    result=DicomLoader().load_dataset(ds,None,False)
    assert np.isnan(result.modality_pixel[0,0])
    np.testing.assert_allclose(result.modality_pixel[1], [0,.1], atol=1e-7)
    assert result.pixel_value_meta.unit == 'a.u.'
    assert 0 < result.window.width < 1
    assert result.image[0,0] == 0 and result.image[1,1] == 255
    from qt_dicom_viewer.core.series_thumbnail import read_series_thumbnail
    thumbnail=read_series_thumbnail(path)
    assert thumbnail.pixelColor(0,0).red()==0
    assert thumbnail.pixelColor(thumbnail.width()-1,thumbnail.height()-1).red()==255
    exported=frame_image(ds.pixel_array,ds)
    for y in range(2):
        for x in range(2):
            assert exported.pixelColor(x,y).red() == result.image[y,x]


def test_mr_window_priority_and_source_polarity_do_not_change_values():
    ds=mr_dataset([[0,100],[200,300]])
    ds.WindowCenter, ds.WindowWidth = [150,200],[300,400]
    loader=DicomLoader()
    source=loader.load_dataset(ds,None,False)
    assert source.window == WindowLevel(150,300)
    ds.PhotometricInterpretation='MONOCHROME1'
    negative=loader.load_dataset(ds,None,False)
    inverted=loader.load_dataset(ds,None,True)
    np.testing.assert_allclose(negative.image.astype(int)+source.image,255,atol=1)
    np.testing.assert_array_equal(inverted.image,source.image)
    np.testing.assert_array_equal(negative.modality_pixel,source.modality_pixel)
    assert not negative.inverted and inverted.inverted
    assert loader.load_dataset(ds,WindowLevel(70,80),False).window == WindowLevel(70,80)
    ds.WindowWidth=0
    assert loader.load_dataset(ds,None,False).window.width > 200


def test_auto_window_constant_padding_and_ct_fallback():
    for pixels in (np.full((4,4),np.nan), np.ones((4,4)), np.zeros((4,4))):
        value=automatic_mr_window(pixels)
        assert np.isfinite([value.center,value.width]).all() and value.width>0
    ds=mr_dataset(); ds.Modality='CT'
    result=DicomLoader().load_dataset(ds,None,False)
    assert result.window == WindowLevel(40,400) and result.pixel_value_meta.unit == 'HU'


def test_source_units_and_mr_parameters_are_preserved():
    ds=mr_dataset(); ds.RescaleType='ADC'; ds.InversionTime=1200
    diffusion=Dataset(); diffusion.DiffusionBValue=1000
    ds.MRDiffusionSequence=[diffusion]
    result=DicomLoader().load_dataset(ds,None,False)
    assert result.pixel_value_meta.unit == 'ADC'
    assert result.instance_meta.mr_parameters.b_value == 1000
    assert result.instance_meta.mr_parameters.inversion_time == 1200


def test_oblique_mr_builds_volume_and_all_mpr_planes(tmp_path):
    def oblique(ds,i):
        ds.ImageOrientationPatient=[1,0,0,0,.8,.6]
        ds.ImagePositionPatient=[0,-1.2*i,1.6*i]
    series=write_mr_series(tmp_path,change=oblique)
    assert not mr_series_error(series,volume=True)
    assert series.instances[0].instance_number == 4  # spatial, not instance-number order
    volume=VolumeManager().get_or_build(series)
    assert volume.modality_pixels.shape == (4,64,64)
    assert volume.geometry.slice_spacing == pytest.approx(2)
    assert volume.pixel_value_meta.unit == 'a.u.'
    for plane in MprPlane:
        result=MprReslicer().reslice(volume,plane)
        assert np.isfinite(result.modality_pixels).any()


@pytest.mark.parametrize('kind', ['echo','bvalue','time','component','position','orientation','spacing','localizer','frames','enhanced','color','mosaic'])
def test_mr_eligibility_rejects_ambiguous_volumes_and_unsupported_formats(tmp_path,kind):
    def change(ds,i):
        if kind=='mosaic': ds.ImageType=['ORIGINAL','PRIMARY','M','MOSAIC']
        if kind=='localizer': ds.ImageType=['ORIGINAL','PRIMARY','LOCALIZER']
        if i!=1: return
        if kind=='echo': ds.EchoTime=100
        if kind=='bvalue': ds.DiffusionBValue=1000
        if kind=='time': ds.TemporalPositionIdentifier=2
        if kind=='component': ds.ComplexImageComponent='PHASE'
        if kind=='position': ds.ImagePositionPatient=[0,0,0]
        if kind=='orientation': ds.ImageOrientationPatient=[1,0,0,0,0,1]
        if kind=='spacing': ds.PixelSpacing=[1,1]
        if kind=='frames': ds.NumberOfFrames=2
        if kind=='enhanced': ds.SOPClassUID=EnhancedMRImageStorage
        if kind=='color': ds.PhotometricInterpretation='RGB'; ds.SamplesPerPixel=3
    series=write_mr_series(tmp_path,change=change)
    records=list(DicomFolderScanner().scan(tmp_path))[-1].series
    series=replace(series,instances=tuple(i for r in records for i in r.instances))
    assert mr_view_error(series,'mpr')
    with pytest.raises(ValueError): VolumeManager().get_or_build(series)
    assert not mr_view_error(series,'tag')
    if kind in ('frames','enhanced','color','mosaic'):
        assert mr_view_error(series,'2d') and not supports_compare(series)
    else:
        assert not mr_view_error(series,'2d') and supports_compare(series)


def test_mr_series_are_not_linked_as_ct_four_d(tmp_path):
    a=write_mr_series(tmp_path/'a',change=lambda ds,i:setattr(ds,'SeriesDescription','T2 phase1'))
    def second(ds,i):
        ds.StudyInstanceUID=a.study_instance_uid
        ds.FrameOfReferenceUID=a.frame_of_reference_uid
        ds.SeriesDescription='T2 phase2'
    write_mr_series(tmp_path/'b',change=second)
    result=list(DicomFolderScanner().scan(tmp_path))[-1]
    assert len(result.series)==2 and not any(r.supports_four_d for r in result.series)


def test_worker_stack_montage_and_mpr_share_mr_display(tmp_path,qt_app):
    def change(ds,i):
        ds.PhotometricInterpretation='MONOCHROME1'
        ds.RescaleSlope=.0001
    series=write_mr_series(tmp_path,change=change)
    catalog=SeriesCatalog(); catalog.update(DicomFolderScanSnapshot(tmp_path,4,4,0,[series]))
    worker=DicomRenderWorker(catalog,VolumeManager()); results=[]; failures=[]
    worker.render_finished.connect(results.append); worker.render_failed.connect(failures.append)
    args=dict(request_id='r',viewport_id='v',series_uid=series.series_instance_uid,window=None,inverted=False)
    worker.handleRenderRequest(StackRenderRequest(**args,slice_index=0))
    worker.handleRenderRequest(MontageRenderRequest(**args,slice_index=0))
    worker.handleRenderRequest(MprRenderRequest(**args,plane=MprPlane.AXIAL,mpr_frame=None))
    assert not failures and len(results)==3
    np.testing.assert_array_equal(results[0].image,results[1].image)
    for result in results:
        assert 0<result.frame_meta.window.width<1
        assert result.frame_meta.pixel_value_meta.unit=='a.u.'
        assert result.frame_meta.instance_meta.mr_parameters.echo_time==80


def test_mr_tools_window_link_and_compare_defaults(qt_app):
    meta=SeriesDisplayMeta('MR','1','','T2','MR','mr')
    tab=TabController(TabConfig('mr','MR',TabType.MPR,(meta,)))
    try:
        assert tab._link_mpr_windows
        assert any(item['value']=='quad' for item in tab.mprLayout.options)
        view=tab.activeViewport
        assert view.supportsGrayscaleWindow and not view.supportsCtWindow
        assert view.minimumWindowWidth==.001 and view.windowPresets==[]
        view.applyWindowPreset(.1,.2)
        assert all(v.current_window == WindowLevel(.1,.2) for v in tab.viewports_by_id.values())
        view.toggleInverted()
        assert all(v.inverted for v in tab.viewports_by_id.values())
        for tool in (ToolType.VOI,ToolType.SERVICE):
            assert not tool_available(tool,TabType.MPR,'MR')
        assert tool_available(ToolType.MEASURE,TabType.MPR,'MR')
        assert tool_available(ToolType.SEGMENTATION,TabType.MPR,'MR')
        assert tool_available(ToolType.IMPORT,TabType.MPR,'MR')
        tab.toolController.activateTool('segmentation')
        assert tab.toolController.activePanel == 'segmentation'
        assert tab.toolController.activeInteraction == 'mpr:segmentation'
        assert not tab.voiController.canDraw
        for interaction in ('service:qa','service:mtf','service:fwhm','mpr:voi'):
            tab.toolController.selectInteraction(interaction)
            assert tab.toolController.activeInteraction!=interaction
    finally: tab.dispose()
    compare=CompareTabController(TabConfig('compare','MR',TabType.COMPARE_2D,(meta,replace(meta,series_uid='other'))))
    try:
        assert compare.syncOperations['scroll']
        assert not compare.syncOperations['window'] and not compare.syncOperations['invert']
    finally: compare.dispose()


@pytest.mark.parametrize('width',[.01,100000.0])
def test_mr_drag_scales_with_signal_range(width):
    operation=WindowLevelOperation(MR_WINDOW_LEVEL_CONFIG)
    point=PointerPosition(Point(0,0),None)
    operation.begin(point,WindowLevelContext((100,100),False,WindowLevel(0,width)))
    result=operation.update(DragUpdateEvent(point,point,Offset(10,0),Offset(10,0)))
    assert result.window.width == pytest.approx(width*1.1,abs=.0005)



@pytest.mark.parametrize('field,value',[('WindowCenter','nan'),('WindowWidth','inf'),('WindowWidth',-5)])
def test_invalid_mr_window_uses_finite_signal_range(field,value):
    ds=mr_dataset(); ds.WindowCenter=100; ds.WindowWidth=200
    if value in ('nan','inf'):
        with pytest.warns(UserWarning, match='Invalid value for VR DS'):
            setattr(ds,field,value)
    else:
        setattr(ds,field,value)
    result=DicomLoader().load_dataset(ds,None,False)
    assert np.isfinite([result.window.center,result.window.width]).all()
    assert result.window.width>3000


def test_mr_workspace_restores_window_inversion_measurement_and_metadata(qt_app,tmp_path):
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from test_workspace_persistence import draw_length
    from test_dicom_tags import wait_until
    series=write_mr_series(tmp_path/'images')
    app=AppController(DicomImageProvider(),settings_path=tmp_path/'settings.json')
    try:
        app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path,4,4,0,[series]))
        wait_until(lambda: app.workspaceController.activeViewport.loadState=='ready')
        view=app.workspaceController.activeViewport
        mid=draw_length(view)
        view.applyWindowPreset(.1,.2); view.toggleInverted()
        wait_until(lambda: view._frame_meta.window==WindowLevel(.1,.2) and view._frame_meta.inverted)
        app.workspaceController.activeTab.historyController.capture()
        manager=app.workspaceDocumentController; path=tmp_path/'mr.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda:not manager.busy)
        assert not manager.isError,manager.message
        assert manager.restore_from(path)
        wait_until(lambda:not manager.busy,20000)
        assert not manager.isError,manager.message
        restored=app.workspaceController.activeViewport
        wait_until(lambda:restored.loadState=='ready')
        assert restored.current_window==WindowLevel(.1,.2) and restored.inverted
        assert restored._measure_controller._measurements[mid].length_mm==8
        assert restored._frame_meta.pixel_value_meta.unit=='a.u.'
        assert restored._frame_meta.instance_meta.mr_parameters.echo_time==80
    finally: app.shutdown()


def test_mosaic_pixels_are_not_exposed_as_an_anatomical_slice():
    ds=mr_dataset(); ds.ImageType=['ORIGINAL','PRIMARY','MOSAIC']
    with pytest.raises(ValueError,match='Mosaic'):
        DicomLoader().load_dataset(ds,None,False)
