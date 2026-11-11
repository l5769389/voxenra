"""Check external dcmqi output against a known mask, then re-export it.

Run after validate_dicom_results.py and check_dcmqi_results.py:
python tests/manual/check_segmentation_import.py RESULTS_ROOT DCMQI_BIN
No source DICOM is modified. Outputs remain in RESULTS_ROOT.
"""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from voxplane.core.dicom_results import SegmentResult, write_results
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.segmentation_import import read_segmentation
from voxplane.core.volume_manager import VolumeManager

root, binaries = map(Path, sys.argv[1:3])
manifest = json.loads((root / "manifest.json").read_text())
paths = list(map(Path, manifest["source_paths"]))
external = root / "dcmqi-generated-seg.dcm"
result = subprocess.run(
    [
        str(binaries / "itkimage2segimage"),
        "--inputImageList",
        str(root / "decoded/1.nrrd"),
        "--inputMetadata",
        str(root / "decoded/meta.json"),
        "--inputDICOMList",
        ",".join(map(str, paths)),
        "--outputDICOM",
        str(external),
    ],
    capture_output=True,
    text=True,
    timeout=120,
)
(root / "itkimage2segimage.log").write_text(result.stdout + result.stderr)
assert result.returncode == 0, result.stderr
snapshot = list(DicomFolderScanner().scan_files(paths, folder=paths[0].parent))[-1]
series = max(snapshot.series, key=lambda s: len(s.instances))
volume = VolumeManager().get_or_build(series)
records, evaluations = read_segmentation(external, volume, series.instances)
assert len(records) == 1
expected = np.load(root / "expected-mask.npz")
record = records[0]
# Stored masks are cropped to foreground, so compare occupied native indices.
actual_indices = np.argwhere(record["mask"]) + record["mask_offset"]
expected_indices = np.argwhere(expected["mask"]) + expected["offset"]
np.testing.assert_array_equal(actual_indices, expected_indices)
output, _ = write_results(
    root, segments=[SegmentResult(record, evaluations[record["id"]], series.instances)]
)
restored, _ = read_segmentation(output / "SEG-001.dcm", volume, series.instances)
np.testing.assert_array_equal(restored[0]["mask"], record["mask"])
assert restored[0]["mask_offset"] == record["mask_offset"]
summary = dict(
    external_producer="dcmqi",
    imported_voxels=len(actual_indices),
    voxels_identical=True,
    reexport_identical=True,
    output=str(output),
)
(root / "import-verification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
