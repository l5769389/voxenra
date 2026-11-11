"""Check GUI roundtrip evidence and independently decode all SR cases with dcmqi.

python tests/manual/check_slicer_roundtrip.py ROOT SOURCE_MANIFEST DCMQI_BIN
An exit code of zero means evidence/numerical checks passed, not all SRs loaded.
Inspect summary.json's sr_gui_loaded and all_sr_gui_loaded compatibility results.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pydicom


def read(path):
    return json.loads(path.read_text())


root, manifest_path, binaries = map(Path, sys.argv[1:4])
manifest = read(manifest_path)
edited = read(root / "slicer-edit.json")
bridge = read(root / "voxplane.json")
returned = read(root / "slicer-return.json")
assert edited["gui_apply_enabled"]
assert not bridge["qml_warnings"]
assert (
    len(edited["counts"]) == len(bridge["segments"]) == len(returned["segments"]) == 2
)
for i, (imported, final) in enumerate(
    zip(bridge["segments"], returned["segments"], strict=True)
):
    assert imported["identical"] and final["identical"]
    assert imported["count"] == final["voxels"] == edited["counts"][i]
    assert imported["name"] == final["name"] == edited["names"][i]
assert edited["overlap"] == edited["original_voxels"] > 0

metrics = {
    "Volume": "volume",
    "Mean": "mean",
    "Standard deviation": "sd",
    "Minimum": "minimum",
    "Maximum": "maximum",
    "Voxel count": "count",
}
decoded = root / "decoded-reports"
decoded.mkdir(exist_ok=True)
table_checks = {}
for label, directory in [
    ("volume", Path(bridge["output"])),
    ("single", Path(bridge["single_output"])),
    ("planar", Path(manifest["output"])),
]:
    destination = decoded / (label + ".json")
    result = subprocess.run(
        [
            str(binaries / "tid1500reader"),
            "--inputDICOM",
            str(directory / ("SR-002.dcm" if label == "planar" else "SR-001.dcm")),
            "--outputMetadata",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    (decoded / (label + ".log")).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    report = read(destination)
    groups = report["Measurements"]
    segment_uids = {
        str(pydicom.dcmread(p, stop_before_pixels=True).SOPInstanceUID)
        for p in directory.glob("SEG-*.dcm")
    }
    references = [g for g in groups if "segmentationSOPInstanceUID" in g]
    assert {g["segmentationSOPInstanceUID"] for g in references} == (
        set() if label == "planar" else segment_uids
    )
    if label == "planar":
        quantities = {
            item["quantity"]["CodeMeaning"]: float(item["value"])
            for group in groups
            for item in group["measurementItems"]
        }
        for quantity, key in [
            ("Area", "roi_area_mm2"),
            ("Perimeter", "roi_perimeter_mm"),
        ]:
            np.testing.assert_allclose(
                quantities[quantity], manifest[key], rtol=1e-12, atol=0
            )
        continue
    expected = bridge["segments"][:1] if label == "single" else bridge["segments"]
    assert len(groups) == len(expected)
    assert [g["ReferencedSegment"] for g in groups] == list(range(1, len(expected) + 1))
    for group, segment in zip(groups, expected, strict=True):
        quantities = {
            item["quantity"]["CodeMeaning"]: item for item in group["measurementItems"]
        }
        for quantity, key in metrics.items():
            np.testing.assert_allclose(
                float(quantities[quantity]["value"]),
                segment["metrics"][key],
                rtol=1e-12,
                atol=0,
            )
    # A partially created table does not count as successful plugin loading.
    gui = returned["reports"][label]
    assert len(gui["tables"]) == 1
    table = gui["tables"][0]
    assert len(table["rows"]) == len(expected)
    for row, group, segment in zip(table["rows"], groups, expected, strict=True):
        assert row[0] == group["TrackingIdentifier"]
        for quantity, key in metrics.items():
            column = next(
                i
                for i, name in enumerate(table["columns"])
                if name.startswith(quantity + " [")
            )
            np.testing.assert_allclose(
                float(row[column]), segment["metrics"][key], rtol=1e-12, atol=0
            )
            item = next(
                x
                for x in group["measurementItems"]
                if x["quantity"]["CodeMeaning"] == quantity
            )
            assert table["units"][column] == item["units"]["CodeMeaning"]
    table_checks[label] = True

assert returned["reports"]["single"]["loaded"], "Single-region SR plugin load failed"
assert returned["reports"]["volume"]["loaded"], "Multi-region SR plugin load failed"
summary = {
    "slicer_version": returned["slicer_version"],
    "margin_mm": edited["margin_mm"],
    "voxel_counts": edited["counts"],
    "overlap_voxels": edited["overlap"],
    "seg_import_identical": True,
    "seg_return_identical": True,
    "qml_warnings": [],
    "dcmqi_sr_values_and_references_verified": True,
    "gui_table_values_and_units_verified": table_checks,
    "sr_gui_loaded": {
        name: result["loaded"] for name, result in returned["reports"].items()
    },
    "all_sr_gui_loaded": all(
        result["loaded"] for result in returned["reports"].values()
    ),
}
(root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
