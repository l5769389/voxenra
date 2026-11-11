"""Run in a separate Slicer process with ROUNDTRIP_ROOT, SOURCE_MANIFEST and ROUNDTRIP_STAGE.

Uses the installed Segment Editor and DICOM plugins, with a temporary database.
Patient-linked screenshots/data remain in the caller's ignored output directory.
"""

import json
import os
import traceback
from pathlib import Path

import ctk
import numpy as np
import pydicom
import slicer
import vtk
from DICOMLib import DICOMUtils
from DICOMSegmentationPlugin import DICOMSegmentationPluginClass
from DICOMTID1500Plugin import DICOMTID1500PluginClass

root = Path(os.environ["ROUNDTRIP_ROOT"])
root.mkdir(parents=True, exist_ok=True)
manifest = json.loads(Path(os.environ["SOURCE_MANIFEST"]).read_text())
stage = os.environ["ROUNDTRIP_STAGE"]
assert stage in {"edit", "verify"}, "ROUNDTRIP_STAGE must be edit or verify"


def save_json(name, result):
    (root / name).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def screenshot(name):
    slicer.util.mainWindow().resize(1400, 900)
    slicer.util.mainWindow().show()
    slicer.app.processEvents()
    assert slicer.util.mainWindow().grab().save(str(root / name))


def load_seg(path):
    plugin = DICOMSegmentationPluginClass()
    loadables = plugin.examineForImport([[str(path)]])
    assert loadables, "SEG not recognized"
    before = {n.GetID() for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode")}
    assert plugin.load(loadables[0]), "SEG plugin load failed"
    return next(
        n
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        if n.GetID() not in before
    )


def array(node, sid, volume):
    return slicer.util.arrayFromSegmentBinaryLabelmap(node, sid, volume).astype(bool)


try:
    with DICOMUtils.TemporaryDICOMDatabase(str(root / ("database-" + stage))):
        indexer = ctk.ctkDICOMIndexer()
        indexer.addListOfFiles(slicer.dicomDatabase, manifest["source_paths"])
        series_uid = str(
            pydicom.dcmread(
                manifest["source_paths"][0], stop_before_pixels=True
            ).SeriesInstanceUID
        )
        ids = DICOMUtils.loadSeriesByUID([series_uid])
        volume = next(
            slicer.mrmlScene.GetNodeByID(i)
            for i in ids
            if slicer.mrmlScene.GetNodeByID(i).IsA("vtkMRMLScalarVolumeNode")
        )
        slicer.util.setSliceViewerLayers(background=volume)
        slicer.app.layoutManager().setLayout(
            slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView
        )
        slicer.util.resetSliceViews()
        if stage == "edit":
            original = Path(manifest["output"]) / "SEG-001.dcm"
            slicer.dicomDatabase.insert(str(original))
            node = load_seg(original)
            node.SetReferenceImageGeometryParameterFromVolumeNode(volume)
            segmentation = node.GetSegmentation()
            sid = segmentation.GetNthSegmentID(0)
            original_mask = array(node, sid, volume)
            assert int(original_mask.sum()) == manifest["voxel_count"]
            copy = slicer.vtkSegment()
            copy.DeepCopy(segmentation.GetSegment(sid))
            copy.SetName("Slicer baseline")
            copy.SetColor(0.25, 0.8, 0.45)
            second = segmentation.AddSegment(copy)
            slicer.util.selectModule("SegmentEditor")
            widget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
            widget.setSegmentationNode(node)
            widget.setSourceVolumeNode(volume)
            widget.setCurrentSegmentID(sid)
            widget.mrmlSegmentEditorNode().SetOverwriteMode(
                slicer.vtkMRMLSegmentEditorNode.OverwriteNone
            )
            widget.setActiveEffectByName("Margin")
            effect = widget.activeEffect()
            assert effect
            effect_spacing = effect.selectedSegmentLabelmap().GetSpacing()
            margin_mm = max(3, float(np.ceil(max(effect_spacing))) + 1)
            effect.setParameter("MarginSizeMm", margin_mm)
            effect.self().updateGUIFromMRML()
            assert effect.self().applyButton.enabled, (
                "Margin is not feasible in the GUI"
            )
            effect.self().applyButton.click()
            segment = segmentation.GetSegment(sid)
            segment.SetName(f"Slicer edited margin {margin_mm:g}mm")
            segment.SetColor(0.95, 0.55, 0.15)
            segment.SetTag("DICOM.SegmentAlgorithmType", "SEMIAUTOMATIC")
            segment.SetTag(
                "DICOM.SegmentAlgorithmName", f"Slicer Margin {margin_mm:g}mm"
            )
            edited = array(node, sid, volume)
            assert edited.sum() > original_mask.sum()
            ids = [
                segmentation.GetNthSegmentID(i)
                for i in range(segmentation.GetNumberOfSegments())
            ]
            matrix = vtk.vtkMatrix4x4()
            volume.GetIJKToRASMatrix(matrix)
            ijk_ras = np.array(
                [[matrix.GetElement(i, j) for j in range(4)] for i in range(4)]
            )
            permutation = np.eye(4)[[2, 1, 0, 3]]
            affine = np.diag([-1, -1, 1, 1]) @ ijk_ras @ permutation
            masks = [array(node, i, volume) for i in ids]
            np.savez_compressed(
                root / "slicer-edited-masks.npz",
                affine=affine,
                **{f"mask{i}": m for i, m in enumerate(masks)},
            )
            sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(
                slicer.mrmlScene
            )
            plugin = DICOMSegmentationPluginClass()
            exportables = plugin.examineForExport(sh.GetItemByDataNode(node))
            assert exportables
            destination = root / "slicer-export"
            destination.mkdir(exist_ok=True)
            for exportable in exportables:
                exportable.directory = str(destination)
            existing_files = set(destination.glob("*.dcm"))
            error = plugin.export(exportables)
            assert not error, error
            files = sorted(set(destination.glob("*.dcm")) - existing_files)
            assert len(files) == 1
            screenshot("slicer-edited.png")
            save_json(
                "slicer-edit.json",
                {
                    "slicer_version": slicer.app.applicationVersion,
                    "exported": str(files[0]),
                    "effect": "Margin",
                    "margin_mm": margin_mm,
                    "effect_spacing": list(effect_spacing),
                    "gui_apply_enabled": True,
                    "original_voxels": int(original_mask.sum()),
                    "names": [segmentation.GetSegment(i).GetName() for i in ids],
                    "counts": [int(m.sum()) for m in masks],
                    "overlap": int(np.logical_and(*masks).sum()),
                },
            )
        else:
            bridge = json.loads((root / "voxplane.json").read_text())
            output = Path(bridge["output"])
            files = sorted(output.glob("SEG-*.dcm"))
            assert files, "Missing exported SEG files"
            indexer.addListOfFiles(
                slicer.dicomDatabase, [str(p) for p in output.glob("*.dcm")]
            )
            expected = np.load(root / "slicer-edited-masks.npz")
            checked = []
            for path in files:
                node = load_seg(path)
                segmentation = node.GetSegmentation()
                for n in range(segmentation.GetNumberOfSegments()):
                    sid = segmentation.GetNthSegmentID(n)
                    i = len(checked)
                    actual = array(node, sid, volume)
                    np.testing.assert_array_equal(actual, expected[f"mask{i}"])
                    checked.append(
                        {
                            "name": segmentation.GetSegment(sid).GetName(),
                            "voxels": int(actual.sum()),
                            "identical": True,
                        }
                    )
            assert len(checked) == len(bridge["segments"])
            slicer.util.selectModule("Segmentations")
            screenshot("slicer-returned-seg.png")
            reports = {}
            for label, path in [
                ("volume", output / "SR-001.dcm"),
                ("single", Path(bridge["single_output"]) / "SR-001.dcm"),
                ("planar", Path(manifest["output"]) / "SR-002.dcm"),
            ]:
                if label != "volume":
                    indexer.addListOfFiles(
                        slicer.dicomDatabase,
                        [str(p) for p in path.parent.glob("*.dcm")],
                    )
                before = {
                    n.GetID() for n in slicer.util.getNodesByClass("vtkMRMLTableNode")
                }
                try:
                    plugin = DICOMTID1500PluginClass()
                    loadables = plugin.examineForImport([[str(path)]])
                    assert loadables, "SR not recognized"
                    loaded = bool(plugin.load(loadables[0]))
                    reports[label] = {"loaded": loaded}
                except Exception as error:  # noqa: BLE001 - record each plugin failure and continue other cases
                    reports[label] = {
                        "loaded": False,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                tables = [
                    n
                    for n in slicer.util.getNodesByClass("vtkMRMLTableNode")
                    if n.GetID() not in before
                ]
                reports[label]["tables"] = [
                    {
                        "columns": [
                            t.GetColumnName(c) for c in range(t.GetNumberOfColumns())
                        ],
                        "units": [
                            t.GetColumnUnitLabel(t.GetColumnName(c))
                            for c in range(t.GetNumberOfColumns())
                        ],
                        "rows": [
                            [t.GetCellText(r, c) for c in range(t.GetNumberOfColumns())]
                            for r in range(t.GetNumberOfRows())
                        ],
                    }
                    for t in tables
                ]
                if tables:
                    plugin.showTable(tables[0])
                    slicer.util.selectModule("Tables")
                screenshot("slicer-sr-" + label + ".png")
            save_json(
                "slicer-return.json",
                {
                    "slicer_version": slicer.app.applicationVersion,
                    "segments": checked,
                    "reports": reports,
                },
            )
        (root / ("error-" + stage + ".json")).unlink(missing_ok=True)
        print("SLICER_ROUNDTRIP_OK", stage, root, flush=True)
except Exception:  # noqa: BLE001 - save traceback before terminating the separate Slicer process
    save_json("error-" + stage + ".json", {"traceback": traceback.format_exc()})
    traceback.print_exc()
    slicer.app.exit(1)
else:
    slicer.app.exit(0)
