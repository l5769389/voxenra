from pathlib import Path
from threading import Event

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset
from pydicom.uid import CTImageStorage, RLELossless
from PySide6.QtGui import QImage

from voxplane.core.series_export import ExportCancelled, ExportError, ExportRequest, export_series
from voxplane.core.export_images import frame_image
from voxplane.ui.controller.series_export_controller import SeriesExportController
from voxplane.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, make_dicom, make_series, catalog_for, wait_until


@pytest.mark.parametrize("encoding", ["explicit", "implicit", "rle"])
def test_anonymous_dicom_preserves_pixels_geometry_and_uid_references(tmp_path, encoding):
    paths, originals = [], []
    for index in (1, 2):
        path = tmp_path / f"SECRET-{index}.dcm"
        ds = make_dicom(path, index, implicit=encoding == "implicit")
        ds.PatientID = "SECRET-PATIENT"
        ds.PatientName = "SECRET^NAME"
        ds.PatientBirthDate = "19801231"
        ds.PatientAddress = "SECRET-ADDRESS"
        ds.InstitutionName = "SECRET-HOSPITAL"
        ds.AccessionNumber = "SECRET-ACCESS"
        ds.DeviceSerialNumber = "SECRET-DEVICE"
        ds.StudyDate = "20260907"
        ds.FrameOfReferenceUID = "1.2.3.99"
        ds.ImagePositionPatient = [1, 2, index * 3]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ref = Dataset()
        ref.ReferencedSOPClassUID = CTImageStorage
        ref.ReferencedSOPInstanceUID = "1.2.826.0.1.3680043.10.999.2"
        ref.PatientName = "SECRET^NESTED"
        ref.add_new((0x0011, 0x1010), "LO", "SECRET-PRIVATE")
        ds.ReferencedImageSequence = [ref]
        ds.OriginalAttributesSequence = [ref]
        ds.IconImageSequence = [ref]
        ds.add_new((0x6000, 0x3000), "OW", b"SECRET-OVERLAY ")
        ds.file_meta.SourceApplicationEntityTitle = "SECRET-AE"
        ds.preamble = b"SECRET" + b"\0" * 122
        if encoding == "rle":
            ds.compress(RLELossless, generate_instance_uid=False)
        ds.save_as(path, enforce_file_format=True)
        paths.append(path)
        originals.append(path.read_bytes())
    result = export_series(ExportRequest(tuple(paths), tmp_path / "output"))
    files = sorted(result.directory.glob("*.dcm"))
    assert result.file_count == len(files) == 2
    datasets = [pydicom.dcmread(path) for path in files]
    for original, output, raw in zip(paths, datasets, files):
        source = pydicom.dcmread(original)
        assert b"SECRET" not in raw.read_bytes()
        assert output.PatientName == "ANONYMOUS"
        assert output.PatientIdentityRemoved == "YES"
        assert output.PatientID != source.PatientID
        assert output.PatientBirthDate == ""
        assert output.SeriesInstanceUID != source.SeriesInstanceUID
        assert output.StudyInstanceUID != source.StudyInstanceUID
        assert output.FrameOfReferenceUID != source.FrameOfReferenceUID
        assert output.SOPInstanceUID != source.SOPInstanceUID
        assert output.SOPClassUID == source.SOPClassUID
        assert output.PixelData == source.PixelData
        np.testing.assert_array_equal(output.pixel_array, source.pixel_array)
        assert output.ImagePositionPatient == source.ImagePositionPatient
        assert output.PixelSpacing == source.PixelSpacing
        assert output.RescaleIntercept == source.RescaleIntercept
        assert output.NumberOfFrames == 2
        assert output.file_meta.TransferSyntaxUID == source.file_meta.TransferSyntaxUID
        assert output.file_meta.MediaStorageSOPInstanceUID == output.SOPInstanceUID
        assert output.preamble == b"\0" * 128
        assert "SourceApplicationEntityTitle" not in output.file_meta
        assert "OriginalAttributesSequence" not in output and "IconImageSequence" not in output
        assert all(not element.tag.is_private for element in output.iterall())
    assert len({str(ds.PatientID) for ds in datasets}) == 1
    assert len({str(ds.SeriesInstanceUID) for ds in datasets}) == 1
    assert len({str(ds.StudyInstanceUID) for ds in datasets}) == 1
    assert len({str(ds.FrameOfReferenceUID) for ds in datasets}) == 1
    for ds in datasets:
        assert ds.ReferencedImageSequence[0].ReferencedSOPInstanceUID == datasets[1].SOPInstanceUID
        assert ds.ReferencedImageSequence[0].ReferencedSOPClassUID == CTImageStorage
    assert [path.read_bytes() for path in paths] == originals


def test_identified_dicom_is_exact_copy_and_exports_never_overwrite(tmp_path):
    series = make_series(tmp_path, 2)
    paths = tuple(i.path for i in series.instances)
    request = ExportRequest(paths, tmp_path / "out", anonymous=False)
    first, second = export_series(request), export_series(request)
    assert first.directory != second.directory
    for folder in (first.directory, second.directory):
        assert [p.read_bytes() for p in sorted(folder.iterdir())] == [p.read_bytes() for p in paths]


@pytest.mark.parametrize("kind", ["gray", "inverted", "rgb", "palette", "rle"])
@pytest.mark.parametrize("anonymous", [True, False])
def test_png_exports_every_frame_at_original_resolution(tmp_path, kind, anonymous):
    path = tmp_path / "input.dcm"
    ds = make_dicom(path)
    ds.Rows, ds.Columns = 16, 32
    ds.RescaleSlope, ds.RescaleIntercept = 2, -64
    ds.WindowCenter, ds.WindowWidth = 192, 512
    ramp = np.tile(np.arange(32, dtype=np.uint16) * 8, (16, 1))
    if kind == "rgb":
        ds.SamplesPerPixel, ds.PlanarConfiguration = 3, 0
        ds.PhotometricInterpretation = "RGB"
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        pixels = np.zeros((2, 16, 32, 3), dtype=np.uint8)
        pixels[0, :, :, 0] = 255
        pixels[1, :, :, 1] = 255
    else:
        pixels = np.stack([ramp, np.full_like(ramp, 128)])
        if kind == "inverted":
            ds.PhotometricInterpretation = "MONOCHROME1"
        elif kind == "palette":
            ds.PhotometricInterpretation = "PALETTE COLOR"
            for channel in ("Red", "Green", "Blue"):
                setattr(ds, channel + "PaletteColorLookupTableDescriptor", [256, 0, 16])
                lut = np.arange(256, dtype=np.uint16) * 257 if channel == "Red" else np.zeros(256, dtype=np.uint16)
                setattr(ds, channel + "PaletteColorLookupTableData", lut.tobytes())
    ds.PixelData = pixels.tobytes()
    if kind == "rle":
        ds.compress(RLELossless)
    ds.save_as(path, enforce_file_format=True)
    original = path.read_bytes()
    progress = []
    result = export_series(ExportRequest((path,), tmp_path / "out", "png", anonymous),
                           progress=lambda done, total: progress.append((done, total)))
    files = sorted(result.directory.glob("*.png"))
    assert result.file_count == len(files) == 2
    assert progress[-1] == (2, 2)
    images = [QImage(str(p)) for p in files]
    for image in images:
        assert (image.width(), image.height()) == (32, 16)
        assert ("PatientName" not in image.textKeys()) if anonymous else image.text("PatientName") == str(ds.PatientName)
    # Literal window reference: (2 * stored - 64 - (-64)) / 512 * 255.
    # Checking each channel of every pixel catches replayed/blank later frames.
    gray_row = [0, 7, 15, 23, 31, 39, 47, 55, 63, 71, 79, 87, 95, 103,
                111, 119, 127, 135, 143, 151, 159, 167, 175, 183, 191, 199,
                207, 215, 223, 231, 239, 247]
    inverted_row = [255, 247, 239, 231, 223, 215, 207, 199, 191, 183, 175,
                    167, 159, 151, 143, 135, 127, 119, 111, 103, 95, 87,
                    79, 71, 63, 55, 47, 39, 31, 23, 15, 7]
    for frame, image in enumerate(images):
        for y in range(16):
            for x in range(32):
                if kind == "rgb":
                    expected = (255, 0, 0, 255) if frame == 0 else (0, 255, 0, 255)
                elif kind == "palette":
                    expected = (x * 8 if frame == 0 else 128, 0, 0, 255)
                else:
                    row = inverted_row if kind == "inverted" else gray_row
                    value = row[x] if frame == 0 else 127
                    expected = (value, value, value, 255)
                assert image.pixelColor(x, y).getRgb() == expected, (kind, frame, x, y)
    assert path.read_bytes() == original


def test_per_frame_windows_do_not_modify_dataset():
    ds = Dataset()
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.WindowCenter, ds.WindowWidth = 50, 100
    group = Dataset()
    voi = Dataset()
    voi.WindowCenter, voi.WindowWidth = 100, 200
    group.FrameVOILUTSequence = [voi]
    ds.PerFrameFunctionalGroupsSequence = [group]
    image = frame_image(np.array([[50]], dtype=np.uint16), ds)
    assert 62 <= image.pixelColor(0, 0).red() <= 64
    assert ds.WindowCenter == 50 and ds.WindowWidth == 100


@pytest.mark.parametrize("format", ["png", "dicom"])
def test_burned_in_late_instance_blocks_anonymous_export(tmp_path, format):
    series = make_series(tmp_path, 2)
    ds = pydicom.dcmread(series.instances[-1].path)
    ds.BurnedInAnnotation = "YES"
    ds.save_as(series.instances[-1].path, enforce_file_format=True)
    root = tmp_path / "out"
    with pytest.raises(ExportError, match="烧录"):
        export_series(ExportRequest(tuple(i.path for i in series.instances), root, format))
    assert not root.exists()


def test_cancel_and_decode_failure_remove_partial_outputs(tmp_path, monkeypatch):
    series = make_series(tmp_path, 2)
    request = ExportRequest(tuple(i.path for i in series.instances), tmp_path / "out", "png")
    cancel = Event()
    with pytest.raises(ExportCancelled):
        export_series(request, cancel=cancel, progress=lambda done, _: cancel.set() if done == 1 else None)
    assert not list(request.directory.iterdir())
    from voxplane.core import series_export
    real_image = series_export.frame_image
    calls = []
    def failing_image(*args):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("SECRET-PATIENT/path/decoder error")
        return real_image(*args)
    monkeypatch.setattr(series_export, "frame_image", failing_image)
    with pytest.raises(ExportError) as error:
        export_series(request)
    assert "SECRET" not in str(error.value)
    assert not list(request.directory.iterdir())


def test_invalid_destination_and_missing_source_are_reported(tmp_path):
    source = tmp_path / "input.dcm"
    make_dicom(source)
    root = tmp_path / "out"
    root.write_text("existing file")
    with pytest.raises(ExportError, match="目录"):
        export_series(ExportRequest((source,), root))
    assert root.read_text() == "existing file"
    with pytest.raises(ExportError, match="读取"):
        export_series(ExportRequest((tmp_path / "missing.dcm",), tmp_path / "unused"))
    assert not (tmp_path / "unused").exists()


def test_export_directory_persists_validates_and_resets(qt_app, tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"scale":{"enabled":false}}')
    settings = SettingsController(path=settings_path)
    assert Path(settings.exportDirectory).is_absolute()
    assert settings.exportDirectory == settings.defaultExportDirectory
    custom = tmp_path / "中文 导出"
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(custom))
    settings.chooseExportDirectory()
    assert SettingsController(path=settings_path).exportDirectory == str(custom)
    before = settings_path.read_bytes()
    for value in (42, "relative/path", str(settings_path), "bad\x00path"):
        assert not settings.setValue("export", "directory", value)
        assert settings_path.read_bytes() == before
    assert settings.resetSection("export")
    assert settings.exportDirectory == settings.defaultExportDirectory
    assert settings.section("scale")["enabled"] is False


def test_background_export_locks_anonymous_and_snapshots_selected_series(qt_app, tmp_path):
    series = make_series(tmp_path, 2)
    settings = SettingsController(path=False)
    settings.setValue("export", "directory", str(tmp_path / "out"))
    controller = SeriesExportController(catalog_for(series, tmp_path), settings)
    try:
        controller.openSeries(series.series_instance_uid, True)
        controller.startExport("dicom", False)
        assert controller.busy
        controller.openSeries("missing", False)
        controller.startExport("png", False)
        wait_until(lambda: not controller.busy)
        assert controller.anonymousLocked
        output = Path(controller.outputDirectory)
        assert len(list(output.glob("*.dcm"))) == 2
        assert all(pydicom.dcmread(p).PatientIdentityRemoved == "YES" for p in output.iterdir())
        controller.closeDialog()
        controller.startExport("png", False)
        assert not controller.busy
    finally:
        controller.shutdown()
