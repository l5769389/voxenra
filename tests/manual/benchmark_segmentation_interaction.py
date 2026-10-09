"""Deterministic interaction benchmark; run before/after with the same source fixtures.

QT_QPA_PLATFORM=offscreen .venv/bin/python tests/manual/benchmark_segmentation_interaction.py OUTPUT.json
Synthetic arrays only; this measures CPU work, not native GPU frame rate.
"""
from dataclasses import replace
import json
from pathlib import Path
import platform
from statistics import median
import sys
import time
import tracemalloc
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_mpr_reslicer import _volume
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.core.mpr_voi import VoiEvaluation, plane_mask
from qt_dicom_viewer.model import MprFrame, MprPlane, TabType
from qt_dicom_viewer.ui.controller.edit_history_controller import EditHistoryController
from qt_dicom_viewer.ui.controller.tab.mpr_voi_controller import MprVoiController
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.workspace_snapshot import edit_signature


def timing(action, repeats=9):
    action()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000)
    return dict(median_ms=median(samples), max_ms=max(samples))


def main():
    app = QApplication.instance() or QApplication([])
    volume = _volume(np.zeros((128, 256, 256), np.float32))
    plane = MprReslicer().reslice(volume, MprPlane.AXIAL,
                                 MprFrame(volume.geometry.center_patient)).geometry
    mask = np.random.default_rng(90210).random(volume.modality_pixels.shape, dtype=np.float32) > .8
    evaluation = VoiEvaluation(mask, np.zeros(3, int), volume.geometry, {}, None, (0, 0))
    tab = QObject()
    tab.viewports_by_id = {}
    tools = ToolController(tab_type=TabType.MPR)
    controller = MprVoiController(tools, tab)
    tab._voi_controller = controller
    controller.records = [dict(id="segment", phase=None, kind="segmentation",
                               mask=mask, visible=True, color="#44bbdd")]
    controller.evaluations = {"segment": evaluation}
    history = EditHistoryController(tab)
    view = SimpleNamespace(_plane_geometry=plane, viewportId="axial")
    output = dict(python=platform.python_version(), platform=platform.platform(),
                  mask_shape=list(mask.shape), mask_voxels=int(mask.size), repeats=9)
    try:
        state = dict(views={}, voi=controller.records)
        output["history_signature"] = timing(lambda: edit_signature(state))
        output["history_unchanged"] = timing(history.capture)
        output["display_setting"] = timing(lambda: (
            controller.setFillOpacity((controller.fillOpacity + 1) % 100), app.processEvents()))
        # QML may read a preview repeatedly between two pointer events.
        controller._draft = dict(mode="brush", id="segment", color="#44bbdd",
                                 mask=mask, offset=evaluation.offset, volume=volume,
                                 record=controller.records[0])
        output["preview_repeated"] = timing(lambda: controller.masks(view))
        controller._draft = None
        for size in (512, 1024, 2048):
            g = replace(plane, rows=size, columns=size)
            output[f"plane_{size}"] = timing(lambda: plane_mask(evaluation, g), repeats=5)
            tracemalloc.start()
            plane_mask(evaluation, g)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            output[f"plane_{size}"]["peak_temporary_mib"] = peak / 1024**2
    finally:
        history.dispose()
        controller.dispose()
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
