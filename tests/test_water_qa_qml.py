from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import ToolType
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_measurement_qml import qt_app, _visual_children, _mouse_drag, _scene
from test_service_panel_qml import _find, _click
from test_water_qa import water_image
from test_water_qa_controller import qa_view, water_render, wait_qa


@pytest.fixture
def qa_workspace(qt_app, qa_view, request):
    controller, _ = qa_view
    pixels = water_image(shape=(400, 512), spacing=(.7, .5), center=(265, 196))
    frame = water_render(controller, spacing=(.7, .5), pixels=pixels)
    controller.handleRenderResult(frame)
    controller._tool_controller.resetRequested.connect(lambda tool: controller.reset_tool_state(ToolType(tool)))
    window = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    window.engine().addImageProvider("navigation", SvgIconProvider())
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.resize(*getattr(request, "param", (1200, 820)))
    provider = DicomImageProvider()
    provider.set_array(controller.viewport_config.viewport_id, frame.image)
    window.engine().addImageProvider("dicom", provider)
    warnings = []
    window.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window.setInitialProperties(dict(viewportController=controller, toolController=controller._tool_controller))
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).parent/"qml/MtfWorkspace.qml")))
    assert window.status() == QQuickView.Ready, [e.toString() for e in window.errors()]
    window.show()
    QTest.qWait(70)
    try:
        yield window, controller, warnings
    finally:
        window.hide()
        delete(window)


@pytest.mark.parametrize("qa_workspace", [(1200, 820), (760, 560)], indirect=True)
def test_actual_qa_button_draws_five_rois_and_measures_current_slice(qa_workspace, qt_app, tmp_path):
    window, view, warnings = qa_workspace
    _click(window, _find(window, "primaryTool-service"))
    _click(window, _find(window, "serviceEntry-qa"))
    wait_qa(qt_app, view.qaController)
    QTest.qWait(40)
    rois = [item for item in _visual_children(window.rootObject())
            if item.objectName().startswith("waterQaVoi-")]
    assert len(rois) == 5
    assert all(roi.isVisible() for roi in rois)
    result = view.qaController.currentResult
    for key in ("water_ct_hu", "noise_hu", "uniformity_hu", "consistency_range_hu",
                "horizontal_difference_hu", "vertical_difference_hu"):
        item = _find(window, "waterQaMetric-"+key)
        assert item.property("text") == f"{result[key]:.2f} HU"
    assert len([item for item in _visual_children(window.rootObject())
                if item.objectName().startswith("waterQaRow-") and item.isVisible()]) == 5
    assert "中心" in _find(window, "waterQaVoiLabel-center").property("text")
    texts = [item.property("text") for item in _visual_children(window.rootObject()) if item.isVisible()]
    assert not any(text in ("通过", "不通过", "合格", "不合格") for text in texts)
    image = window.grabWindow()
    assert image.save(str(tmp_path/f"water-qa-{window.width()}x{window.height()}.png"))
    if window.width() < 900:
        flick = _find(window, "toolDetailFlickable")
        assert flick.property("contentHeight") > flick.height()
        flick.setProperty("contentY", flick.property("contentHeight")-flick.height())
        QTest.qWait(20)
        last = _find(window, "waterQaRow-bottom")
        local = last.mapToItem(flick, QPointF()).y()
        assert 0 <= local and local+last.height() <= flick.height()
    assert not warnings, warnings


@pytest.mark.parametrize("transformed", [False, True])
def test_all_five_rois_drag_in_image_coordinates_and_cancel_with_escape(qa_workspace, qt_app, transformed):
    window, view, warnings = qa_workspace
    qa = view.qaController
    view._tool_controller.selectService("service:qa")
    wait_qa(qt_app, qa)
    if transformed:
        view.apply_pan(15, -12)
        view.apply_zoom(1.2)
        view.applyTransformAction("rotate:cw90")
        view.applyTransformAction("rotate:mirror-h")
        view.applyTransformAction("rotate:mirror-v")
    QTest.qWait(30)
    pixels = _find(window, "dicomPixelLayer")
    for index in range(5):
        before = qa.currentResult["rois"]
        roi = before[index]
        start = _scene(pixels, roi["column"]+2, roi["row"]+1)
        end = _scene(pixels, roi["column"]+10, roi["row"]+7)
        QTest.mouseMove(window, start, 20)
        assert _find(window, "viewportInteractionLayer").property("hoverCursorKind") == "pan"
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(window, (start+end)/2, 20)
        assert qa.dragging
        assert _find(window, "waterQaMetric-uniformity_hu").property("text") == "—"
        assert "拖动中" in _find(window, "waterQaVoiLabel-"+roi["key"]).property("text")
        QTest.mouseMove(window, end, 20)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
        QTest.qWait(20)
        after = qa.currentResult["rois"]
        assert not qa.dragging and not qa.error
        assert after[index]["column"] == pytest.approx(roi["column"]+8, abs=1)
        assert after[index]["row"] == pytest.approx(roi["row"]+6, abs=1)
        for other in range(5):
            if other != index:
                assert after[other]["column"] == before[other]["column"]
                assert after[other]["row"] == before[other]["row"]
            item = _find(window, "waterQaVoi-"+after[other]["key"])
            expected = pixels.mapToItem(item, QPointF(after[other]["column"]+.5, after[other]["row"]+.5))
            actual = item.property("center")
            assert actual.x() == pytest.approx(expected.x(), abs=.01)
            assert actual.y() == pytest.approx(expected.y(), abs=.01)
        assert _find(window, "waterQaMetric-water_ct_hu").property("text") == f'{qa.currentResult["water_ct_hu"]:.2f} HU'
    saved = qa.currentResult
    roi = saved["rois"][0]
    start = _scene(pixels, roi["column"], roi["row"])
    end = start+QPoint(20, 15)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 20)
    assert qa.dragging
    QTest.keyClick(window, Qt.Key_Escape)
    assert not qa.dragging
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    assert qa.currentResult == saved
    # Empty image regions do not create a sixth ROI; other tools keep working.
    _mouse_drag(window, _scene(pixels, 20, 20), _scene(pixels, 50, 50))
    assert qa.currentResult == saved and len(qa.roiItems) == 5
    view._tool_controller.activateTool("pan")
    previous_pan = view._state.pan_x
    _mouse_drag(window, start, start+QPoint(80, 50))
    assert view._state.pan_x != previous_pan and qa.currentResult == saved
    assert not warnings, warnings


@pytest.mark.parametrize("qa_workspace", [(1200, 820), (760, 560)], indirect=True)
def test_qa_manual_entry_replaces_per_metric_info_and_fits_window(qa_workspace, qt_app, tmp_path):
    window, view, warnings = qa_workspace
    view._tool_controller.selectService("service:qa")
    wait_qa(qt_app, view.qaController)
    QTest.qWait(30)
    panel = _find(window, "waterQaResults")
    requested = []
    panel.manualRequested.connect(lambda: requested.append(True))
    assert not any(item.objectName().startswith("waterQaInfo")
                   for item in _visual_children(window.contentItem()))
    button = _find(window, "waterQaManualButton")
    position = button.mapToScene(QPointF())
    assert 0 <= position.x() < window.width() - button.width()
    assert 0 <= position.y() < window.height() - button.height()
    result = view.qaController.currentResult
    _click(window, button)
    assert requested == [True]
    assert view.qaController.currentResult == result
    assert window.grabWindow().save(str(tmp_path / f"qa-manual-{window.width()}.png"))
    assert not warnings, warnings


def test_overlay_tracks_physical_transform_and_parameter_reset(qa_workspace, qt_app):
    window, view, warnings = qa_workspace
    tools = view._tool_controller
    tools.selectService("service:qa")
    wait_qa(qt_app, view.qaController)
    QTest.qWait(30)
    result = view.qaController.currentResult
    pixel_layer = _find(window, "dicomPixelLayer")
    for action in (lambda: None, lambda: view.apply_pan(21, -17), lambda: view.apply_zoom(1.3),
                   lambda: view.applyTransformAction("rotate:cw90"),
                   lambda: view.applyTransformAction("rotate:mirror-h"),
                   lambda: view.applyTransformAction("rotate:mirror-v")):
        action()
        QTest.qWait(20)
        for roi in view.qaController.roiItems:
            item = _find(window, "waterQaVoi-"+roi["key"])
            expected = pixel_layer.mapToItem(item, QPointF(roi["column"]+.5, roi["row"]+.5))
            point = item.property("center")
            assert point.x() == pytest.approx(expected.x(), abs=.01)
            assert point.y() == pytest.approx(expected.y(), abs=.01)
            u, v = item.property("u"), item.property("v")
            rx, ry = np.hypot(u.x()-point.x(), u.y()-point.y()), np.hypot(v.x()-point.x(), v.y()-point.y())
            assert rx == pytest.approx(ry, abs=.01)
        assert view.qaController.currentResult == result
    number = _find(window, "waterQaSetting-roiDiameterMm")
    _click(window, number)
    QTest.keyClick(window, Qt.Key_Up)
    wait_qa(qt_app, view.qaController)
    assert view.qaController.roiDiameterMm == 21
    _click(window, _find(window, "activeToolReset"))
    assert view.qaController.roiItems == [] and not view.qaController.enabled
    _click(window, _find(window, "waterQa-analyze"))
    wait_qa(qt_app, view.qaController)
    assert len(view.qaController.roiItems) == 5
    assert not warnings, warnings


@pytest.mark.parametrize("qa_workspace", [(1200, 980), (760, 560)], indirect=True)
def test_qa_row_actions_copy_and_only_delete_additional_rois(qa_workspace, qt_app, tmp_path):
    window, view, warnings = qa_workspace
    _click(window, _find(window, 'primaryTool-service'))
    _click(window, _find(window, 'serviceEntry-qa'))
    wait_qa(qt_app, view.qaController)
    QTest.qWait(40)
    for key in ('center','left','right','top','bottom'):
        assert _find(window, 'waterQaCopy-'+key).isEnabled()
        assert not _find(window, 'waterQaDelete-'+key).isEnabled()
    baseline = view.qaController.currentResult
    flick = _find(window, 'toolDetailFlickable')
    target = _find(window, 'waterQaCopy-center')
    y = target.mapToItem(flick, QPointF()).y()
    if y + target.height() > flick.height():
        flick.setProperty('contentY', flick.property('contentY') + y + target.height() - flick.height() + 8)
        QTest.qWait(40)
    _click(window, _find(window, 'waterQaCopy-center'))
    assert len(view.qaController.roiItems) == 6
    assert _find(window, 'waterQaVoi-extra-1').isVisible()
    assert _find(window, 'waterQaDelete-extra-1').isEnabled()
    assert view.qaController.currentResult['rois'][:5] == baseline['rois']
    table = _find(window, 'waterQaRoiTable')
    for item in _visual_children(table):
        if item.isVisible() and item.width() > 0:
            x = item.mapToItem(table, QPointF()).x()
            assert x >= -1 and x+item.width() <= table.width()+1
    assert window.grabWindow().save(str(tmp_path/'qa-copy-actions.png'))
    flick = _find(window, 'toolDetailFlickable')
    flick.setProperty('contentY', max(0, flick.property('contentHeight')-flick.height()))
    QTest.qWait(40)
    _click(window, _find(window, 'waterQaCopy-extra-1'))
    assert len(view.qaController.roiItems) == 7
    flick.setProperty('contentY', max(0, flick.property('contentHeight')-flick.height()))
    QTest.qWait(40)
    _click(window, _find(window, 'waterQaDelete-extra-1'))
    assert len(view.qaController.roiItems) == 6
    _click(window, _find(window, 'waterQaDelete-extra-2'))
    assert view.qaController.currentResult == baseline
    assert not warnings, warnings


def test_qa_numeric_text_commits_once_and_escape_restores(qa_workspace, qt_app):
    from PySide6.QtCore import QMetaObject
    window, view, warnings = qa_workspace
    _click(window, _find(window, "primaryTool-service"))
    _click(window, _find(window, "serviceEntry-qa"))
    wait_qa(qt_app, view.qaController)
    number = _find(window, "waterQaSetting-roiDiameterMm")
    field = number.property("contentItem")
    field.forceActiveFocus()
    QMetaObject.invokeMethod(field, "selectAll")
    QTest.keyClick(window, "3")
    QTest.keyClick(window, "0")
    assert view.qaController.roiDiameterMm == 20
    QTest.keyClick(window, Qt.Key_Escape)
    assert field.property("text") == "20"
    field.forceActiveFocus()
    QMetaObject.invokeMethod(field, "selectAll")
    QTest.keyClick(window, "3")
    QTest.keyClick(window, "0")
    QTest.keyClick(window, Qt.Key_Return)
    assert view.qaController.roiDiameterMm == 30
    assert not warnings, warnings


@pytest.mark.parametrize('change', ['slice', 'disable'])
def test_qa_draft_is_discarded_on_slice_change_or_disable(qa_workspace, qt_app, change):
    from PySide6.QtCore import QMetaObject
    from test_water_qa_controller import deliver_frame
    window, view, warnings = qa_workspace
    _click(window, _find(window, 'primaryTool-service'))
    _click(window, _find(window, 'serviceEntry-qa'))
    qa = view.qaController
    wait_qa(qt_app, qa)
    qa.setRoiDiameterMm(25)
    wait_qa(qt_app, qa)
    number = _find(window, 'waterQaSetting-roiDiameterMm')
    field = number.property('contentItem')
    field.forceActiveFocus()
    QMetaObject.invokeMethod(field, 'selectAll')
    QTest.keyClick(window, '3')
    QTest.keyClick(window, '0')
    assert qa.roiDiameterMm == 25
    if change == 'slice':
        qa.set_current_slice(1)
        assert qa.status == 'waiting'
    else:
        number.setEnabled(False)
    assert qa.roiDiameterMm == 25
    assert not number.isEnabled()
    assert number.property("value") == 25
    assert field.property('text') == '25'
    QTest.keyClick(window, Qt.Key_Return)
    assert qa.roiDiameterMm == 25
    if change == 'slice':
        deliver_frame(view, water_render(view, index=1))
        wait_qa(qt_app, qa)
        assert number.isEnabled()
        assert qa.roiDiameterMm == 25
        assert field.property('text') == '25'
    assert not warnings, warnings
