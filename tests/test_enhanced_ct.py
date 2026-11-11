"""Enhanced CT: frame addressing, HU, spatial groups and source fidelity."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pydicom
import pytest
from pydicom.uid import EnhancedCTImageStorage, LegacyConvertedEnhancedCTImageStorage, RLELossless, generate_uid
from PySide6.QtGui import QImage

from voxplane.core.ct import ct_series_error, ct_view_error
from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.enhanced_frames import frame_metadata
from voxplane.core.export_images import frame_image
from voxplane.core.series_export import ExportRequest, export_series
from voxplane.core.volume_manager import VolumeManager, VolumeBuildError
from voxplane.core.series_thumbnail import read_series_thumbnail
from voxplane.model import WindowLevel
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.workers.dicom_scan_worker import DicomScanWorker
from test_enhanced_mr import item
from test_mr import mr_dataset
from test_dicom_tags import qt_app, wait_until


def enhanced_ct_dataset():
    d = mr_dataset(np.arange(64).reshape(8, 8))
    d.SOPClassUID = d.file_meta.MediaStorageSOPClassUID = EnhancedCTImageStorage
    d.Modality, d.SeriesDescription = 'CT', 'Synthetic Enhanced CT'
    for key in ('ImagePositionPatient', 'ImageOrientationPatient', 'PixelSpacing', 'SliceThickness',
                'RepetitionTime', 'EchoTime', 'FlipAngle', 'MagneticFieldStrength',
                'RescaleSlope', 'RescaleIntercept'):
        delattr(d, key)
    d.SharedFunctionalGroupsSequence = [item(
        PixelMeasuresSequence=[item(PixelSpacing=[.7, .8], SliceThickness=2)],
        PlaneOrientationSequence=[item(ImageOrientationPatient=[1, 0, 0, 0, 1, 0])],
        CTImageFrameTypeSequence=[item(FrameType=['ORIGINAL', 'PRIMARY', 'AXIAL', 'NONE'],
                                      PixelPresentation='MONOCHROME', VolumetricProperties='VOLUME')],
        CTReconstructionSequence=[item(ConvolutionKernel='B30', ReconstructionAlgorithm='FILTER_BACK_PROJ')])]
    d.DimensionIndexSequence = [item(DimensionIndexPointer=tag, FunctionalGroupPointer=0x00209111)
                                for tag in (0x00209057, 0x00209128)]
    frames, pixels = [], []
    for t in (1, 2):
        for z in (2, 0, 1):
            f = len(frames)
            frames.append(item(
                FrameContentSequence=[item(StackID='1', InStackPositionNumber=z+1,
                                           TemporalPositionIndex=t, DimensionIndexValues=[z+1, t])],
                PlanePositionSequence=[item(ImagePositionPatient=[10, 20, 2*z])],
                PixelValueTransformationSequence=[item(RescaleSlope=.5+f/4, RescaleIntercept=-1024+f, RescaleType='HU')],
                FrameVOILUTSequence=[item(WindowCenter=40+f, WindowWidth=400+f)],
                CTExposureSequence=[item(XRayTubeCurrentInmA=100.5+f)],
                CTXRayDetailsSequence=[item(KVP=120)]))
            pixels.append(np.arange(64, dtype=np.int16).reshape(8, 8)+100*f)
    d.NumberOfFrames = len(frames)
    d.PerFrameFunctionalGroupsSequence = frames
    d.PixelData = np.stack(pixels).tobytes()
    return d


def save_and_scan(tmp_path, d=None):
    d = enhanced_ct_dataset() if d is None else d
    path = tmp_path / 'enhanced-ct.dcm'
    d.save_as(path, enforce_file_format=True)
    return path, list(DicomFolderScanner().scan_files([path], folder=tmp_path, can_publish=lambda: False))[-1]


@pytest.mark.parametrize('storage,compressed', [(EnhancedCTImageStorage, False),
    (LegacyConvertedEnhancedCTImageStorage, False), (EnhancedCTImageStorage, True)])
def test_enhanced_ct_pixels_windows_geometry_and_volumes(tmp_path, storage, compressed):
    d = enhanced_ct_dataset()
    d.SOPClassUID = d.file_meta.MediaStorageSOPClassUID = storage
    raw = d.pixel_array.copy()
    if compressed:
        d.compress(RLELossless, generate_instance_uid=False)
    path, snapshot = save_and_scan(tmp_path, d)
    assert snapshot.dicom_file_count == 1 and len(snapshot.series) == 2
    loader = DicomLoader()
    identities = []
    for series in snapshot.series:
        assert not ct_series_error(series, volume=True)
        assert [i.image_position_patient[2] for i in series.instances] == [0, 2, 4]
        volume = VolumeManager().get_or_build(series)
        assert (volume.geometry.row_spacing, volume.geometry.column_spacing, volume.geometry.slice_spacing) == (.7, .8, 2)
        for z, instance in enumerate(series.instances):
            f = instance.frame_index
            identities.append(instance.frame_identity)
            metadata, pixels = loader.read_frame(path, f)
            expected = raw[f]*(.5+f/4)-1024+f
            np.testing.assert_array_equal(pixels, expected)
            np.testing.assert_array_equal(volume.modality_pixels[z], expected)
            rendered = loader.load_dataset(metadata, None, False, modality_pixels=pixels)
            assert rendered.pixel_value_meta.unit == 'HU'
            assert rendered.window == WindowLevel(40+f, 400+f)
            assert rendered.instance_meta.frame_index == f
            assert rendered.instance_meta.tube_current_ma == 100.5+f
            assert rendered.instance_meta.kvp == 120
        assert not read_series_thumbnail(path, series.instances[1].frame_index).isNull()
    assert len(set(identities)) == 6
    with pytest.raises(ValueError):
        loader.read_frame(path)
    assert 'ImagePositionPatient' not in d


@pytest.mark.parametrize('defect', ['count', 'position', 'dimension', 'spacing', 'orientation',
                                   'cardinality', 'slope', 'color', 'supplemental'])
def test_invalid_frames_remain_tag_accessible(tmp_path, defect):
    d = enhanced_ct_dataset()
    frame = d.PerFrameFunctionalGroupsSequence[1]
    if defect == 'count': d.NumberOfFrames = 7
    if defect == 'position': del frame.PlanePositionSequence
    if defect == 'dimension': frame.FrameContentSequence[0].DimensionIndexValues = [1]
    if defect == 'spacing': d.SharedFunctionalGroupsSequence[0].PixelMeasuresSequence[0].PixelSpacing = [0, .8]
    if defect == 'orientation': d.SharedFunctionalGroupsSequence[0].PlaneOrientationSequence[0].ImageOrientationPatient = [0]*6
    if defect == 'cardinality': frame.CTExposureSequence.append(item(XRayTubeCurrentInmA=2))
    if defect == 'slope': frame.PixelValueTransformationSequence[0].RescaleSlope = 0
    if defect == 'color': d.PhotometricInterpretation = 'RGB'
    if defect == 'supplemental': d.SharedFunctionalGroupsSequence[0].CTImageFrameTypeSequence[0].PixelPresentation = 'COLOR'
    _, snapshot = save_and_scan(tmp_path, d)
    assert snapshot.dicom_file_count == 1 and len(snapshot.series) == 1
    series = snapshot.series[0]
    assert ct_view_error(series, '2d')
    assert ct_view_error(series, 'mpr')
    assert not ct_view_error(series, 'tag')
    with pytest.raises(VolumeBuildError): VolumeManager().get_or_build(series)


@pytest.mark.parametrize('kind', ['unknown-dimension', 'kernel', 'stack'])
def test_nonspatial_dimensions_never_become_slices(tmp_path, kind):
    d = enhanced_ct_dataset()
    for f, group in enumerate(d.PerFrameFunctionalGroupsSequence):
        content = group.FrameContentSequence[0]
        content.TemporalPositionIndex = 1
        content.DimensionIndexValues = [int(content.InStackPositionNumber), 1]
        if kind == 'unknown-dimension': content.DimensionIndexValues[1] = f//3+1
        if kind == 'kernel': group.CTReconstructionSequence = [item(ConvolutionKernel='B30' if f<3 else 'B70')]
        if kind == 'stack': content.StackID = str(f//3+1)
    if kind == 'unknown-dimension': d.DimensionIndexSequence[1].DimensionIndexPointer = 0x00189360
    _, snapshot = save_and_scan(tmp_path, d)
    assert sorted(len(s.instances) for s in snapshot.series) == [3, 3]


def test_duplicate_positions_allow_2d_but_block_volume(tmp_path):
    d = enhanced_ct_dataset()
    d.PerFrameFunctionalGroupsSequence[1].PlanePositionSequence[0].ImagePositionPatient = [10, 20, 4]
    _, snapshot = save_and_scan(tmp_path, d)
    invalid = next(s for s in snapshot.series if s.instances[0].phase_value('TemporalPositionIndex') == 1)
    assert not ct_view_error(invalid, '2d') and ct_view_error(invalid, 'mpr')
    with pytest.raises(VolumeBuildError): VolumeManager().get_or_build(invalid)


def test_incremental_import_and_multiple_objects_keep_source_frames(tmp_path):
    d = enhanced_ct_dataset()
    raw = d.pixel_array
    paths = []
    for n, indices in enumerate(([0, 3], [1, 2, 4, 5])):
        part = deepcopy(d)
        part.SOPInstanceUID = part.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        part.NumberOfFrames = len(indices)
        part.PerFrameFunctionalGroupsSequence = [d.PerFrameFunctionalGroupsSequence[i] for i in indices]
        part.PixelData = raw[indices].tobytes()
        path = tmp_path/f'part{n}.dcm'; part.save_as(path, enforce_file_format=True); paths.append(path)
    scanner = DicomFolderScanner()
    partial = list(scanner.scan_files(paths[:1], folder=tmp_path))[-1]
    full = list(scanner.scan_files(paths+paths, folder=tmp_path))[-1]
    assert {s.series_instance_uid for s in partial.series} == {s.series_instance_uid for s in full.series}
    assert full.dicom_file_count == 2 and sorted(len(s.instances) for s in full.series) == [3, 3]
    worker = DicomScanWorker(paths, base_series={s.series_instance_uid:s for s in partial.series})
    merged = worker._merge_snapshot(full)
    assert sorted(len(s.instances) for s in merged.series) == [3, 3]
    for s in merged.series: assert not ct_series_error(s, volume=True)


def test_export_selected_frames_and_complete_original_object(qt_app, tmp_path):
    d = enhanced_ct_dataset()
    path, snapshot = save_and_scan(tmp_path, d)
    series = snapshot.series[0]
    refs = tuple((i.path, i.frame_index) for i in series.instances)
    request = ExportRequest(tuple(i.path for i in series.instances), tmp_path/'exports', 'png', True, refs)
    result = export_series(request)
    assert result.file_count == 3
    for _, f in refs:
        assert QImage(str(result.directory/f'instance-000001-frame-{f+1:06d}.png')) == frame_image(d.pixel_array[f], d, f)
    copied = export_series(replace(request, format='dicom', anonymous=False))
    assert copied.file_count == 1 and next(copied.directory.glob('*.dcm')).read_bytes() == path.read_bytes()
    anon = export_series(replace(request, format='dicom'))
    exported = pydicom.dcmread(next(anon.directory.glob('*.dcm')))
    np.testing.assert_array_equal(exported.pixel_array, d.pixel_array)
    assert exported.NumberOfFrames == 6 and str(exported.PatientName) != str(d.PatientName)
    rescanned = list(DicomFolderScanner().scan(anon.directory))[-1]
    assert sorted(len(s.instances) for s in rescanned.series) == [3, 3]


def test_ct_views_and_workspace_restore_frame_indices(qt_app, tmp_path):
    _, snapshot = save_and_scan(tmp_path)
    app = AppController(DicomImageProvider(), settings_path=tmp_path/'settings.json')
    try:
        app.panelController.update_series_session(snapshot); app.panelController._update_series_record(snapshot)
        series = snapshot.series[0]
        app.workspaceController.createTab(series.series_instance_uid, 'Enhanced CT', '2d')
        view = app.workspaceController.activeViewport
        wait_until(lambda: view.loadState == 'ready')
        view.setSliceIndex(2)
        wait_until(lambda: view._frame_meta.slice_index == 2)
        assert view._frame_meta.pixel_value_meta.unit == 'HU'
        manager = app.workspaceDocumentController
        path = tmp_path/'ct.voxworkspace'
        assert manager.save_to(path); wait_until(lambda: not manager.busy)
        assert manager.restore_from(path); wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert app.workspaceController.activeViewport.sliceIndex == 2
        app.workspaceController.createTab(series.series_instance_uid, 'Enhanced CT MPR', 'mpr')
        tab = app.workspaceController.activeTab
        wait_until(lambda: all(v.loadState == 'ready' for v in tab.viewports_by_id.values()))
        app.workspaceController.createTab(series.series_instance_uid, 'Enhanced CT 3D', '3d')
        wait_until(lambda: app.workspaceController.activeViewport.loadState == 'ready')
    finally:
        app.shutdown()


def test_shared_only_single_frame_and_top_level_cannot_mask_missing_groups(tmp_path):
    d = enhanced_ct_dataset()
    raw = d.pixel_array[:1].copy()
    shared = d.SharedFunctionalGroupsSequence[0]
    for element in d.PerFrameFunctionalGroupsSequence[0]: shared.add(deepcopy(element))
    del d.PerFrameFunctionalGroupsSequence
    d.NumberOfFrames = 1
    d.PixelData = raw.tobytes()
    path, snapshot = save_and_scan(tmp_path, d)
    assert len(snapshot.series) == 1 and not ct_view_error(snapshot.series[0], '2d')
    assert ct_view_error(snapshot.series[0], 'mpr')
    metadata, pixels = DicomLoader().read_frame(path, 0)
    np.testing.assert_array_equal(pixels, raw[0]*.5-1024)
    del shared.PlanePositionSequence
    d.ImagePositionPatient = [0, 0, 0]  # Invalid top-level fallback must not hide the defect.
    _, snapshot = save_and_scan(tmp_path, d)
    assert ct_view_error(snapshot.series[0], '2d')


def test_unsupported_ct_cannot_enter_compare(qt_app, tmp_path):
    from voxplane.core.compare import supports_compare
    d = enhanced_ct_dataset()
    d.SharedFunctionalGroupsSequence[0].CTImageFrameTypeSequence[0].PixelPresentation = 'COLOR'
    _, snapshot = save_and_scan(tmp_path, d)
    assert not supports_compare(snapshot.series[0])
    app = AppController(DicomImageProvider(), settings_path=tmp_path/'settings.json')
    try:
        app.panelController.update_series_session(snapshot); app.panelController._update_series_record(snapshot)
        uid = snapshot.series[0].series_instance_uid
        assert app.panelController.seriesViewError(uid, '2d')
        app.workspaceController.createTab(uid, 'Unsupported CT', '2d')
        assert app.workspaceController.activeTab is not None
        wait_until(lambda: app.workspaceController.activeLoadState.status == "error")
        assert app.workspaceController.activeLoadState.errorMessage
        assert not app.exportController.canExportPng
        app.workspaceController.createTab(uid, 'Source tags', 'tag')
        assert app.workspaceController.activeTab is not None
    finally:
        app.shutdown()
