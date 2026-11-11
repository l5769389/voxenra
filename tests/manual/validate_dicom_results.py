"""Export a validation ROI/segment from a local series; never modifies sources.

python tests/manual/validate_dicom_results.py SOURCE_DIRECTORY OUTPUT_DIRECTORY
Generated patient-linked DICOM and local manifests must stay outside Git.
"""

from pathlib import Path
from uuid import uuid4
import json
import sys
import numpy as np

from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.volume_manager import VolumeManager
from voxplane.core.dicom_results import (
    SegmentResult,
    PlanarResult,
    write_results,
)
from voxplane.core.mpr_voi import VoiRegion, evaluate_voi
from voxplane.core.measurement_geometry import roi_metrics
from voxplane.model import ImagePoint, MeasurementKind
from voxplane.model.measure import RoiMeasurement

source, output = map(Path, sys.argv[1:3])
output.mkdir(parents=True, exist_ok=True)
files = [p for p in source.rglob("*") if p.is_file()]
snapshot = list(
    DicomFolderScanner().scan_files(files, folder=source, can_publish=lambda: False)
)[-1]
series = max(snapshot.series, key=lambda s: len(s.instances))
volume = VolumeManager().get_or_build(series)
g = volume.geometry
size = (
    np.array(
        [
            g.columns * g.column_spacing,
            g.rows * g.row_spacing,
            g.slice_count * g.slice_spacing,
        ]
    )
    * 0.45
)
region = VoiRegion(
    tuple(g.center_patient),
    tuple(
        map(
            tuple,
            (
                g.column_index_direction_patient,
                g.row_index_direction_patient,
                g.slice_index_direction_patient,
            ),
        )
    ),
    tuple(size),
)
threshold = (
    150
    if series.modality == "CT"
    else float(np.nanpercentile(volume.modality_pixels, 80))
)
evaluation = evaluate_voi(volume, region, threshold=threshold)
record = dict(
    id=str(uuid4()),
    series=series.series_instance_uid,
    name="Validation region",
    kind="segmentation",
    unitLabel="HU" if series.modality == "CT" else "MR signal",
    color="#43c6dc",
)
k = g.slice_count // 2
instance = series.instances[k]
points = tuple(
    ImagePoint(x * g.columns, y * g.rows)
    for x, y in [(0.3, 0.35), (0.6, 0.32), (0.65, 0.55), (0.5, 0.48), (0.35, 0.6)]
)
metrics = roi_metrics(
    points,
    MeasurementKind.FREEHAND,
    volume.modality_pixels[k],
    row_spacing=g.row_spacing,
    column_spacing=g.column_spacing,
    unit=record["unitLabel"],
)
roi = RoiMeasurement(
    str(uuid4()),
    series.series_instance_uid,
    instance.sop_instance_uid,
    k,
    MeasurementKind.FREEHAND,
    points,
    metrics,
)
frame = (
    series.series_instance_uid,
    instance.sop_instance_uid,
    k,
    g.rows,
    g.columns,
    (
        g.row_spacing,
        g.column_spacing,
        *instance.image_position_patient,
        *instance.image_orientation_patient,
    ),
)
folder, count = write_results(
    output,
    [PlanarResult(roi, frame, series.instances)],
    [SegmentResult(record, evaluation, series.instances)],
)
np.savez_compressed(
    output / "expected-mask.npz",
    mask=evaluation.mask,
    offset=evaluation.offset,
    affine=g.voxel_to_patient,
    shape=volume.modality_pixels.shape,
)
manifest = dict(
    output=str(folder.resolve()),
    source_paths=[str(i.path) for i in series.instances],
    count=count,
    voxel_count=evaluation.metrics["count"],
    volume_cm3=evaluation.metrics["volume"],
    roi_area_mm2=metrics.area_mm2,
    roi_perimeter_mm=metrics.perimeter_mm,
)
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({k: v for k, v in manifest.items() if k != "source_paths"}, indent=2))
