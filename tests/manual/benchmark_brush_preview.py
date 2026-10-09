"""CPU-only brush update + 3-plane preview benchmark; no GPU/frame-rate claim.

QT_QPA_PLATFORM=offscreen .venv/bin/python tests/manual/benchmark_brush_preview.py OUTPUT.json
"""
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QApplication
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_mpr_reslicer import _volume
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.core.segmentation_masks import mask_record
from qt_dicom_viewer.model import MprFrame, MprPlane, TabType
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.tab.mpr_voi_controller import MprVoiController


def run(flush_each):
    volume = _volume(np.zeros((128, 512, 512), np.float32))
    views = [SimpleNamespace(_plane_geometry=MprReslicer().reslice(volume, p,
                MprFrame(volume.geometry.center_patient)).geometry,
                _voi_volume=volume, viewportId=p.value,
                viewport_config=SimpleNamespace(series_meta=SimpleNamespace(modality='CT')))
             for p in (MprPlane.AXIAL, MprPlane.SAGITTAL, MprPlane.CORONAL)]
    mask = np.zeros(volume.modality_pixels.shape, bool)
    mask[20:100, 60:450, 60:450] = True
    tools = ToolController(tab_type=TabType.MPR)
    c = MprVoiController(tools)
    c.set_source(volume); tools.activateTool('segmentation')
    record, result = mask_record(volume, mask, (0, 0, 0), name='Synthetic')
    c.records.append(record); c.evaluations[record['id']] = result; c._selected = record['id']
    c.setEditMode('erase')
    g = views[0]._plane_geometry
    x, y = (g.columns-1)/2, (g.rows-1)/2
    count = 0
    def render():
        nonlocal count
        count += 1
        for view in views:
            c.masks(view)
    c.masksChanged.connect(render)
    c.begin(views[0], x, y, .1)
    c._preview_timer.stop(); render(); count = 0
    times = []
    try:
        for i in range(40):
            start = perf_counter()
            c.update(views[0], x + i/4, y)
            if flush_each and c._preview_timer.isActive():
                c._preview_timer.stop(); c.masksChanged.emit()
            times.append((perf_counter()-start)*1000)
        # Include final rendering cost in total; never hide deferred work.
        start = perf_counter()
        if c._preview_timer.isActive():
            c._preview_timer.stop(); c.masksChanged.emit()
        final_ms = (perf_counter()-start)*1000
        return dict(mask_shape=list(volume.modality_pixels.shape), updates=40,
            median_update_ms=median(times), p95_update_ms=float(np.percentile(times,95)),
            total_cpu_ms=sum(times)+final_ms, final_render_ms=final_ms, preview_refreshes=count)
    finally:
        c.dispose()


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    result = dict(flush_every_changed_sample=run(True), coalesced_burst=run(False))
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
