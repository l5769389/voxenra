"""Enhanced frame identity, dimensions, patient geometry and source fidelity."""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset
from pydicom.uid import EnhancedMRImageStorage, LegacyConvertedEnhancedMRImageStorage, RLELossless
from PySide6.QtGui import QImage

from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.mr import mr_series_error, mr_view_error
from voxplane.core.mr_frames import frame_metadata
from voxplane.core.volume_manager import VolumeManager
from voxplane.core.compare import plane_center, nearest_patient_slice, reference_line, compatible_patient_space
from voxplane.core.series_export import ExportRequest, export_series
from voxplane.core.export_images import frame_image
from voxplane.core.workspace_document import read_document
from voxplane.model import PixelSpacing, SeriesDisplayMeta, WindowLevel
from voxplane.ui.workers.dicom_scan_worker import DicomScanWorker
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from test_mr import mr_dataset
from test_dicom_tags import qt_app, wait_until


def item(**fields):
    d=Dataset()
    for key,value in fields.items(): setattr(d,key,value)
    return d


def enhanced_dataset():
    d=mr_dataset(np.arange(64).reshape(8,8))
    d.SOPClassUID=d.file_meta.MediaStorageSOPClassUID=EnhancedMRImageStorage
    for key in ('ImagePositionPatient','ImageOrientationPatient','PixelSpacing','SliceThickness','EchoTime','RepetitionTime'):
        delattr(d,key)
    d.SharedFunctionalGroupsSequence=[item(
        PixelMeasuresSequence=[item(PixelSpacing=[.8,.8],SliceThickness=2)],
        PlaneOrientationSequence=[item(ImageOrientationPatient=[1,0,0,0,1,0])],
        MRTimingAndRelatedParametersSequence=[item(RepetitionTime=2000,FlipAngle=90)],
        PixelValueTransformationSequence=[item(RescaleSlope=10,RescaleIntercept=-5,RescaleType='US')])]
    d.DimensionIndexSequence=[item(DimensionIndexPointer=tag,FunctionalGroupPointer=fg) for tag,fg in
                              ((0x00209057,0x00209111),(0x00209128,0x00209111),(0x00189082,0x00189114))]
    frames=[]; pixels=[]
    for t in range(2):
        for z in (2,0,1):  # Deliberately interleaved echoes and unsorted slices.
            for echo in range(2):
                f=len(frames)
                frames.append(item(
                    FrameContentSequence=[item(StackID='1',InStackPositionNumber=z+1,TemporalPositionIndex=t+1,
                                               DimensionIndexValues=[z+1,t+1,echo+1])],
                    PlanePositionSequence=[item(ImagePositionPatient=[0,0,2*z])],
                    MREchoSequence=[item(EffectiveEchoTime=10.+20*echo)],
                    MRImageFrameTypeSequence=[item(FrameType=['ORIGINAL','PRIMARY','T2','NONE'],ComplexImageComponent='MAGNITUDE')],
                    PixelValueTransformationSequence=[item(RescaleSlope=.001*(f+1),RescaleIntercept=-.1*f,RescaleType='US')],
                    FrameVOILUTSequence=[item(WindowCenter=.01*f,WindowWidth=.02*(f+1))]))
                pixels.append(np.arange(64,dtype=np.int16).reshape(8,8)+100*f)
    d.PerFrameFunctionalGroupsSequence=frames
    d.NumberOfFrames=len(frames)
    d.PixelData=np.stack(pixels).tobytes()
    return d


def save_and_scan(tmp_path,d=None):
    d=enhanced_dataset() if d is None else d
    path=tmp_path/'enhanced.dcm'
    d.save_as(path,enforce_file_format=True)
    snapshot=list(DicomFolderScanner().scan_files([path],folder=tmp_path,can_publish=lambda:False))[-1]
    return path,snapshot


@pytest.mark.parametrize('storage,compressed', [(EnhancedMRImageStorage,False),(LegacyConvertedEnhancedMRImageStorage,False),(EnhancedMRImageStorage,True)])
def test_frames_decode_scale_window_and_sort_independently(tmp_path,storage,compressed):
    d=enhanced_dataset();d.SOPClassUID=d.file_meta.MediaStorageSOPClassUID=storage
    raw=d.pixel_array.copy()
    if compressed:d.compress(RLELossless,generate_instance_uid=False)
    path,s=save_and_scan(tmp_path,d)
    assert s.dicom_file_count==1 and s.skipped_file_count==0 and len(s.series)==4
    loader=DicomLoader();identities=[]
    for series in s.series:
        assert len(series.instances)==3 and not mr_series_error(series,volume=True)
        assert [i.image_position_patient[2] for i in series.instances]==[0,2,4]
        assert len({i.mr_parameters for i in series.instances})==1
        volume=VolumeManager().get_or_build(series)
        for z,i in enumerate(series.instances):
            f=i.frame_index; identities.append(i.frame_identity)
            metadata,pixels=loader.read_frame(path,f)
            expected=raw[f]*(.001*(f+1))-.1*f
            np.testing.assert_allclose(pixels,expected,atol=1e-6)
            np.testing.assert_array_equal(volume.modality_pixels[z],pixels)
            rendered=loader.load_dataset(metadata,None,False,modality_pixels=pixels)
            assert rendered.instance_meta.frame_index==f
            assert rendered.instance_meta.sop_instance_uid==d.SOPInstanceUID
            assert rendered.window==WindowLevel(.01*f,.02*(f+1))
    assert len(set(identities))==12
    assert d.SharedFunctionalGroupsSequence[0].PixelValueTransformationSequence[0].RescaleSlope==10
    assert 'EchoTime' not in d and 'ImagePositionPatient' not in d


@pytest.mark.parametrize('defect',['count','position','dimension','spacing','cardinality'])
def test_malformed_enhanced_retains_tags_but_cannot_render(tmp_path,defect):
    d=enhanced_dataset()
    if defect=='count':d.NumberOfFrames=13
    if defect=='position':del d.PerFrameFunctionalGroupsSequence[1].PlanePositionSequence
    if defect=='dimension':d.PerFrameFunctionalGroupsSequence[1].FrameContentSequence[0].DimensionIndexValues=[1]
    if defect=='spacing':d.SharedFunctionalGroupsSequence[0].PixelMeasuresSequence[0].PixelSpacing=[0,.8]
    if defect=='cardinality':d.PerFrameFunctionalGroupsSequence[1].MREchoSequence.append(item(EffectiveEchoTime=30.))
    _,s=save_and_scan(tmp_path,d)
    assert s.dicom_file_count==1 and len(s.series)==1
    assert mr_view_error(s.series[0],'2d') and not mr_view_error(s.series[0],'tag')


def test_group_ids_and_frames_survive_duplicate_incremental_import(tmp_path):
    path,s=save_and_scan(tmp_path)
    reverse=list(DicomFolderScanner().scan_files([path,path],folder=tmp_path))[-1]
    assert reverse.series==s.series
    worker=DicomScanWorker([path],base_series={r.series_instance_uid:replace(r,instances=r.instances[:1]) for r in s.series})
    merged=worker._merge_snapshot(s)
    assert {r.series_instance_uid:len(r.instances) for r in merged.series}=={r.series_instance_uid:3 for r in s.series}
    assert sum(len(r.instances) for r in merged.series)==12
    assert merged.existing_file_count == 0  # The file adds missing frames.
    complete = DicomScanWorker([path], base_series={r.series_instance_uid: r for r in merged.series})
    assert complete._merge_snapshot(s).existing_file_count == 1  # One file, not twelve frames/four groups.


def test_selected_group_png_and_complete_dicom_source_export(tmp_path,qt_app):
    path,s=save_and_scan(tmp_path)
    series=s.series[0]; refs=tuple((i.path,i.frame_index) for i in series.instances)
    request=ExportRequest(tuple(i.path for i in series.instances),tmp_path/'exports','png',True,refs)
    result=export_series(request)
    assert result.file_count==3
    d=pydicom.dcmread(path);raw=d.pixel_array
    for _,f in refs:
        png=QImage(str(result.directory/f'instance-000001-frame-{f+1:06d}.png'))
        expected=frame_image(raw[f],d,f)
        assert png==expected
    result=export_series(replace(request,format='dicom'))
    assert result.file_count==1
    exported=pydicom.dcmread(next(result.directory.glob('*.dcm')))
    assert exported.NumberOfFrames==12 and exported.SOPClassUID==d.SOPClassUID
    np.testing.assert_array_equal(exported.pixel_array,raw)
    assert str(exported.PatientName)!=str(d.PatientName)


def test_spatial_navigation_matches_positions_not_relative_progress():
    def planes(zs):return tuple(((0,0,z),(1,0,0,0,1,0),PixelSpacing(1,1),11,11) for z in zs)
    a,b=planes([0,2,4,6,8]),planes([0,4,8,12,16])
    assert nearest_patient_slice(plane_center(a[2]),b,(0,0,1))==1
    assert nearest_patient_slice((5,5,99),b,(0,0,1)) is None
    assert nearest_patient_slice((100,5,4),b,(0,0,1)) is None
    assert nearest_patient_slice((5,5,4),b,(1,0,0)) is None
    sagittal=((3,0,0),(0,1,0,0,0,1),PixelSpacing(1,1),11,11)
    line=reference_line(sagittal,a[2]);assert line in ((3.,0.,3.,10.),(3.,10.,3.,0.))
    m=SeriesDisplayMeta('MR','1','','MR','MR','one',study_uid='study',frame_of_reference_uid='space')
    assert compatible_patient_space(m,replace(m,series_uid='two'))
    assert not compatible_patient_space(m,replace(m,frame_of_reference_uid=''))
    assert not compatible_patient_space(m,replace(m,frame_of_reference_uid='other'))


def test_enhanced_four_series_compare_and_workspace_preserve_every_frame(qt_app,tmp_path):
    path,s=save_and_scan(tmp_path)
    app=AppController(DicomImageProvider(),settings_path=tmp_path/'settings.json')
    try:
        app.panelController.update_series_session(s);app.panelController._update_series_record(s)
        app.workspaceController.createMultiCompareTab([r.series_instance_uid for r in s.series])
        tab=app.workspaceController.activeTab
        views=list(tab.viewports_by_id.values())
        wait_until(lambda:all(v.loadState=='ready' for v in views))
        assert len(views)==4 and tab.scrollMode=='spatial'
        assert not tab.syncOperations['window']
        views[0].setSliceIndex(2)
        wait_until(lambda:all(v._frame_meta.slice_index==2 for v in views))
        assert len({v.windowWidth for v in views})>1
        doc=tmp_path/'enhanced.voxworkspace'; manager=app.workspaceDocumentController
        assert manager.save_to(doc);wait_until(lambda:not manager.busy)
        saved=read_document(doc)
        assert sum(len(r['instances']) for r in saved['series'])==12
        assert len(saved['tabs'][0]['views'])==4
        assert manager.restore_from(doc);wait_until(lambda:not manager.busy,timeout=20000)
        assert not manager.isError,manager.message
        tab=app.workspaceController.activeTab
        assert tab.scrollMode=='spatial' and len(tab.viewports_by_id)==4
        assert all(v.sliceIndex==2 for v in tab.viewports_by_id.values())
    finally:app.shutdown()


def test_mr_volume_uses_relative_presets_float_windows_and_shared_mpr_volume(qt_app,tmp_path):
    _,s=save_and_scan(tmp_path)
    app=AppController(DicomImageProvider(),settings_path=tmp_path/'settings.json')
    try:
        app.panelController.update_series_session(s);app.panelController._update_series_record(s)
        r=s.series[0]
        app.workspaceController.createTab(r.series_instance_uid,'MR 3D','3d')
        view=app.workspaceController.activeTab.activeViewport
        wait_until(lambda:view.loadState=='ready')
        assert view.currentPresetId=='mr-general'
        assert {p['presetId'] for p in view.volumePresets}=={'mr-general','mr-bright','mr-mip'}
        assert not view.bedRemovalAvailable
        view.applyWindowPreset(.1,.02)
        assert view.windowWidth==.02
        view.applyVolumePreset('bone');assert view.currentPresetId=='mr-general'
        view.applyVolumePreset('mr-mip');assert view.currentPresetId=='mr-mip'
        pixels = view.volume.modality_pixels
        expected = WindowLevel(float((np.nanmin(pixels)+np.nanmax(pixels))/2),
                               float(np.nanmax(pixels)-np.nanmin(pixels)))
        assert view.display_state.window == expected
        view.applyWindowPreset(.1,.02); view.autoWindow()
        assert view.display_state.window == expected
        from voxplane.ui.volume_render_backend import create_transfer_functions
        from voxplane.volume_presets import VOLUME_PRESET_BY_ID
        colors,opacity=create_transfer_functions(VOLUME_PRESET_BY_ID['mr-general'],WindowLevel(.1,.02))
        assert colors.GetRange()==pytest.approx((.09,.11))
        app.workspaceController.createTab(r.series_instance_uid,'MR MPR','mpr')
        tab=app.workspaceController.activeTab
        wait_until(lambda:all(v.loadState=='ready' for v in tab.viewports_by_id.values()))
        tab.mprLayout.setLayout('quad')
        assert tab.mprLayout.volumeViewport.volume is tab.mprLayout._pending_volume
        assert tab.mprLayout.volumeViewport.currentPresetId=='mr-general'
    finally:app.shutdown()


def test_legacy_classic_workspace_keeps_saved_sources_and_uid(tmp_path):
    from test_mr import write_mr_series
    from voxplane.core.local_import import LocalImportStore
    from voxplane.core.workspace_document import source_manifest, load_referenced_series
    series = write_mr_series(tmp_path / 'classic')
    original_uid = series.instances[0].series_instance_uid
    saved = replace(series, series_instance_uid=original_uid, instances=series.instances[:3])
    path = tmp_path / 'legacy.voxworkspace'
    store = LocalImportStore()
    document = {'series': [source_manifest(saved, store, path)]}
    restored, missing = load_referenced_series(document, path, store,
                                               extra_paths=[i.path for i in series.instances])
    assert not missing and len(restored.series) == 1
    assert restored.series[0].series_instance_uid == original_uid
    assert restored.series[0].instances == saved.instances
    assert restored.dicom_file_count == 3


def test_group_identity_does_not_depend_on_translated_error(tmp_path):
    from voxplane.core.mr import split_mr_series
    from voxplane.core.dicom_scanner import _build_series_record
    _, snapshot = save_and_scan(tmp_path)
    first = snapshot.series[0].instances[0]
    groups = [split_mr_series([replace(first, mr_support_error=error)], _build_series_record)
              for error in ('缺少逐帧几何', 'Missing frame geometry')]
    assert groups[0][0].series_instance_uid == groups[1][0].series_instance_uid



@pytest.mark.parametrize('polarity', ['MONOCHROME1', 'MONOCHROME2'])
def test_mr_3d_padding_mask_survives_cropping_and_mip_reset(tmp_path, polarity):
    from unittest.mock import Mock
    from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
    from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from voxplane.ui.volume_render_backend import VolumeRenderBackend
    from voxplane.model.volume_models import VolumeDisplayState
    d = enhanced_dataset()
    raw = d.pixel_array.copy()
    raw[:, :2, :2] = -30000
    d.PixelData = raw.tobytes()
    d.PixelPaddingValue = -30000
    d.PhotometricInterpretation = polarity
    _, snapshot = save_and_scan(tmp_path, d)
    volume = VolumeManager().get_or_build(snapshot.series[0])
    before = volume.modality_pixels.copy()
    valid = np.isfinite(before)
    assert not valid.all()
    window = vtkGenericOpenGLRenderWindow()
    interactor = vtkGenericRenderWindowInteractor(); interactor.SetRenderWindow(window)
    widget = Mock(); widget.GetRenderWindow.return_value = window
    backend = VolumeRenderBackend(widget)
    try:
        backend.set_volume(volume)
        def mask():
            return vtk_to_numpy(backend.mapper.GetMaskInput().GetPointData().GetScalars()).reshape(valid.shape)>0
        np.testing.assert_array_equal(mask(), valid)
        assert np.isfinite(backend._pixels).all()
        crop = np.ones(valid.shape, dtype=bool); crop[:, :, -2:] = False
        backend.apply_mask(crop)
        np.testing.assert_array_equal(mask(), crop & valid)
        backend.apply_mask(None)
        np.testing.assert_array_equal(mask(), valid)
        backend.apply_display(VolumeDisplayState('mr-mip', volume.default_window))
        assert backend.mapper.GetBlendMode() == (2 if polarity=='MONOCHROME1' else 1)
        np.testing.assert_array_equal(mask(), valid)
        np.testing.assert_array_equal(volume.modality_pixels, before)
        assert np.isnan(volume.modality_pixels[0,0,0])
    finally:
        backend.dispose()
