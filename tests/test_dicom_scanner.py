from dataclasses import replace
from pathlib import Path

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

from voxplane.core.dicom_scanner import (
    _build_series_record,
    _iter_visible_files,
    _read_instance,
)
from voxplane.model import PixelSpacing

#
# a.txt
# b.txt
# .hidden.txt
# visible
#    /nested.txt
# .hidden-dir
#    /should-not-appear.txt
def create_path(tmp_path: Path) -> None:
    (tmp_path / "b.txt").touch()
    (tmp_path / "a.txt").touch()
    (tmp_path / ".hidden.txt").touch()

    visible_dir = tmp_path / "visible"
    visible_dir.mkdir()
    (visible_dir / "nested.txt").touch()

    hidden_dir = tmp_path / ".hidden-dir"
    hidden_dir.mkdir()
    (hidden_dir / "should-not-appear.txt").touch()

def test_iter_visible_files_skips_hidden_entries_and_recurses(tmp_path: Path) -> None:
    create_path(tmp_path)
    paths = [path.relative_to(tmp_path).as_posix() for path in _iter_visible_files(tmp_path)]
    assert paths == ['a.txt', 'b.txt', 'visible/nested.txt']


def test_read_instance_extracts_typed_identity_and_geometry(tmp_path: Path) -> None:
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    dataset = FileDataset(
        str(tmp_path / "slice.dcm"),
        {},
        file_meta=file_meta,
        preamble=b"\0" * 128,
    )
    dataset.PatientName = "Example Patient"
    dataset.PatientID = "P001"
    dataset.PatientSex = "M"
    dataset.PatientAge = "034Y"
    dataset.StudyInstanceUID = "1.2.3"
    dataset.SeriesInstanceUID = "1.2.3.4"
    dataset.SOPInstanceUID = "1.2.3.4.5"
    dataset.SOPClassUID = CTImageStorage
    dataset.Modality = "CT"
    dataset.SeriesNumber = 2
    dataset.InstanceNumber = 7
    dataset.Rows = 512
    dataset.Columns = 512
    dataset.PixelSpacing = [0.7, 0.8]
    dataset.SliceThickness = 0.625
    dataset.AcquisitionDateTime = "20230724105538"
    dataset.KVP = 120
    dataset.XRayTubeCurrent = 30
    dataset.ImagePositionPatient = [-120.5, -90.25, 42.0]
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.save_as(dataset.filename, enforce_file_format=True)

    instance = _read_instance(Path(dataset.filename))

    assert instance is not None
    assert instance.sop_instance_uid == "1.2.3.4.5"
    assert instance.pixel_spacing == PixelSpacing(row=0.7, column=0.8)
    assert instance.slice_thickness == 0.625
    assert instance.patient_sex == "M"
    assert instance.patient_age == "034Y"
    assert instance.acquisition_datetime == "2023.07.24 10:55:38"
    assert instance.kvp == 120.0
    assert instance.tube_current_ma == 30.0
    assert instance.image_position_patient == (-120.5, -90.25, 42.0)
    assert instance.image_orientation_patient == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    series = _build_series_record([instance])
    assert series.instances == (instance,)
    assert series.dicom_file_count == 1
    assert series.first_file == Path(dataset.filename)


def test_series_record_prefers_spatial_order_over_instance_number(
    tmp_path: Path,
) -> None:
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.10"
    dataset = FileDataset(
        str(tmp_path / "base.dcm"),
        {},
        file_meta=file_meta,
        preamble=b"\0" * 128,
    )
    dataset.StudyInstanceUID = "1.2.3"
    dataset.SeriesInstanceUID = "1.2.3.4"
    dataset.SOPInstanceUID = "1.2.3.4.10"
    dataset.SOPClassUID = CTImageStorage
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.ImagePositionPatient = [0, 0, 0]
    dataset.save_as(dataset.filename, enforce_file_format=True)

    base = _read_instance(Path(dataset.filename))
    assert base is not None

    upper = replace(
        base,
        path=tmp_path / "upper.dcm",
        sop_instance_uid="1.2.3.4.11",
        instance_number=1,
        image_position_patient=(0.0, 0.0, 10.0),
    )
    lower = replace(
        base,
        path=tmp_path / "lower.dcm",
        sop_instance_uid="1.2.3.4.12",
        instance_number=2,
        image_position_patient=(0.0, 0.0, 0.0),
    )

    series = _build_series_record([upper, lower])

    assert series.instances == (lower, upper)
