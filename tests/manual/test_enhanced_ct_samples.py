"""Opt-in acceptance against untouched public NEMA Enhanced CT objects."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pydicom
import pytest

from voxplane.core.ct import ct_view_error
from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.series_thumbnail import read_series_thumbnail
from voxplane.core.volume_manager import VolumeManager
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from manual.test_mr_samples import import_local, ready


@pytest.fixture
def sample_root():
    path = os.environ.get('VOXPLANE_ENHANCED_CT_SAMPLE_DIR')
    if not path:
        pytest.skip('Set VOXPLANE_ENHANCED_CT_SAMPLE_DIR to the public sample directory')
    root = Path(path)
    assert root.is_dir(), root
    return root


def functional_group(dataset, frame, keyword):
    groups = [*getattr(dataset, 'SharedFunctionalGroupsSequence', ()),
              dataset.PerFrameFunctionalGroupsSequence[frame]]
    return next(getattr(g, keyword)[0] for g in reversed(groups) if keyword in g)


def test_public_hu_frames_and_patient_coordinates(sample_root, tmp_path):
    root = sample_root/'NEMA-2006'
    manifest = json.loads((root/'manifest.json').read_text())
    assert manifest['files']
    report = []
    for source in manifest['files']:
        path = root/source['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
        d = pydicom.dcmread(path)
        # Direct decoding and functional-group lookup, independent of app parsing.
        stored = d.pixel_array
        snapshot = list(DicomFolderScanner().scan_files([path], folder=root, can_publish=lambda:False))[-1]
        assert snapshot.dicom_file_count == 1
        assert sum(len(s.instances) for s in snapshot.series) == int(d.NumberOfFrames)
        loader = DicomLoader()
        seen = set()
        for series in snapshot.series:
            assert not ct_view_error(series, '2d')
            volume_error = ct_view_error(series, 'mpr')
            volume = None if volume_error else VolumeManager().get_or_build(series)
            assert not read_series_thumbnail(path, series.instances[len(series.instances)//2].frame_index).isNull()
            for z, instance in enumerate(series.instances):
                f = instance.frame_index
                assert f not in seen
                seen.add(f)
                transform = functional_group(d, f, 'PixelValueTransformationSequence')
                assert str(transform.RescaleType) == 'HU'
                expected = stored[f].astype(float)*float(transform.RescaleSlope)+float(transform.RescaleIntercept)
                if 'PixelPaddingValue' in d:
                    low = float(d.PixelPaddingValue)
                    high = float(getattr(d, 'PixelPaddingRangeLimit', low))
                    expected[(stored[f]>=min(low,high)) & (stored[f]<=max(low,high))] = np.nan
                metadata, pixels = loader.read_frame(path, f)
                np.testing.assert_allclose(pixels, expected, rtol=1e-6, atol=.002)
                display = loader.load_dataset(metadata, None, False, modality_pixels=pixels)
                assert display.pixel_value_meta.unit == 'HU'
                ipp = np.array(functional_group(d, f, 'PlanePositionSequence').ImagePositionPatient, float)
                iop = np.array(functional_group(d, f, 'PlaneOrientationSequence').ImageOrientationPatient, float)
                spacing = np.array(functional_group(d, f, 'PixelMeasuresSequence').PixelSpacing, float)
                np.testing.assert_allclose(instance.image_position_patient, ipp, atol=1e-6)
                np.testing.assert_allclose(instance.image_orientation_patient, iop, atol=1e-6)
                if volume is not None:
                    np.testing.assert_allclose(volume.modality_pixels[z], expected, rtol=1e-6, atol=.002)
                    for row, col in ((0,0), (d.Rows//2,d.Columns//2), (d.Rows-1,d.Columns-1)):
                        expected_lps = ipp+iop[:3]*col*spacing[1]+iop[3:]*row*spacing[0]
                        actual_lps = (volume.geometry.voxel_to_patient@[z,row,col,1])[:3]
                        np.testing.assert_allclose(actual_lps, expected_lps, atol=.002)
            report.append(dict(file=source['file'], group=series.series_description,
                               frames=len(series.instances), volume=volume is not None,
                               volume_error=str(volume_error)))
        assert seen == set(range(int(d.NumberOfFrames)))
    (tmp_path/'validation-enhanced-ct.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    assert any(r['volume'] for r in report)


def test_public_perfusion_units_are_not_mislabeled_hu(sample_root):
    path = sample_root/'pydicom/eCT_Supplemental.dcm'
    d = pydicom.dcmread(path, stop_before_pixels=True)
    assert str(d.SharedFunctionalGroupsSequence[0].PixelValueTransformationSequence[0].RescaleType) == 'US'
    snapshot = list(DicomFolderScanner().scan_files([path], folder=path.parent))[-1]
    series = snapshot.series[0]
    assert snapshot.dicom_file_count == 1 and len(snapshot.series) == 1
    assert not ct_view_error(series, '2d') and not ct_view_error(series, 'tag')
    assert ct_view_error(series, 'mpr')
    assert len(series.instances) == 2
    source = pydicom.dcmread(path)
    raw = source.pixel_array
    mapping = source.SharedFunctionalGroupsSequence[0].RealWorldValueMappingSequence[0]
    lut = np.stack([np.frombuffer(getattr(source, c+'PaletteColorLookupTableData'), '<u2')
                    for c in ('Red', 'Green', 'Blue')], axis=-1)
    lut = np.rint(lut.astype(float)*255/65535).astype(np.uint8)
    for i in series.instances:
        f = i.frame_index
        meta, values = DicomLoader().read_frame(path, f)
        result = DicomLoader().load_dataset(meta, None, False, modality_pixels=values)
        assert result.image.shape == (512, 512, 3)
        assert result.pixel_value_meta.unit == 'ml/100ml/s'
        np.testing.assert_allclose(result.modality_pixel, raw[f].astype(float)*float(mapping.RealWorldValueSlope)+float(mapping.RealWorldValueIntercept))
        mask = raw[f] >= 1024
        np.testing.assert_array_equal(result.image[mask], lut[np.clip(raw[f][mask].astype(int)-1024,0,99)])
        gray = DicomLoader.apply_window(values, result.window, False)
        np.testing.assert_array_equal(result.image[~mask], np.repeat(gray[~mask,None],3,axis=1))



@pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM') == 'offscreen', reason='Requires a native desktop OpenGL surface')
def test_public_ct_native_views_and_source_export(scene, sample_root, tmp_path):
    from dataclasses import replace
    from PySide6.QtTest import QTest
    from voxplane.core.series_export import ExportRequest, export_series
    from voxplane.core.mpr_reslicer import MprReslicer
    from voxplane.model import MprPlane
    window, app, warnings = scene
    root = sample_root/'NEMA-2006'
    source = json.loads((root/'manifest.json').read_text())['files'][0]
    path = root/source['file']
    import_local(app, [path])
    ws = app.workspaceController
    series = next(iter(app.panelController._scan_series_record.values()))
    assert len(series.instances) == source['frames']
    window.resize(1400, 900)
    ws.createTab(series.series_instance_uid, 'Enhanced CT 2D', '2d'); ready(ws)
    view = ws.activeViewport
    for index in (0, len(series.instances)-1, len(series.instances)//2):
        view.setSliceIndex(index)
        wait_until(lambda: view._frame_meta.slice_index == index)
        assert view._frame_meta.instance_meta.frame_index == series.instances[index].frame_index
    QTest.qWait(150)
    assert window.grabWindow().save(str(tmp_path/'enhanced-ct-2d.png'))
    ws.createTab(series.series_instance_uid, 'Enhanced CT MPR', 'mpr'); ready(ws)
    tab = ws.activeTab
    tab.mprLayout.setLayout('quad')
    reference = tab.mprLayout.volumeViewport
    wait_until(lambda: reference._host is not None, timeout=15000)
    QTest.qWait(250)
    assert reference.snapshot_image().save(str(tmp_path/'enhanced-ct-mpr-reference.png'))
    assert window.grabWindow().save(str(tmp_path/'enhanced-ct-mpr.png'))
    volume = reference.volume
    # Check the axial center sample against the source HU volume.
    axial = MprReslicer().reslice(volume, MprPlane.AXIAL)
    row, col = np.array(axial.modality_pixels.shape)//2
    patient = axial.geometry.image_point_to_patient(column=col, row=row)
    voxel = (volume.geometry.patient_to_voxel@[*patient,1])[:3]
    lo = np.floor(voxel).astype(int); hi = np.minimum(lo+1, np.array(volume.modality_pixels.shape)-1)
    fraction = voxel-lo
    import itertools
    expected = sum(volume.modality_pixels[tuple(hi[a] if corner[a] else lo[a] for a in range(3))]
                   * np.prod([fraction[a] if corner[a] else 1-fraction[a] for a in range(3)])
                   for corner in itertools.product((0,1), repeat=3))
    assert axial.modality_pixels[row,col] == pytest.approx(expected, abs=.002)
    ws.createTab(series.series_instance_uid, 'Enhanced CT 3D', '3d'); ready(ws)
    view = ws.activeViewport
    wait_until(lambda: view._host is not None, timeout=15000)
    QTest.qWait(250)
    assert view.snapshot_image().save(str(tmp_path/'enhanced-ct-3d.png'))
    assert not view._host.backend._error
    request = ExportRequest(tuple(i.path for i in series.instances), tmp_path/'exports', 'dicom', False)
    exported = export_series(request)
    assert exported.file_count == 1
    assert next(exported.directory.glob('*.dcm')).read_bytes() == path.read_bytes()
    refs = tuple((i.path, i.frame_index) for i in series.instances)
    pngs = export_series(replace(request, format='png', anonymous=True, frames=refs))
    assert pngs.file_count == len(series.instances)
    assert not warnings, warnings


@pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM') == 'offscreen', reason='Requires native window capture')
def test_public_perfusion_native_browsing_and_png(scene, sample_root, tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QImage
    from voxplane.core.series_export import ExportRequest, export_series
    window, app, warnings = scene
    path = sample_root/'pydicom/eCT_Supplemental.dcm'
    import_local(app,[sample_root/'NEMA-2006/01-CT0001',path])
    ws = app.workspaceController
    series = next(s for s in app.panelController._scan_series_record.values() if len(s.instances)==2)
    window.resize(1400,900)
    app.panelController._request_thumbnails()
    wait_until(lambda:len(app.panelController._thumbnails)==2)
    ws.createTab(series.series_instance_uid,'Enhanced CT · RCBF','2d'); ready(ws)
    view = ws.activeViewport
    images=[]; view.imageUpdateRequested.connect(lambda _,pixels:images.append(pixels.copy()))
    for index in (0,1):
        view.setSliceIndex(index)
        wait_until(lambda:view._frame_meta.slice_index==index)
        assert view._frame_meta.pixel_value_meta.unit=='ml/100ml/s'
        view.refresh_window_image()
        assert images[-1].shape==(512,512,3)
        assert np.any(images[-1][...,0] != images[-1][...,1])
        QTest.qWait(200)
        assert window.grabWindow().save(str(tmp_path/f'perfusion-frame-{index+1}.png'))
    mask = view._frame_meta.supplemental_overlay[...,3]!=0
    before=images[-1].copy()
    view.toggleInverted()
    wait_until(lambda: view.inverted)
    np.testing.assert_array_equal(images[-1][mask],before[mask])
    assert np.any(images[-1][~mask]!=before[~mask])
    view.toggleInverted()
    request = ExportRequest(tuple(i.path for i in series.instances),tmp_path/'export','png',True,
                            frames=tuple((i.path,i.frame_index) for i in series.instances))
    exported=export_series(request)
    assert exported.file_count==2
    assert len(list(exported.directory.glob('*.png')))==2
    for p in exported.directory.glob('*.png'):
        image=QImage(str(p)); assert image.width()==512 and image.height()==512 and not image.isGrayscale()
    ws.createTab(series.series_instance_uid,'RCBF · Montage','montage')
    wait_until(lambda:len(ws.activeViewport._display_palettes)==2)
    assert all(p is not None for p in ws.activeViewport._display_palettes.values())
    QTest.qWait(200)
    assert window.grabWindow().save(str(tmp_path/'perfusion-montage.png'))
    assert not warnings,warnings
