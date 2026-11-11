from __future__ import annotations

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import (
    DicomFolderScanSnapshot,
    DicomInstanceMeta,
    DicomSeriesRecord,
    MontageRenderRequest,
    MontageRenderResult,
    PixelSpacing,
    WindowLevel,
)
from voxplane.ui.workers.dicom_render_worker import DicomRenderWorker


def _dataset() -> FileDataset:
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 1
    dataset.PixelData = np.array(
        [[-1000, 0], [40, 1000]],
        dtype=np.int16,
    ).tobytes()
    dataset.RescaleSlope = 1
    dataset.RescaleIntercept = 0
    dataset.WindowCenter = 40
    dataset.WindowWidth = 400
    dataset.SOPInstanceUID = generate_uid()
    dataset.InstanceNumber = 1
    dataset.PixelSpacing = [1.0, 1.0]
    return dataset


def _catalog(tmp_path) -> SeriesCatalog:
    instance = DicomInstanceMeta(
        path=tmp_path / "slice.dcm",
        patient_name="Patient",
        patient_id="P001",
        study_description="Study",
        study_instance_uid="study-1",
        series_description="Series",
        series_instance_uid="series-1",
        series_number=1,
        instance_number=1,
        sop_instance_uid="sop-1",
        pixel_spacing=PixelSpacing(row=1.0, column=1.0),
        modality="CT",
        rows=2,
        columns=2,
        transfer_syntax="Explicit VR Little Endian",
        image_position_patient=None,
        image_orientation_patient=None,
        slice_thickness=None,
    )
    catalog = SeriesCatalog()
    catalog.update(
        DicomFolderScanSnapshot(
            folder=tmp_path,
            total_file_count=1,
            dicom_file_count=1,
            skipped_file_count=0,
            series=[
                DicomSeriesRecord(
                    patient_name=instance.patient_name,
                    patient_id=instance.patient_id,
                    study_description=instance.study_description,
                    study_instance_uid=instance.study_instance_uid,
                    series_description=instance.series_description,
                    series_instance_uid=instance.series_instance_uid,
                    series_number=1,
                    modality="CT",
                    instances=(instance,),
                )
            ],
        )
    )
    return catalog


def _request(request_id: str, window=None) -> MontageRenderRequest:
    return MontageRenderRequest(
        request_id=request_id,
        viewport_id="montage-1",
        series_uid="series-1",
        slice_index=0,
        window=window,
        inverted=False,
    )


def test_montage_worker_reuses_cached_modality_pixels_for_windowing(
    tmp_path,
    monkeypatch,
) -> None:
    from voxplane.core.dicom_loader import DicomLoader
    from pydicom.uid import CTImageStorage
    dataset = _dataset()
    dataset.SOPClassUID = CTImageStorage
    dataset.Modality = "CT"
    dataset.save_as(tmp_path / "slice.dcm", enforce_file_format=True)
    reads = []
    decode = DicomLoader.to_modality_pixels
    monkeypatch.setattr(DicomLoader, "to_modality_pixels", staticmethod(
        lambda source: reads.append(source.SOPInstanceUID) or decode(source)))
    worker = DicomRenderWorker(_catalog(tmp_path), VolumeManager())
    results = []
    worker.render_finished.connect(results.append)

    worker.handleRenderRequest(_request("request-1"))
    worker.handleRenderRequest(
        _request("request-2", WindowLevel(center=80.0, width=200.0))
    )

    assert len(reads) == 1
    assert all(isinstance(result, MontageRenderResult) for result in results)
    assert results[0].frame_meta.window == WindowLevel(40.0, 400.0)
    assert results[1].frame_meta.window == WindowLevel(80.0, 200.0)
    assert results[0].image_key == "montage-1:slice:0"
    assert worker._montage_cache.total_bytes == 16
