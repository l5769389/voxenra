"""Real codec round trips, shared rendering paths and actionable failure states."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pydicom
import pytest
from pydicom.uid import CTImageStorage, RLELossless, JPEGLSLossless, JPEG2000Lossless

from qt_dicom_viewer.core import pixel_codecs as codecs
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.series_thumbnail import read_series_thumbnail
from qt_dicom_viewer.core.series_export import export_series, ExportRequest, ExportError
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.i18n.messages import error_message, localize, builtin
from test_mr import mr_dataset
from test_enhanced_mr import enhanced_dataset
from test_dicom_tags import qt_app

LOSSLESS = [RLELossless, JPEGLSLossless, JPEG2000Lossless]


@pytest.mark.parametrize('syntax', LOSSLESS)
@pytest.mark.parametrize('modality', ['CT', 'MR'])
def test_lossless_view_thumbnail_volume_export(qt_app, tmp_path, syntax, modality):
    original = mr_dataset(np.arange(4096, dtype=np.int16).reshape(64, 64) - 2048)
    original.Modality = modality
    if modality == 'CT':
        original.SOPClassUID = original.file_meta.MediaStorageSOPClassUID = CTImageStorage
    original.RescaleSlope, original.RescaleIntercept = .5, -1024
    expected = DicomLoader.to_modality_pixels(original)
    paths = []
    for z in range(2):
        ds = deepcopy(original)
        ds.ImagePositionPatient = [0, 0, z * 2]
        ds.compress(syntax)
        path = tmp_path / f'{z}.dcm'
        ds.save_as(path, enforce_file_format=True)
        paths.append(path)
        before = path.read_bytes()
        np.testing.assert_array_equal(DicomLoader().read_frame(path)[1], expected)
        assert not read_series_thumbnail(path).isNull()
        assert path.read_bytes() == before
    record = list(DicomFolderScanner().scan(tmp_path))[-1].series[0]
    volume = VolumeManager().get_or_build(record)
    np.testing.assert_array_equal(volume.modality_pixels, np.stack([expected, expected]))
    result = export_series(ExportRequest(tuple(paths), tmp_path / 'export', format='png'))
    assert result.file_count == 2


@pytest.mark.parametrize('syntax', LOSSLESS)
def test_enhanced_mr_decodes_requested_frame_with_per_frame_scaling(tmp_path, syntax):
    ds = enhanced_dataset()
    # OpenJPEG's default decomposition requires a sufficiently large frame.
    raw = np.frombuffer(ds.PixelData, dtype=np.int16).reshape(-1, 8, 8)
    raw = np.tile(raw, (1, 8, 8)).copy()
    ds.Rows = ds.Columns = 64
    ds.PixelData = raw.tobytes()
    ds.compress(syntax)
    path = tmp_path / 'enhanced.dcm'
    ds.save_as(path, enforce_file_format=True)
    loader = DicomLoader()
    for index in (7, 0, 11):
        _, actual = loader.read_frame(path, index)
        np.testing.assert_allclose(actual, raw[index].astype(np.float32) * (.001 * (index + 1)) - .1 * index,
                                   atol=1e-6)


def test_all_supported_compressed_syntaxes_have_bundled_plugin():
    for syntax, plugin in codecs.PLUGINS.items():
        assert plugin in codecs.get_decoder(syntax).available_plugins, syntax


def test_missing_decoder_is_distinct_from_corrupt_data(monkeypatch, tmp_path):
    ds = mr_dataset()
    ds.compress(JPEGLSLossless)
    path = tmp_path / 'private-patient.dcm'
    ds.save_as(path, enforce_file_format=True)
    monkeypatch.setattr(codecs, 'get_decoder', lambda _: SimpleNamespace(available_plugins=()))
    with pytest.raises(codecs.PixelDecodeError) as error:
        DicomLoader().read_frame(path)
    assert error_message(error.value).key == 'codec.missing'
    assert 'private-patient' not in str(error.value)
    assert 'unavailable' in localize(error.value, builtin('en-US')['messages'])
    with pytest.raises(ExportError) as export_error:
        export_series(ExportRequest((path,), tmp_path / 'png', format='png'))
    assert error_message(export_error.value).key == 'codec.missing'
    assert not list((tmp_path / 'png').iterdir())
    # DICOM copying does not require a decoder.
    result = export_series(ExportRequest((path,), tmp_path / 'dicom', anonymous=False))
    assert next(result.directory.iterdir()).read_bytes() == path.read_bytes()


def test_corrupt_pixels_and_unsupported_codec_are_distinct():
    ds = mr_dataset()
    ds.compress(JPEG2000Lossless)
    from pydicom.encaps import encapsulate
    ds.PixelData = encapsulate([b'broken compressed frame'])
    with pytest.raises(codecs.PixelDecodeError) as error:
        codecs.decode_pixels(ds)
    assert error_message(error.value).key == 'codec.failed'
    ds.file_meta.TransferSyntaxUID = '1.2.840.10008.1.2.4.100'  # MPEG2
    with pytest.raises(codecs.PixelDecodeError) as error:
        codecs.decode_pixels(ds)
    assert error_message(error.value).key == 'codec.unsupported'


def test_bundled_public_jpeg_lossless_rgb_sample():
    path = Path(pydicom.__file__).parent / 'data/test_files/SC_rgb_jpeg_gdcm.dcm'
    pixels = codecs.decode_pixels(path)
    assert pixels.shape == (100, 100, 3) and pixels.dtype == np.uint8
    np.testing.assert_array_equal(pixels[0, 0], [255, 0, 0])
    np.testing.assert_array_equal(pixels[20, 0], [0, 255, 0])


@pytest.mark.parametrize('syntax, tolerance', [('1.2.840.10008.1.2.4.81', 2), ('1.2.840.10008.1.2.4.91', 100)])
def test_lossy_decoders_keep_shape_and_approximate_values(syntax, tolerance):
    pixels = np.arange(4096, dtype=np.uint16).reshape(64, 64)
    ds = mr_dataset(pixels)
    ds.PixelRepresentation = 0
    options = {'jls_error': 2} if syntax.endswith('.81') else {'j2k_cr': [4]}
    ds.compress(syntax, **options)
    decoded = codecs.decode_pixels(ds)
    assert decoded.shape == pixels.shape
    assert np.max(np.abs(decoded.astype(float) - pixels)) <= tolerance


def test_frozen_verifier_checks_pixels_and_rejects_wrong_reference(tmp_path):
    import importlib.util
    import json
    from qt_dicom_viewer.core.codec_check import verify
    spec = importlib.util.spec_from_file_location('verify_pixel_codecs', Path(__file__).resolve().parents[1] / 'scripts/verify_pixel_codecs.py')
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    script.prepare(tmp_path)
    output = tmp_path / 'result.json'
    assert verify(tmp_path, output) == 0
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest[0]['sha256'] = 'wrong'
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    assert verify(tmp_path, output) == 1
    assert not json.loads(output.read_text())['passed']


from test_pacs_qml import scene


@pytest.mark.parametrize('syntax', LOSSLESS)
def test_compressed_mr_opens_and_plays_in_real_qml(scene, tmp_path, syntax):
    from test_mr import write_mr_series
    from test_dicom_tags import wait_until
    from test_slice_playback import settle
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    _, app, warnings = scene
    series = write_mr_series(tmp_path / 'compressed-mr', change=lambda ds, _: ds.compress(syntax))
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    workspace = app.workspaceController
    wait_until(lambda: workspace.activeViewport is not None and workspace.activeViewport.loadState == 'ready')
    tab = workspace.activeTab
    tab.setPlaying(True)
    assert tab.playing
    tab._phase_timer.stop()
    before = tab.activeViewport.sliceIndex
    tab._handle_playback_timeout()
    settle(tab, tab.activeViewport)
    assert tab.activeViewport.sliceIndex == (before + 1) % 4
    workspace.createTab(series.series_instance_uid, 'Compressed MR', 'mpr')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    assert not tab.playing
    assert all(view.imageSource for view in workspace.activeTab.viewports_by_id.values())
    assert not warnings, warnings


def test_legacy_mixed_vr_jpeg_path_thumbnail_and_export(qt_app, tmp_path):
    # The upstream file's Pixel Data element uses implicit VR despite its
    # explicit-VR compressed transfer syntax. dcmread recovers the element.
    path = Path(pydicom.__file__).parent / 'data/test_files/SC_rgb_jpeg.dcm'
    expected = codecs.decode_pixels(pydicom.dcmread(path))
    np.testing.assert_array_equal(codecs.decode_pixels(path), expected)
    np.testing.assert_array_equal(list(codecs.iter_decoded_pixels(path))[0], expected)
    assert not read_series_thumbnail(path).isNull()
    assert export_series(ExportRequest((path,), tmp_path, format='png', anonymous=False)).file_count == 1


def test_jpeg_extended_12_bit_has_explicit_capability_message():
    path = Path(pydicom.__file__).parent / 'data/test_files/JPEG-lossy.dcm'
    with pytest.raises(codecs.PixelDecodeError) as error:
        codecs.decode_pixels(path)
    assert error_message(error.value).key == 'codec.precision'


@pytest.mark.parametrize('filename', ['SC_rgb_jpeg.dcm', 'SC_rgb_jpeg_gdcm.dcm'])
def test_color_main_view_preserves_decoded_rgb_without_scalar_values(filename):
    path = Path(pydicom.__file__).parent / 'data/test_files' / filename
    dataset, pixels = DicomLoader().read_frame(path)
    assert pixels.shape[-1] == 3
    result = DicomLoader().load_dataset(dataset, None, False, modality_pixels=pixels)
    np.testing.assert_array_equal(result.image, pixels)
    assert result.modality_pixel is None
    assert result.pixel_value_meta.quantification == 'color'


def test_streaming_decode_never_replays_frames_after_a_late_failure(monkeypatch, tmp_path):
    ds = mr_dataset()
    path = tmp_path / 'source.dcm'
    ds.save_as(path, enforce_file_format=True)
    def frames(*args, **kwargs):
        yield np.array([123])
        raise ValueError('bad later frame')
    monkeypatch.setattr(codecs, 'iter_pixels', frames)
    monkeypatch.setattr(codecs, '_dataset_fallback', lambda *a: pytest.fail('must not replay'))
    iterator = codecs.iter_decoded_pixels(path)
    np.testing.assert_array_equal(next(iterator), [123])
    with pytest.raises(codecs.PixelDecodeError):
        next(iterator)
