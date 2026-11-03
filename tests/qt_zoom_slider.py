"""Drag the real Qt Quick handle to an absolute magnification in a UI test."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_tag_qml import settled_point


def drag_zoom(window, slider, factor):
    handle = slider.property('handle')
    start = settled_point(handle)
    left = slider.property('leftPadding') + handle.width() / 2
    span = slider.property('availableWidth') - handle.width()
    fraction = (factor - slider.property('from')) / (slider.property('to') - slider.property('from'))
    at = lambda x: slider.mapToScene(QPointF(x, slider.height() / 2)).toPoint()
    end = at(left + span * fraction)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 10)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    return slider.property('value')
