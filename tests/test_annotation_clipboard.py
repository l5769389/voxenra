"""Real viewport shortcuts, safe clipboard payloads and target-frame metrics."""

from dataclasses import replace
import json
import math

import pytest
from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtTest import QTest

from qt_dicom_viewer.model import PixelSpacing
from qt_dicom_viewer.ui.annotation_clipboard import MIME_TYPE, read_annotation
from test_measurement_qml import (
    qt_app as qt_app,
    viewport as viewport,
    _scene,
    _click_points,
)
from test_viewport_transform import _controller, _render_result
from test_pacs_qml import scene as scene
from test_series_sidebar import sidebar_scene


def draw(view, controller, pixels, kind):
    controller._tool_controller.selectInteraction(
        ("annotate:" if kind in ("arrow", "text") else "measure:") + kind
    )
    if kind == "text":
        controller.textAnnotationController.setAnnotationText("ROI A")
        controller.textAnnotationController.setAnnotationColor("#12abcd")
        controller.textAnnotationController.setAnnotationFontSize(20)
    if kind == "angle":
        for point in ((35, 40), (70, 105), (140, 85)):
            QTest.mouseClick(view, Qt.LeftButton, pos=_scene(pixels, *point))
    else:
        _click_points(view, _scene(pixels, 35, 40), _scene(pixels, 140, 115))
    QTest.qWait(30)


def items(controller, kind):
    return (
        controller.textAnnotationController.annotationItems
        if kind == "text"
        else controller.measurementController.measurementItems
    )


@pytest.mark.parametrize(
    "kind", ["length", "angle", "rect", "ellipse", "arrow", "text"]
)
def test_copy_paste_selected_geometry_with_real_keyboard(viewport, kind):
    view, controller, pixels, warnings = viewport
    draw(view, controller, pixels, kind)
    # Completed point geometry is immediately available to copy.
    QTest.keySequence(view, QKeySequence(QKeySequence.Copy))
    original = items(controller, kind)[0]
    payload = read_annotation()
    assert payload and payload["kind"] == kind
    assert set(payload) <= {"kind", "points", "text", "color", "fontSize", "version"}
    for count in (1, 2):
        QTest.keySequence(view, QKeySequence(QKeySequence.Paste))
        QTest.qWait(30)
        copies = items(controller, kind)
        assert len(copies) == count + 1
        copied = copies[-1]
        if kind == "text":
            assert copied["selected"] and not copied["draft"]
            assert copied["annotationId"] != original["annotationId"]
            assert copied["tailColumn"] == pytest.approx(
                original["tailColumn"] + 10 * count
            )
            assert (copied["text"], copied["color"], copied["fontSize"]) == (
                "ROI A",
                "#12abcd",
                20,
            )
        else:
            assert copied["measurementId"] != original["measurementId"]
            assert (
                controller.measurementController.selectedMeasurementState == "completed"
            )
            assert not controller.measurementController.has_active_transaction
            for point, source in zip(copied["points"], original["points"]):
                assert point["column"] == pytest.approx(source["column"] + 10 * count)
                assert point["row"] == pytest.approx(source["row"] + 10 * count)
            if kind in ("rect", "ellipse"):
                assert copied["metrics"]["mean"] == pytest.approx(
                    original["metrics"]["mean"] + 20 * count
                )
            else:
                assert copied["label"] == original["label"]
    QTest.keyClick(view, Qt.Key_Delete)
    assert len(items(controller, kind)) == 2
    original_after = items(controller, kind)[0]
    assert (
        original_after["text"] == original["text"]
        if kind == "text"
        else original_after == original
    )
    assert not warnings, warnings


def test_paste_to_other_view_uses_target_slice_spacing_and_can_survive_source_close(
    viewport,
):
    view, source, pixels, warnings = viewport
    draw(view, source, pixels, "length")
    assert source.copySelectedAnnotation()
    payload = read_annotation()
    target = _controller()
    result = _render_result(target)
    frame = replace(
        result.frame_meta,
        slice_index=4,
        slice_count=6,
        geometry=replace(
            result.frame_meta.geometry, pixel_spacing=PixelSpacing(row=2, column=3)
        ),
    )
    target._state = replace(target._state, slice_index=4, slice_count=6)
    target.handleRenderResult(replace(result, frame_meta=frame))
    source.measurementController.clear_all()
    try:
        assert target.pasteAnnotation()
        copied = target.measurementController.committed_measurements[0]
        a, b = payload["points"]
        assert copied.length_mm == pytest.approx(
            math.hypot((b[0] - a[0]) * 3, (b[1] - a[1]) * 2)
        )
        assert (
            copied.slice_index == 4
            and copied.series_uid == target.viewport_config.series_uid
        )
        target._state = replace(target._state, slice_index=5)
        assert (
            not target.pasteAnnotation()
        )  # No old pixels written to an awaiting slice.
    finally:
        target.shutdown()
    assert not warnings, warnings


def test_clipboard_ignores_incomplete_points_and_preserves_plain_text(viewport):
    view, controller, pixels, warnings = viewport
    QGuiApplication.clipboard().setText("ordinary text")
    assert not controller.copySelectedAnnotation() and not controller.pasteAnnotation()
    assert QGuiApplication.clipboard().text() == "ordinary text"
    controller._tool_controller.selectInteraction("measure:length")
    start, end = _scene(pixels, 35, 40), _scene(pixels, 140, 115)
    QTest.mousePress(view, Qt.LeftButton, pos=start)
    QTest.mouseMove(view, end, 30)
    assert not controller.copySelectedAnnotation() and not controller.pasteAnnotation()
    QTest.mouseRelease(view, Qt.LeftButton, pos=end)
    assert not controller.copySelectedAnnotation()
    QTest.mousePress(view, Qt.LeftButton, pos=end)
    try:
        assert controller.copySelectedAnnotation()
    finally:
        QTest.mouseRelease(view, Qt.LeftButton, pos=end)
    assert not warnings, warnings


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": 2, "kind": "length", "points": [[1, 2], [3, 4]]},
        {"version": 1, "kind": "length", "points": [[True, 2], [3, 4]]},
        {"version": 1, "kind": "length", "points": [[10**500, 2], [3, 4]]},
        {"version": 1, "kind": "angle", "points": [[1, 2], [3, 4]]},
        {
            "version": 1,
            "kind": "text",
            "points": [[1, 2], [3, 4]],
            "text": "x",
            "color": "invalid",
            "fontSize": 16,
        },
        {
            "version": 1,
            "kind": "text",
            "points": [[1, 2], [3, 4]],
            "text": "x" * 201,
            "color": "red",
            "fontSize": 16,
        },
    ],
)
def test_untrusted_clipboard_cannot_create_objects(viewport, payload):
    _, controller, _, _ = viewport
    mime = QMimeData()
    mime.setData(MIME_TYPE, json.dumps(payload).encode())
    QGuiApplication.clipboard().setMimeData(mime)
    assert not controller.pasteAnnotation()
    assert not controller.measurementController.measurementItems
    assert not controller.textAnnotationController.annotationItems


def test_focused_text_editor_keeps_standard_text_copy_paste(scene, tmp_path):
    from test_series_sidebar import phantom_series
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from test_dicom_tags import wait_until
    from test_tag_qml import find
    from PySide6.QtCore import QMetaObject

    window, app, warnings = scene
    series = phantom_series(tmp_path, 1, "DEMO-A", "1.2.3.991", "20260906")
    app.panelController.acceptPacsImport(
        DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [series])
    )
    wait_until(
        lambda: (
            app.workspaceController.activeViewport is not None
            and bool(app.workspaceController.activeViewport.imageSource)
        )
    )
    controller = app.workspaceController.activeViewport
    controller._tool_controller.activateTool("annotate")
    controller.setAnnotationMode(True)
    controller.textAnnotationController.setAnnotationText("Editable label")
    controller.textAnnotationController.addAnnotation(20, 20, 50, 50)
    editor = find(window, "annotationTextEditor")
    editor.forceActiveFocus()
    QMetaObject.invokeMethod(editor, "selectAll")
    QTest.keySequence(window, QKeySequence(QKeySequence.Copy))
    assert QGuiApplication.clipboard().text() == "Editable label"
    assert read_annotation() is None
    QGuiApplication.clipboard().setText("New label")
    QTest.keySequence(window, QKeySequence(QKeySequence.Paste))
    QTest.qWait(30)
    assert editor.property("text") == "New label"
    assert len(controller.textAnnotationController.annotationItems) == 1
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['length', 'rect', 'text', 'arrow'])
def test_copy_paste_from_panel_focus_with_history_and_modal_isolation(sidebar_scene, kind):
    from test_input_settings_qml import reading_scene, visible_viewport
    from test_tag_qml import find
    window, app, tab = reading_scene(sidebar_scene)
    controller = tab.activeViewport
    pixels = find(window, 'dicomPixelLayer')
    # The full-app fixture uses a small image. Fit to points inside that frame.
    controller._tool_controller.selectInteraction(('annotate:' if kind in ('text', 'arrow') else 'measure:')+kind)
    if kind == 'text':
        controller.textAnnotationController.setAnnotationText('copied note')
    _click_points(window, _scene(pixels, 12, 12), _scene(pixels, 32, 32))
    assert len(items(controller, kind)) == 1
    history = tab.historyController
    history.reset()
    # Focus a sidebar control after selecting the shape; viewport Keys won't receive it.
    button = find(window, 'primaryTool-measure')
    button.forceActiveFocus()
    QGuiApplication.clipboard().setText('ordinary text')
    QTest.keySequence(window, QKeySequence(QKeySequence.Copy))
    assert read_annotation() and read_annotation()['kind'] == kind
    QTest.keySequence(window, QKeySequence(QKeySequence.Paste)); QTest.qWait(30)
    assert len(items(controller, kind)) == 2
    QTest.keySequence(window, QKeySequence(QKeySequence.Undo)); QTest.qWait(30)
    assert len(items(controller, kind)) == 1
    QTest.keySequence(window, QKeySequence(QKeySequence.Redo)); QTest.qWait(30)
    assert len(items(controller, kind)) == 2
    search = find(window, 'sidebarPatientSearch'); search.forceActiveFocus()
    QTest.keySequence(window, QKeySequence(QKeySequence.Paste))
    assert len(items(controller, kind)) == 2
    visible_viewport(window).forceActiveFocus()
    app.feedbackController.show(); QTest.qWait(40)
    assert window.property('shortcutPopupOpen')
    QTest.keySequence(window, QKeySequence(QKeySequence.Paste))
    assert len(items(controller, kind)) == 2
    QTest.keyClick(window, Qt.Key_Escape); QTest.qWait(30)
    visible_viewport(window).forceActiveFocus()
    QTest.keySequence(window, QKeySequence(QKeySequence.Paste)); QTest.qWait(30)
    assert len(items(controller, kind)) == 3  # One paste, not two handlers.
    assert not sidebar_scene[3], sidebar_scene[3]
    # The offscreen platform owns its QMimeData until static destruction, after
    # Python has exited. Release the Python wrapper while the interpreter lives.
    QGuiApplication.clipboard().clear()
