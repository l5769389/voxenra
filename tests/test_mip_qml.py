"""用真实 QML 事件验证 MIP 面板与厚度辅助线。"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import (
    MprFrame,
    MprPlane,
    MprRenderResult,
    MprState,
    TabType,
)
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.viewport.image_2d.mpr_viewport_controller import (
    MprViewportController,
)
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_measurement_qml import _visual_children, qt_app
from test_viewport_controller_hierarchy import (
    _frame_meta,
    _mpr_geometry_for_plane,
    _viewport_config,
)


def _find(view: QQuickView, name: str):
    return next(
        item
        for item in _visual_children(view.rootObject())
        if item.objectName() == name and item.isVisible()
    )


def _click(view: QQuickView, item, x_ratio: float = 0.5) -> None:
    point = item.mapToScene(
        QPointF(item.width() * x_ratio, item.height() / 2)
    ).toPoint()
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(40)


@pytest.fixture
def mip_panel(qt_app):
    controller = ToolController(tab_type=TabType.MPR)
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(340, 640)
    warnings = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "toolController": controller,
        "toolVisible": True,
        "viewportController": None,
    })
    source = (
        Path(__file__).resolve().parents[1]
        / "src/qt_dicom_viewer/qml/sections/RightPanel.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [
        error.toString() for error in view.errors()
    ]
    view.show()
    QTest.qWait(80)
    try:
        yield view, controller, warnings
    finally:
        view.hide()
        delete(view)


def test_mip_panel_updates_mode_enablement_and_live_thickness(
    mip_panel,
    tmp_path,
) -> None:
    view, controller, warnings = mip_panel

    mip_button = _find(view, "primaryTool-mip")
    mip_icon = next(item for item in _visual_children(mip_button)
                    if item.objectName() == "navigationSvgIcon" and item.isVisible())
    inactive_color = mip_icon.parentItem().property("iconColor")
    origin = mip_icon.mapToItem(mip_button, QPointF())
    corner = mip_icon.mapToItem(mip_button, QPointF(mip_icon.width(), mip_icon.height()))
    assert corner.x() - origin.x() == pytest.approx(24)
    assert corner.y() - origin.y() == pytest.approx(24)

    _click(view, _find(view, "primaryTool-mip"))
    assert _find(view, "mipPanel") is not None
    assert _find(view, "mipMode-mip").property("checked")
    assert mip_icon.parentItem().property("iconColor") != inactive_color

    _click(view, _find(view, "mipMode-mean"))
    thickness_input = _find(view, "mipThicknessInput-axial")
    _click(view, thickness_input)
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(view, Qt.Key_3)
    QTest.keyClick(view, Qt.Key_6)
    QTest.qWait(40)
    assert controller.mprThicknesses["axial"] != 36
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(40)
    assert controller.mprThicknesses["axial"] == 36
    assert _find(view, "mipThickness-axial").property("value") == 36

    _click(view, _find(view, "mipThickness-axial"), 0.52)
    QTest.qWait(40)
    slider_value = round(
        _find(view, "mipThickness-axial").property("value")
    )
    assert slider_value == pytest.approx(52, abs=2)
    assert _find(view, "mipThicknessInput-axial").property("text") == str(
        slider_value
    )
    _click(view, _find(view, "mipEnabledSwitch"))

    assert controller.mprProjectionMode == "mean"
    assert controller.mprThicknesses["axial"] == pytest.approx(52, abs=2)
    assert controller.mprProjectionEnabled is True
    assert not warnings, warnings

    screenshot = view.grabWindow()
    assert not screenshot.isNull()
    assert screenshot.save(str(tmp_path / "mip-panel.png"))


def test_mpr_slab_guide_layer_tracks_image_transforms(qt_app, tmp_path) -> None:
    tools = ToolController(tab_type=TabType.MPR)
    controller = MprViewportController(
        _viewport_config(MprPlane.CORONAL),
        tools,
    )
    frame = MprFrame.standard_lps((10.0, 20.0, 30.0))
    frame_meta = _frame_meta()
    frame_meta = replace(
        frame_meta,
        instance_meta=replace(
            frame_meta.instance_meta,
            rows=101,
            columns=101,
            pixel_spacing=(2.0, 3.0),
        ),
        geometry=replace(
            frame_meta.geometry,
            rows=101,
            columns=101,
        ),
    )
    pixels = np.zeros((101, 101), dtype=np.uint8)
    controller.handleRenderResult(
        MprRenderResult(
            response_id="guide-result",
            viewport_id=controller.viewport_config.viewport_id,
            series_uid=controller.viewport_config.series_uid,
            view_type=MprPlane.CORONAL,
            image=pixels,
            modality_pixel=pixels.astype(np.float32),
            frame_meta=frame_meta,
            mpr_frame=frame,
            plane_geometry=_mpr_geometry_for_plane(
                frame,
                MprPlane.CORONAL,
            ),
        )
    )
    controller.apply_mpr_state(MprState(frame))
    tools.setMprThickness("axial", 10)
    tools.setMprProjectionEnabled(True)

    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(640, 480)
    provider = DicomImageProvider()
    provider.set_array(controller.viewport_config.viewport_id, pixels)
    view.engine().addImageProvider("dicom", provider)
    warnings = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "viewportController": controller,
        "hasTabs": True,
    })
    source = (
        Path(__file__).resolve().parents[1]
        / "src/qt_dicom_viewer/qml/sections/center/viewportArea/Viewport.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [
        error.toString() for error in view.errors()
    ]
    view.show()
    QTest.qWait(80)
    try:
        layer = view.rootObject().findChild(
            QQuickItem,
            "mprSlabGuideLayer",
        )
        assert layer is not None and layer.isVisible()
        assert len(controller.mprSlabGuides) == 2

        controller.apply_zoom(1.4)
        controller.applyTransformAction("rotate:cw90")
        controller.applyTransformAction("rotate:mirror-h")
        QTest.qWait(80)

        assert layer.isVisible()
        assert not warnings, warnings
        screenshot = view.grabWindow()
        assert not screenshot.isNull()
        assert screenshot.save(str(tmp_path / "mpr-slab-guides.png"))

        tools.setMprProjectionEnabled(False)
        QTest.qWait(20)
        assert not layer.isVisible()
    finally:
        view.hide()
        delete(view)
