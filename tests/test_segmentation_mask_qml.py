"""Rendered erase previews retain unchanged foreground pixels across swaps."""
from pathlib import Path

from PySide6.QtCore import QUrl, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until


def test_mask_frames_do_not_clear_or_double_blend(qt_app):
    view = QQuickView()
    view.setColor(QColor('black'))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(64, 64)
    path = Path(__file__).parents[1] / 'src/qt_dicom_viewer/qml/sections/center/viewportArea/SegmentationMaskImage.qml'
    view.setSource(QUrl.fromLocalFile(str(path.resolve())))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(20)
    item = view.rootObject()
    try:
        color = None
        for cut in list(range(12, 40)) + list(range(39, 11, -1)):
            mask = QImage(64, 64, QImage.Format_RGBA8888)
            mask.fill(QColor(255, 0, 255, 95))
            for y in range(12, cut):
                for x in range(12, cut):
                    mask.setPixelColor(x, y, QColor(0, 0, 0, 0))
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            mask.save(buffer, 'PNG')
            item.setProperty('source', QUrl('data:image/png;base64,' + bytes(buffer.data().toBase64()).decode()))
            if color is None:
                wait_until(lambda: item.property("maskReady"))
            image = view.grabWindow()
            assert item.property('maskReady')
            pixel = image.pixelColor(4, 4)
            assert pixel.red() > 0
            if color is None:
                color = pixel
            assert pixel == color  # neither blank nor old+new alpha accumulation
            for _ in range(6):
                QTest.qWait(5)
                image = view.grabWindow()
                assert image.pixelColor(4, 4) == color
            if cut > 12:
                assert image.pixelColor(int(12 * image.width()/64), int(12 * image.height()/64)).red() == 0, (cut, item.property('front'), [(x.isVisible(), x.property('source') == item.property('source')) for x in item.childItems()])
    finally:
        view.close()
