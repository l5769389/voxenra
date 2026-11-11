"""Cross-check merged viewer decoding/geometry with Slicer's native GDCM reader.

INTEGRATION_ROOT=/absolute/ignored/output .venv/bin/python this_script.py
INTEGRATION_STAGE=slicer INTEGRATION_ROOT=... Slicer --python-script this_script.py
Use VOXPLANE_TEST_DICOM_DIR to override the local sample library. No downloads.
"""

import hashlib
import json
import os
from pathlib import Path
import traceback

import numpy as np

root = Path(os.environ["INTEGRATION_ROOT"]).resolve()
root.mkdir(parents=True, exist_ok=True)


def digest(array):
    return hashlib.sha256(
        np.ascontiguousarray(array, dtype=np.float32).tobytes()
    ).hexdigest()


def prepare():
    import pydicom
    from voxplane.core.dicom_scanner import DicomFolderScanner
    from voxplane.core.dicom_loader import DicomLoader
    from voxplane.core.volume_manager import VolumeManager

    library = Path(
        os.environ.get("VOXPLANE_TEST_DICOM_DIR", "/Users/jun/Documents/test_dicom")
    )
    compressed = library / "Compressed_DICOM_Public_20260916"
    cases = []
    for item in json.loads((compressed / "manifest.json").read_text()):
        if (
            item["frames"] != 1
            or item["photometric"] not in ("MONOCHROME1", "MONOCHROME2")
            or item["file"].endswith(("JPEG-lossy.dcm", "JPEGLSNearLossless_16.dcm"))
        ):
            continue
        cases.append((Path(item["file"]).stem, [compressed / item["file"]]))
    cases.append(
        ("enhanced-ct", [library / "VoxPlane-EnhancedCT-TestData/NEMA-2006/01-CT0001"])
    )
    # Existing local manifests identify exactly the same source series used before.
    for name, previous in [("p113", "p113-final"), ("mr", "mr-thin")]:
        manifest = json.loads(
            (
                Path(".worktrees/segmentation-export-report/build/validation/seg-sr")
                / previous
                / "manifest.json"
            ).read_text()
        )
        cases.append((name, list(map(Path, manifest["source_paths"]))))
    records = []
    for name, files in cases:
        scanned = list(
            DicomFolderScanner().scan_files(
                files, folder=files[0].parent, can_publish=lambda: False
            )
        )[-1]
        assert len(scanned.series) == 1
        series = scanned.series[0]
        if len(series.instances) > 1:
            volume = VolumeManager().get_or_build(series)
            pixels = volume.modality_pixels
            affine = volume.geometry.voxel_to_patient
        else:
            instance = series.instances[0]
            _, image = DicomLoader().read_frame(instance.path, instance.frame_index)
            pixels = image[None]
            affine = None
        if affine is None:
            np.save(root / (name + "-viewer.npy"), pixels)
        header = pydicom.dcmread(files[0], stop_before_pixels=True)
        records.append(
            dict(
                name=name,
                lossy=str(header.get("LossyImageCompression", "00")) == "01",
                rescale_slope=float(header.get("RescaleSlope", 1)),
                files=[str(p) for p in dict.fromkeys(i.path for i in series.instances)],
                modality=series.modality,
                shape=list(pixels.shape),
                sha256=digest(pixels),
                affine=None if affine is None else affine.tolist(),
            )
        )
    (root / "images-manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print("PREPARED", len(records))


def capture():
    import slicer
    import vtk
    from DICOMScalarVolumePlugin import DICOMScalarVolumePluginClass

    report = {
        "slicer_version": slicer.app.applicationVersion,
        "reader": "GDCM",
        "cases": [],
    }
    for case in json.loads((root / "images-manifest.json").read_text()):
        slicer.mrmlScene.Clear(0)
        result = {"name": case["name"]}
        try:
            volume = DICOMScalarVolumePluginClass().loadFilesWithSeriesReader(
                "GDCM", case["files"], case["name"]
            )
            assert volume is not None and volume.GetImageData() is not None
            pixels = slicer.util.arrayFromVolume(volume)
            result["shape"] = list(pixels.shape)
            if case["affine"] is not None:
                matrix = vtk.vtkMatrix4x4()
                volume.GetIJKToRASMatrix(matrix)
                affine = (
                    np.diag([-1, -1, 1, 1])
                    @ np.array(
                        [[matrix.GetElement(i, j) for j in range(4)] for i in range(4)]
                    )[:, [2, 1, 0, 3]]
                )
                transform = np.linalg.inv(affine) @ case["affine"]
                permutation = np.argmax(np.abs(transform[:3, :3]), axis=0).tolist()
                assert len(set(permutation)) == 3
                signed = np.zeros((3, 3))
                for j, i in enumerate(permutation):
                    signed[i, j] = np.sign(transform[i, j])
                    assert (
                        abs(
                            transform[i, 3]
                            - (pixels.shape[i] - 1 if signed[i, j] < 0 else 0)
                        )
                        < 0.01
                    )
                np.testing.assert_allclose(transform[:3, :3], signed, atol=1e-5)
                pixels = pixels.transpose(permutation)
                for j, i in enumerate(permutation):
                    if signed[i, j] < 0:
                        pixels = np.flip(pixels, j)
                result["patient_geometry_identical"] = True
            assert list(pixels.shape) == case["shape"]
            result["voxels_identical"] = digest(pixels) == case["sha256"]
            if case["affine"] is None:
                expected = np.load(root / (case["name"] + "-viewer.npy"))
                valid = np.isfinite(expected)
                result["padding_pixels_excluded"] = int((~valid).sum())
                actual32 = pixels.astype(np.float32)
                result["finite_values_identical"] = np.array_equal(
                    expected[valid].astype(np.float32), actual32[valid]
                )
                delta = (
                    pixels[valid].astype(float) - expected[valid].astype(float)
                ) / abs(case["rescale_slope"])
                result["max_difference_stored_levels"] = float(np.max(np.abs(delta)))
                result["differing_stored_levels_pixels"] = int(
                    np.count_nonzero(np.abs(delta) > 0.5)
                )
                if not result["finite_values_identical"]:
                    np.save(root / (case["name"] + "-slicer.npy"), pixels)
                    assert case["lossy"] and np.max(np.abs(delta)) <= 1.001, (
                        "Unexpected decoding difference"
                    )
                    result["comparison"] = "lossy_decoder_difference"
                else:
                    result["comparison"] = "identical_valid_samples"
            else:
                assert result["voxels_identical"], "Decoded voxel values differ"
                result["comparison"] = "identical_volume_and_geometry"
            slicer.util.setSliceViewerLayers(background=volume)
            slicer.util.resetSliceViews()
            if case["affine"] is not None:
                logic = slicer.modules.volumerendering.logic()
                display = logic.CreateDefaultVolumeRenderingNodes(volume)
                display.GetVolumePropertyNode().Copy(
                    logic.GetPresetByName(
                        "MR-Default" if case["modality"] == "MR" else "CT-AAA"
                    )
                )
                display.SetVisibility(True)
                slicer.util.resetThreeDViews()
            slicer.util.mainWindow().resize(1400, 900)
            slicer.app.processEvents()
            assert (
                slicer.util.mainWindow()
                .grab()
                .save(str(root / (case["name"] + ".png")))
            )
        except Exception as error:  # noqa: BLE001 - keep evidence for every independent sample
            result["error"] = str(error)
            result["traceback"] = traceback.format_exc()
        report["cases"].append(result)
        (root / "slicer-images.json").write_text(json.dumps(report, indent=2) + "\n")
        print("CASE", result, flush=True)
    slicer.app.exit(1 if any("error" in c for c in report["cases"]) else 0)


if os.environ.get("INTEGRATION_STAGE") == "slicer":
    capture()
else:
    prepare()
