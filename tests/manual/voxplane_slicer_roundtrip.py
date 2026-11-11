"""Native VoxPlane GUI stage between slicer_seg_roundtrip.py edit and verify.

python tests/manual/voxplane_slicer_roundtrip.py SOURCE_MANIFEST ROUNDTRIP_ROOT
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from i18n_support import install_default_language
from test_dicom_tags import wait_until
from test_tag_qml import click, find

from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider

manifest_path, root = map(Path, sys.argv[1:3])
manifest = json.loads(manifest_path.read_text())
external = json.loads((root / "slicer-edit.json").read_text())
paths = list(map(Path, manifest["source_paths"]))
snapshot = list(DicomFolderScanner().scan_files(paths, folder=paths[0].parent))[-1]
series = max(snapshot.series, key=lambda s: len(s.instances))
qt = QApplication.instance() or QApplication([])
install_default_language(qt)
provider = DicomImageProvider()
app = AppController(
    provider,
    settings_path=False,
    pacs_config_path=root / "pacs.json",
    pacs_import_root=root / "imports",
)
engine = QQmlApplicationEngine()
engine.addImageProvider("navigation", SvgIconProvider())
engine.addImageProvider("dicom", provider)
engine.rootContext().setContextProperty("appController", app)
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
engine.load(QUrl.fromLocalFile(str(ROOT / "src/voxplane/qml/Main.qml")))
window = engine.rootObjects()[0]


def reveal(name):
    item = find(window, name)
    flickable = find(window, "toolDetailFlickable")
    edge = item.mapToScene(QPointF(0, item.height())).y()
    bottom = flickable.mapToScene(QPointF(0, flickable.height())).y()
    if edge > bottom:
        flickable.setProperty(
            "contentY", flickable.property("contentY") + edge - bottom + 8
        )
    QTest.qWait(100)
    return item


def choose_tool(name):
    for attempt in range(3):
        QTest.qWait(300)
        click(window, find(window, "primaryTool-" + name))
        if app.workspaceController.activeTab.toolController.activePanel == name:
            return
    window.grabWindow().save(str(root / ("failed-tool-" + name + ".png")))
    raise AssertionError("Toolbar did not open " + name)


try:
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    app.workspaceController.createTab(
        series.series_instance_uid, "Slicer exchange", "mpr"
    )
    tab = app.workspaceController.activeTab
    wait_until(
        lambda: (
            bool(tab.voiController.sources) and not tab.activeViewport.render_pending
        ),
        timeout=120000,
    )
    window.resize(1400, 900)
    window.show()
    window.requestActivate()
    QTest.qWait(600)
    window.raise_()
    window.requestActivate()
    QTest.qWaitForWindowActive(window, 3000)
    # Direct QTest events still target this native window when another desktop
    # application holds focus; choose_tool verifies the actual resulting panel.
    choose_tool("import")
    QTest.qWait(100)
    with patch(
        "voxplane.ui.controller.dicom_results_controller.QFileDialog.getOpenFileName",
        return_value=(external["exported"], ""),
    ):
        click(window, reveal("importSegmentation"))
    controller = app.exportController.dicomResults
    wait_until(lambda: not controller.busy, timeout=120000)
    assert not controller.isError, controller.message
    voi = tab.voiController
    wait_until(lambda: not voi.busy, timeout=120000)
    expected = np.load(root / "slicer-edited-masks.npz")
    volume = tab.activeViewport._voi_volume
    transform = volume.geometry.patient_to_voxel @ expected["affine"]
    results = []
    assert len(voi.records) == len(external["counts"])
    for i, record in enumerate(voi.records):
        expected_indices = np.argwhere(expected[f"mask{i}"])
        native = expected_indices @ transform[:3, :3].T + transform[:3, 3]
        np.testing.assert_allclose(native, np.rint(native), atol=1e-4, rtol=0)
        native = np.rint(native).astype(int)
        actual = np.argwhere(record["mask"]) + record["mask_offset"]
        shape = volume.modality_pixels.shape
        np.testing.assert_array_equal(
            np.sort(np.ravel_multi_index(native.T, shape)),
            np.sort(np.ravel_multi_index(actual.T, shape)),
        )
        assert record["name"] == external["names"][i]
        results.append(
            {
                "name": record["name"],
                "count": len(actual),
                "metrics": voi.evaluations[record["id"]].metrics,
                "identical": True,
            }
        )
    click(window, reveal("manageImportedSegments"))
    QTest.qWait(250)
    assert window.grabWindow().save(str(root / "voxplane-imported.png"))
    choose_tool("export")
    with patch(
        "voxplane.ui.controller.dicom_results_controller.QFileDialog.getExistingDirectory",
        return_value=str(root),
    ):
        click(window, reveal("exportStructuredReport"))
    wait_until(lambda: not controller.busy, timeout=120000)
    assert not controller.isError, controller.message
    assert window.grabWindow().save(str(root / "voxplane-exported.png"))
    full_output = controller.resultPath
    voi.remove(voi.records[1]["id"])
    wait_until(lambda: not voi.busy, timeout=120000)
    with patch(
        "voxplane.ui.controller.dicom_results_controller.QFileDialog.getExistingDirectory",
        return_value=str(root),
    ):
        click(window, reveal("exportStructuredReport"))
    wait_until(lambda: not controller.busy, timeout=120000)
    assert not controller.isError, controller.message
    assert not warnings, warnings
    (root / "voxplane.json").write_text(
        json.dumps(
            {
                "output": full_output,
                "single_output": controller.resultPath,
                "segments": results,
                "qml_warnings": warnings,
            },
            indent=2,
        )
        + "\n"
    )
    print("VOXPLANE_ROUNDTRIP_OK", root, flush=True)
finally:
    window.hide()
    app.shutdown()
    delete(engine)
