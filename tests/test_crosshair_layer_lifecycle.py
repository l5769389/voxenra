"""A retiring viewport can clear its style before its QML layer is destroyed."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtQuick import QQuickView

from test_dicom_tags import qt_app


@pytest.mark.parametrize('cleared_style', [{}, None])
def test_crosshair_style_can_be_cleared_without_qml_errors(qt_app, cleared_style):
    view = QQuickView()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    source = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml/sections/center/viewportArea/CrosshairLayer.qml'
    view.setInitialProperties({
        'crosshairStyle': {'centerGap': 4, 'lineWidth': 2,
                          'horizontalColor': '#ff0000', 'verticalColor': '#00ff00'},
        'crosshairPosition': QPointF(20, 20), 'rotationDegrees': 0})
    view.setSource(QUrl.fromLocalFile(str(source)))
    layer = view.rootObject()
    assert layer is not None, view.errors()
    initial_width = layer.property('lineWidth')
    initial_color = layer.property('horizontalColor').name()
    layer.setProperty('crosshairStyle', cleared_style)
    final_width = layer.property('lineWidth')
    final_alpha = layer.property('horizontalColor').alpha()
    view.setSource(QUrl())
    del layer, view
    assert initial_width == 2 and initial_color == '#ff0000'
    assert not warnings, warnings
    assert final_width == 0 and final_alpha == 0
