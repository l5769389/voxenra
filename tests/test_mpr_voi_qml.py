from pathlib import Path
from dataclasses import replace
import time

import numpy as np
import pytest
from PySide6.QtCore import QUrl, Qt, QPointF, QMetaObject, QObject
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_measurement_qml import qt_app, _visual_children, _scene, _mouse_drag
from test_pet_fusion import paired_series
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.mpr_voi import evaluate_voi


def settle(controller):
    deadline = time.monotonic() + 5
    while controller.busy and not controller.error and time.monotonic() < deadline:
        QTest.qWait(20)
    assert not controller.error
    assert not controller.busy
    QTest.qWait(30)


@pytest.mark.parametrize("modality", ["CT", "PT"])
def test_real_mpr_draw_edit_threshold_depth_and_voi(qt_app, paired_series, tmp_path, modality):
    catalog, ct, pet = paired_series
    series = ct if modality == "CT" else pet
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(lambda failure: pytest.fail(str(failure.error)))
    workspace.renderRequested.connect(worker.handleRenderRequest)
    workspace.createTab(series.series_instance_uid, "MPR VOI", "mpr")
    tab = next(iter(workspace._tab_dict.values()))
    controller = tab.voiController
    tab.toolController.activateTool("segmentation")
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.engine().addImageProvider("dicom", provider)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1550, 1100)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties({"workspace": workspace, "tabController": tab})
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/MprVoiWorkspace.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(80)
    try:
        items = list(_visual_children(view.rootObject()))
        assert any(x.objectName() == "mprVoiPanel" and x.isVisible() for x in items)
        layers = [x for x in items if x.objectName() == "dicomPixelLayer"]
        viewport = next(v for v in tab.viewports_by_id.values() if v.viewportType == "axial")
        # Locate its visual layer by walking from Viewport's controller property.
        layer = next(x for x in layers if _owner(x) is viewport)
        g = viewport._plane_geometry
        center = np.array([(g.columns-1)/2, (g.rows-1)/2])
        # Right zoom stays available while the segmentation tool is selected,
        # including over the crosshair. It must not start a VOI or rotate MPR.
        before_frame, before_zoom = tab._target_mpr_state.frame, viewport.zoom
        right_start = _scene(layer, *center)
        right_end = right_start + QPointF(20, -35).toPoint()
        QTest.mousePress(view, Qt.RightButton, Qt.NoModifier, right_start)
        QTest.mouseMove(view, (right_start+right_end)/2, 20)
        QTest.mouseMove(view, right_end, 20)
        QTest.mouseRelease(view, Qt.RightButton, Qt.NoModifier, right_end)
        QTest.qWait(30)
        assert viewport.zoom != before_zoom
        assert tab._target_mpr_state.frame == before_frame
        assert not controller.records and controller._draft is None
        assert not viewport._voi_drag_active
        viewport.apply_zoom(before_zoom)
        QTest.qWait(30)
        # Starts on crosshair lines: VOI drawing must take priority over rotation.
        start, end = center - 1.2, center + 1.2
        _mouse_drag(view, _scene(layer, *start), _scene(layer, *end))
        settle(controller)
        assert len(controller.records) == 1
        key = controller.selectedId
        r = controller.records[0]
        assert r["depthAuto"]
        assert r["region"].size[2] == pytest.approx(np.sqrt(np.prod(r["region"].size[:2])))
        assert controller.evaluations[key].metrics["count"] > 0
        assert all(v.voiOverlays for v in tab.viewports_by_id.values() if hasattr(v, "voiOverlays"))

        # Narrow panels keep mode buttons and numeric fields on separate rows.
        for width in (260, 300, 390):
            view.rootObject().setProperty("rightPanelWidth", width)
            QTest.qWait(30)
            visual = {x.objectName(): x for x in _visual_children(view.rootObject()) if x.objectName()}
            label = visual["voiThresholdLabel"]
            absolute = visual["voiThresholdAbsolute"]
            percent = visual["voiThresholdPercent"]
            assert label.x() + label.width() <= absolute.x()
            assert absolute.x() + absolute.width() <= percent.x()
            field = visual["voiThreshold"]
            mode_row = visual["voiThresholdModeRow"]
            assert mode_row.y() + mode_row.height() <= field.y()
            assert field.width() > 180

        # Exercise actual number entry and slider-driven scheduling.
        depth = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiDepth")
        depth.forceActiveFocus()
        QMetaObject.invokeMethod(depth, "selectAll")
        QTest.keyClick(view, "6")
        QTest.keyClick(view, Qt.Key_Return)
        settle(controller)
        assert controller.records[0]["region"].size[2] == 6
        assert not r["depthAuto"]
        auto = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiAutoDepth")
        _click(view, auto)
        settle(controller)
        assert r["depthAuto"]
        threshold = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiThreshold")
        threshold.forceActiveFocus()
        QMetaObject.invokeMethod(threshold, "selectAll")
        for c in ("5" if modality == "PT" else "2500"):
            QTest.keyClick(view, c)
        QTest.keyClick(view, Qt.Key_Return)
        settle(controller)
        oracle = evaluate_voi(viewport._voi_volume, r["region"], threshold=r["threshold"])
        assert controller.evaluations[key].metrics == oracle.metrics
        controller.setThreshold(1e10)
        settle(controller)
        assert controller.evaluations[key].metrics["count"] == 0
        controller.setPercent(True)
        controller.setThreshold(50)
        settle(controller)
        assert controller.evaluations[key].metrics["count"] > 0

        if modality == "PT":
            controller.setUnit("kbqml")
            settle(controller)
            assert controller.selected["unit"] == "kBq/ml"
            # Display changes cannot silently relabel saved quantitative thresholds.
            viewport.setPetUnit("source")
            settle(controller)
            assert controller.selected["unit"] == "kBq/ml"

        before = r["region"]
        # PET's compact locator owns a hit at its center. Grab the region body
        # away from that marker to exercise moving the VOI itself.
        move_start = center + [.6, .4] if modality == "PT" else center
        _mouse_drag(view, _scene(layer, *move_start), _scene(layer, *(move_start + [.2, .1])))
        settle(controller)
        assert not np.allclose(before.center, r["region"].center)
        assert len(controller.records) == 1
        controller.toggleVisible(key)
        assert viewport.voiOverlays == []
        controller.toggleVisible(key)
        controller.setEnabled(False)
        assert viewport.voiOverlays == []
        controller.setEnabled(True)
        tab.toolController.activateTool("voi")
        voi_start = center + [.5, .6] if modality == "PT" else center
        _mouse_drag(view, _scene(layer, *voi_start), _scene(layer, *(voi_start + [1, 0])))
        settle(controller)
        assert len(controller.records) == 2
        assert controller.records[-1]["kind"] == "voi"
        circle = controller.records[-1]
        assert circle["region"].shape == "ellipsoid"
        assert circle["region"].size[0] == circle["region"].size[1] == circle["region"].size[2]
        assert controller.evaluations[controller.selectedId].threshold is None
        interaction = next(x for x in _visual_children(view.rootObject())
                           if x.objectName() == "viewportInteractionLayer" and _owner(x) is viewport)
        QTest.mouseMove(view, _scene(layer, *voi_start), 20)
        QTest.qWait(30)
        assert interaction.property("hoverCursorKind") == "pan"
        QTest.mouseMove(view, _scene(layer, *(voi_start + [1, 0])), 20)
        QTest.qWait(30)
        assert interaction.property("hoverCursorKind") == "resize"
        # A captured resize remains a resize throughout the drag.
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, _scene(layer, *(voi_start + [1, 0])))
        QTest.mouseMove(view, _scene(layer, *(voi_start + [1.1, .1])), 20)
        QTest.qWait(30)
        assert interaction.property("effectiveCursorKind") == "resize"
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, _scene(layer, *(voi_start + [1.1, .1])))
        settle(controller)
        controller.setEnabled(False)
        QTest.mouseMove(view, _scene(layer, *voi_start), 20)
        QTest.qWait(30)
        assert interaction.property("hoverCursorKind") == "default"
        controller.setEnabled(True)
        # Rename in the list, without a second description field in the card.
        name = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiSelect-" + circle["id"])
        QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, name.mapToScene(QPointF(name.width()/2, name.height()/2)).toPoint())
        QTest.qWait(30)
        name_field = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiName-" + circle["id"])
        assert name_field.isVisible()
        for char in "Lesion A":
            QTest.keyClick(view, char)
        QTest.keyClick(view, Qt.Key_Return)
        assert circle["name"] == "Lesion A"

        # Contextual help routes to a workspace chapter without changing ROIs.
        records_before = [r.copy() for r in controller.records]
        for tool in ("voi", "segmentation"):
            tab.toolController.activateTool(tool)
            QTest.qWait(40)
            help_button = next(x for x in _visual_children(view.rootObject()) if x.objectName() == ("segmentationManualButton" if tool == "segmentation" else "voiManualButton"))
            _click(view, help_button)
            assert view.rootObject().property("lastManualChapter") == tool
            assert controller.records == records_before
        tab.toolController.activateTool("voi")
        QTest.qWait(40)

        # Destructive actions occupy the fixed footer, outside the scroller.
        clear_kind = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiClearKind")
        clear_all = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "voiClearAll")
        reset = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "activeToolReset")
        assert clear_kind.isVisible() and clear_all.isVisible() and not reset.isVisible()
        assert clear_kind.property("text") == "清除 VOI"
        footer_y = clear_kind.mapToScene(QPointF(0, 0)).y()
        scroller = next(x for x in _visual_children(view.rootObject()) if x.objectName() == "toolDetailFlickable")
        scroller.setProperty("contentY", 40)
        assert clear_kind.mapToScene(QPointF(0, 0)).y() == footer_y
        scroller.setProperty("contentY", 0)
        assert not warnings, warnings
        assert view.grabWindow().save(str(tmp_path / (modality + "-mpr-voi.png")))
        _click(view, clear_kind)
        assert len(controller.records) == 1
        assert controller.records[0]["kind"] == "segmentation"
        assert not clear_kind.isEnabled() and clear_all.isEnabled()
        _click(view, clear_all)
        assert controller.items == []
        assert not clear_all.isEnabled()
        tab.toolController.activateTool("window")
        QTest.qWait(30)
        assert reset.isVisible() and not clear_all.isVisible()
    finally:
        view.hide()
        delete(view)
        workspace.shutdown()


def _owner(item):
    parent = item
    while parent:
        if parent.property("viewportController") is not None:
            return parent.property("viewportController")
        parent = parent.parentItem()
    return None


def _click(view, item):
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                    item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint())
    QTest.qWait(40)
