"""Shared QML/native cursor artwork, rasterized at the native screen density."""
from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QCursor, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


CURSOR_KINDS = frozenset(('window', 'scroll', 'crosshair-move', 'crosshair-rotate', 'rotate-3d', 'voi', 'segmentation', 'segmentation-paint', 'segmentation-erase', 'volume-crop', 'resize', 'mtf', 'strokeColor', 'fillColor', 'pan', 'zoom', 'measure-line', 'measure-angle', 'measure-rect', 'measure-ellipse', 'measure-freehand', 'measure-curve', 'annotate-arrow', 'annotate-text', 'qa', 'rotate'))


@lru_cache(maxsize=128)
def tool_cursor(kind: str, device_pixel_ratio: float = 1.0) -> QCursor:
    """Call on the GUI thread. The hotspot and artwork use logical pixels."""
    if kind not in CURSOR_KINDS:
        raise ValueError(f"No shared cursor for {kind}")
    ratio = max(1.0, float(device_pixel_ratio))
    width, height = round(40 * ratio), round(32 * ratio)
    svg = files("qt_dicom_viewer").joinpath(f"qml/assets/cursors/{kind}.svg").read_bytes()
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(svg).render(painter, QRectF(0, 0, width, height))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return QCursor(pixmap, 2, 2)
