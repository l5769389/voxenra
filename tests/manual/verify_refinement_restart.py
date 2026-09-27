"""Read a saved test workspace in a fresh process and verify its masks/tools.

Usage: python tests/manual/verify_refinement_restart.py WORKSPACE EXPECTED_NPZ
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider


def wait(predicate):
    deadline = time.monotonic() + 30
    while not predicate():
        qt.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError('Workspace did not finish loading')
        time.sleep(.01)


qt = QApplication([])
app = AppController(DicomImageProvider(), settings_path=False)
try:
    expected = np.load(sys.argv[2])
    manager = app.workspaceDocumentController
    assert manager.restore_from(Path(sys.argv[1]))
    wait(lambda: not manager.busy)
    assert not manager.isError, manager.message
    tab = app.workspaceController.activeTab
    c = tab.voiController
    wait(lambda: bool(c.sources) and not c.busy)
    assert len(c.records) == int(expected['count'])
    for i, record in enumerate(c.records):
        np.testing.assert_array_equal(record['mask'], expected[f'mask{i}'])
        np.testing.assert_array_equal(record['mask_offset'], expected[f'offset{i}'])
        assert record['name'] == str(expected[f'name{i}'])
        assert record['color'] == str(expected[f'color{i}'])
        assert record['visible'] == bool(expected[f'visible{i}'])
    assert c.editMode == str(expected['mode']), (c.editMode, str(expected['mode']))
    assert c.selectedId == str(expected['selected'])
    assert c.brushDiameter == float(expected['diameter'])
    assert c.brushRelative == bool(expected['relative'])
    assert c.brushPercent == float(expected['percent'])
    assert c.brushSphere == bool(expected['sphere'])
    assert c._draft is None and not tab.playing
    assert not manager.dirty
    print(json.dumps(dict(masks_equal=True, metadata_equal=True, tool_state_equal=True,
                          no_draft=True, paused=True, clean=True)))
finally:
    app.shutdown()
