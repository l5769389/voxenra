"""CPU/memory benchmark through disk DICOM scanning and volume loading.

.venv/bin/python tests/manual/benchmark_volume_assembly.py OUTPUT.json
Generated inputs stay in build/. Timing uses warm filesystem caches and excludes
data generation/scanning. tracemalloc measures Python/NumPy allocations, not RSS.
"""
from dataclasses import asdict
import gc
from hashlib import sha256
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter
import tracemalloc

import numpy as np
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, PositronEmissionTomographyImageStorage

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.volume_manager import VolumeManager


def generate_case(folder, kind, slices=128, size=512):
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for z in range(slices):
        path = folder / f"{slices - z:04d}.dcm"
        files.append(path)
        if path.exists():
            continue
        uid = f"1.2.826.0.1.3680043.10.543.20261003.{1 if kind == 'ct' else 2}"
        sop_class = CTImageStorage if kind == "ct" else PositronEmissionTomographyImageStorage
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = sop_class
        meta.MediaStorageSOPInstanceUID = f"{uid}.3.{z+1}"
        d = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
        d.SOPClassUID, d.SOPInstanceUID = sop_class, meta.MediaStorageSOPInstanceUID
        d.StudyInstanceUID, d.SeriesInstanceUID, d.FrameOfReferenceUID = uid, f"{uid}.1", f"{uid}.2"
        d.PatientName, d.PatientID = "Synthetic^Benchmark", "SYNTHETIC"
        d.Modality = "CT" if kind == "ct" else "PT"
        d.SeriesNumber, d.InstanceNumber = 1, slices - z
        d.Rows = d.Columns = size
        d.SamplesPerPixel, d.PhotometricInterpretation = 1, "MONOCHROME2"
        d.BitsAllocated, d.BitsStored, d.HighBit, d.PixelRepresentation = 16, 16, 15, 0
        d.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        d.ImagePositionPatient, d.PixelSpacing, d.SliceThickness = [-32, 17, z * 1.5], [.7, .8], 1
        d.RescaleSlope, d.RescaleIntercept = .5 + (z % 3) / 4, -1024 if kind == "ct" else 0
        d.WindowCenter, d.WindowWidth = (40, 400) if kind == "ct" else (4000, 8000)
        if kind != "ct":
            d.Units, d.SeriesType = "BQML", ["STATIC", "IMAGE"]
            d.CorrectedImage, d.DecayCorrection = ["ATTN", "DECY"], "START"
            d.AcquisitionDateTime, d.PatientWeight = "20240101130000", 70
            r = Dataset()
            r.RadiopharmaceuticalStartDateTime = "20240101120000"
            r.RadionuclideTotalDose, r.RadionuclideHalfLife = 70_000_000, 3600
            d.RadiopharmaceuticalInformationSequence = [r]
            if kind == "pet-fallback" and z == slices - 1:
                del d.PatientWeight
        y, x = np.indices((size, size), dtype=np.uint16)
        d.PixelData = ((x * 3 + y * 7 + z * 17) % 8192).astype(np.uint16).tobytes()
        d.save_as(path, enforce_file_format=True)
    return files


def fingerprint(volume):
    return dict(pixels=sha256(volume.modality_pixels.tobytes()).hexdigest(),
                source=None if volume.source_pixels is None else sha256(volume.source_pixels.tobytes()).hexdigest(),
                geometry=asdict(volume.geometry), window=asdict(volume.default_window),
                value_meta=asdict(volume.pixel_value_meta))


def main():
    root = Path(__file__).resolve().parents[2]
    results = dict(python=platform.python_version(), numpy=np.__version__, platform=platform.platform(),
                   shape=[128, 512, 512], repeats=3, cases={})
    for kind in ("ct", "pet", "pet-fallback"):
        folder = root / "build/volume-loading-refactor/data" / kind
        files = generate_case(folder, kind)
        snapshot = list(DicomFolderScanner().scan_files(files, folder=folder, can_publish=lambda: False))[-1]
        assert len(snapshot.series) == 1
        series = snapshot.series[0]
        samples = []
        reference = None
        for _ in range(4):
            gc.collect()
            manager = VolumeManager()
            start = perf_counter()
            volume = manager.get_or_build(series)
            samples.append((perf_counter() - start) * 1000)
            actual = fingerprint(volume)
            assert reference is None or actual == reference
            reference = actual
            del volume, manager
        gc.collect()
        tracemalloc.start()
        manager = VolumeManager()
        volume = manager.get_or_build(series)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert fingerprint(volume) == reference
        results["cases"][kind] = dict(median_ms=median(samples[1:]), samples_ms=samples[1:],
            peak_allocated_mib=peak / 1024**2, retained_pixels_mib=manager.cache_bytes / 1024**2,
            result=reference,
            input_sha256=sha256(b"".join(sha256(p.read_bytes()).digest() for p in files)).hexdigest())
        del volume, manager
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: {n: v[n] for n in ("median_ms", "peak_allocated_mib", "retained_pixels_mib")}
                      for k, v in results["cases"].items()}, indent=2))


if __name__ == "__main__":
    main()
