"""Slicer --python-script; RESULTS_ROOT points to validate_dicom_results output."""

import json
import os
from pathlib import Path
import ctk
import pydicom
import slicer
from DICOMLib import DICOMUtils, DICOMLoadable
from DICOMSegmentationPlugin import DICOMSegmentationPluginClass

root = Path(os.environ["RESULTS_ROOT"])
manifest = json.loads((root / "manifest.json").read_text())
seg_path = Path(manifest["output"]) / "SEG-001.dcm"
try:
    with DICOMUtils.TemporaryDICOMDatabase(str(root / "slicer-database")):
        indexer = ctk.ctkDICOMIndexer()
        indexer.addListOfFiles(
            slicer.dicomDatabase, [*manifest["source_paths"], str(seg_path)]
        )
        loadable = DICOMLoadable()
        loadable.files = [str(seg_path)]
        loadable.uid = str(
            pydicom.dcmread(seg_path, stop_before_pixels=True).SOPInstanceUID
        )
        loadable.name = "VoxPlane validation segment"
        plugin = DICOMSegmentationPluginClass()
        assert plugin.load(loadable)
        nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        node = nodes[-1]
        segment_id = node.GetSegmentation().GetNthSegmentID(0)
        array = slicer.util.arrayFromSegmentInternalBinaryLabelmap(node, segment_id)
        count = int((array > 0).sum())
        assert count == manifest["voxel_count"]
        result = dict(
            slicer_version=slicer.app.applicationVersion,
            segments=node.GetSegmentation().GetNumberOfSegments(),
            voxel_count=count,
            loaded=True,
        )
        (root / "slicer-load.json").write_text(json.dumps(result, indent=2) + "\n")
        print("SLICER_SEG_LOADED", json.dumps(result), flush=True)
except Exception:
    import traceback

    traceback.print_exc()
    slicer.app.exit(1)
else:
    slicer.app.exit(0)
