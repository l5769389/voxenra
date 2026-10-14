"""Text annotations stay attached to the displayed slice and sampling source."""
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl, Qt
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.core.workspace_state import dumps, loads
from qt_dicom_viewer.model import StackRenderResult, TwoDViewType
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.workspace_snapshot import apply_edits, editable_state
from test_four_d_tools import temporal
from test_measurement_qml import qt_app, viewport, _scene, _mouse_drag, _visual_children


def visible_annotations(window):
    QTest.qWait(30)
    return [item for item in _visual_children(window.rootObject())
            if item.objectName().startswith("textAnnotation-") and item.isVisible()]


@pytest.fixture
def temporal_viewport(temporal):
    tab, _, (_, workspace) = temporal
    controller = tab.activeViewport
    window = QQuickView()
    window.engine().addImageProvider("navigation", SvgIconProvider())
    window.engine().addImageProvider("dicom", workspace._image_provider)
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.resize(900, 700)
    window.setInitialProperties({"viewportController": controller, "hasTabs": True})
    source = Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/sections/center/viewportArea/Viewport.qml"
    window.setSource(QUrl.fromLocalFile(str(source)))
    assert window.status() == QQuickView.Ready, window.errors()
    window.show()
    QTest.qWait(80)
    try:
        yield window, controller, tab
    finally:
        window.hide()
        delete(window)


def test_four_d_annotations_roundtrip_and_history_keep_phase_scope(temporal_viewport, tmp_path):
    window, controller, tab = temporal_viewport
    layer = window.rootObject().findChild(QQuickItem, "dicomPixelLayer")
    text, history = controller.textAnnotationController, tab.historyController
    tab.toolController.selectInteraction("annotate:text")
    text.setAnnotationText("Phase 0 only")
    _mouse_drag(window, _scene(layer, .5, .5), _scene(layer, 2., 1.5))
    first = text.selectedAnnotationId
    history.capture()
    assert len(visible_annotations(window)) == 1
    assert window.grabWindow().save(str(tmp_path / "phase-0-annotation.png"))
    original_geometry = controller._frame_meta.geometry
    assert controller._frame_meta.instance_meta.sop_instance_uid is None

    tab.setPhaseIndex(1)
    assert controller._frame_meta.geometry == original_geometry
    assert (controller._modality_pixel == 20).all()
    assert text.annotationItems == []
    assert not visible_annotations(window)
    assert window.grabWindow().save(str(tmp_path / "phase-1-no-annotation.png"))

    text.setAnnotationText("Phase 1 only")
    _mouse_drag(window, _scene(layer, .5, .5), _scene(layer, 2., 1.5))
    second = text.selectedAnnotationId
    history.capture()
    saved = loads(dumps(editable_state(tab)))
    assert [a["annotationId"] for a in text.annotationItems] == [second]
    history.undo()
    assert not text.annotationItems
    history.redo()
    assert [a["annotationId"] for a in text.annotationItems] == [second]
    text.clearAll()
    apply_edits(tab, saved)
    assert [a["annotationId"] for a in text.annotationItems] == [second]
    assert len(visible_annotations(window)) == 1
    tab.setPhaseIndex(0)
    assert [a["annotationId"] for a in text.annotationItems] == [first]
    assert len(visible_annotations(window)) == 1


@pytest.mark.parametrize("change", ["mode", "thickness"])
def test_projection_annotations_keep_sampling_identity(temporal, change):
    tab, _, _ = temporal
    controller, tools = tab.activeViewport, tab.toolController
    tools.setMprProjectionEnabled(True)
    tools.setMprProjectionMode("mip")
    plane = controller.viewport_config.viewport_type.value
    tools.setMprThickness(plane, 5.0)
    text = controller.textAnnotationController
    text.addAnnotation(.5, .5, 2., 1.5)
    original = text.selectedAnnotationId
    original_geometry = controller._frame_meta.geometry
    if change == "mode":
        tools.setMprProjectionMode("minip")
    else:
        tools.setMprThickness(plane, 10.0)
    assert controller._frame_meta.geometry == original_geometry
    assert text.annotationItems == []
    assert not text.hasSelection
    if change == "mode":
        tools.setMprProjectionMode("mip")
    else:
        tools.setMprThickness(plane, 5.0)
    assert [a["annotationId"] for a in text.annotationItems] == [original]


def two_slice_frames(controller):
    old = replace(controller._frame_meta, slice_count=2)
    controller._frame_meta = old
    controller._state = replace(controller._state, slice_count=2)
    new = replace(old, slice_index=1,
                  instance_meta=replace(old.instance_meta, sop_instance_uid="sop-2"),
                  geometry=replace(old.geometry, image_position_patient=(0., 0., 1.)))
    return old, new


def deliver(controller, frame):
    controller.handleRenderResult(StackRenderResult(
        response_id=controller._latest_request_id,
        viewport_id=controller.viewportId,
        series_uid=controller.viewport_config.series_uid,
        view_type=TwoDViewType.STACK,
        image=controller._modality_pixel.astype("uint8"),
        modality_pixel=controller._modality_pixel,
        frame_meta=frame,
    ))
    QTest.qWait(30)


@pytest.mark.parametrize("start_before_request", [False, True])
def test_pending_slice_rejects_new_gestures_and_cancels_existing_draft(viewport, tmp_path, start_before_request):
    window, controller, layer, warnings = viewport
    old, new = two_slice_frames(controller)
    text = controller.textAnnotationController
    controller._tool_controller.selectInteraction("annotate:text")
    text.setAnnotationText("Original slice")
    _mouse_drag(window, _scene(layer, 30, 35), _scene(layer, 95, 95))
    original_id = text.selectedAnnotationId
    original = text._annotations[original_id]
    assert len(visible_annotations(window)) == 1
    start, end = _scene(layer, 150, 160), _scene(layer, 200, 220)
    if start_before_request:
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(window, (start + end) / 2, 20)
        assert text._draft_id
    controller.setSliceIndex(1)
    assert controller.render_pending and controller._frame_meta.slice_index == 0
    if start_before_request:
        QTest.mouseMove(window, end, 20)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    else:
        _mouse_drag(window, start, end)
    assert not text._draft_id and not controller._annotation_drag_active
    assert len(text._annotations) == 1
    assert not text.annotationItems
    assert not visible_annotations(window)
    # Clicking the old arrow cannot select/edit it as if it belonged to the new slice.
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, _scene(layer, 60, 65))
    text.setAnnotationText("Next slice")
    assert not text.hasSelection
    assert text._annotations[original_id] == original
    assert window.grabWindow().save(str(tmp_path / "pending-slice.png"))
    deliver(controller, new)
    _mouse_drag(window, start, end)
    second_id = text.selectedAnnotationId
    assert [a["annotationId"] for a in text.annotationItems] == [second_id]
    assert text.annotationItems[0]["sliceIndex"] == 1
    assert len(visible_annotations(window)) == 1
    controller.setSliceIndex(0)
    deliver(controller, old)
    assert [a["annotationId"] for a in text.annotationItems] == [original_id]
    assert len(visible_annotations(window)) == 1
    assert not warnings, warnings


def test_saved_plain_two_d_annotations_keep_existing_frame_identity(viewport):
    _, controller, _, _ = viewport
    text = controller.textAnnotationController
    text.addAnnotation(30, 35, 95, 95)
    record = loads(dumps(text._annotations))
    # Ordinary 2D workspaces already store the six-field identity; extending
    # phase/projection scope must leave these saved records readable.
    original_id = text.selectedAnnotationId
    assert len(record[original_id].frame_key) == 6
    text.clearAll()
    text._annotations = record
    text.set_frame(controller.viewport_config.series_uid, controller._frame_meta)
    assert [a["annotationId"] for a in text.annotationItems] == [original_id]
