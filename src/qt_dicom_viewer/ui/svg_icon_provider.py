"""DPR-sized, tintable SVG action assets shared by QML icons."""
from functools import lru_cache
from importlib.resources import files
from urllib.parse import unquote

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

NAMES = frozenset({
    'tab-detach', 'tab-return', 'tab-close-others', 'tab-close-right', 'tab-close-all',
    'nav-compare-2d', 'nav-compare-mpr', 'manual', 'annotate', 'annotate-arrow', 'annotate-text', 'cine-pause', 'cine-play', 'cine-stop', 'cine-4d-play', 'cine-4d-stop', 'clear',
    'layout-right', 'layout-left', 'layout-columns', 'layout-rows', 'layout-top', 'layout-bottom', 'layout-quad',
    'crop-inside', 'crop-outside', 'crosshair-rotate', 'copy', 'delete', 'import', 'export', 'export-dicom',
    'export-png', 'fusion', 'invert', 'measure', 'measure-angle',
    'measure-ellipse', 'measure-freehand', 'measure-curve', 'measure-line', 'measure-rect', 'mip', 'mirror-h',
    'mirror-v', 'mtf', 'nav-load-file', 'nav-pacs', 'nav-view-2d', 'nav-view-3d',
    'nav-view-4d', 'nav-view-mpr', 'nav-view-tag', 'nav-view-tile', 'palette',
    'pan', 'qa', 'remove-bed', 'reset', 'rotate',
    'rotate-3d', 'rotate-ccw90', 'rotate-cw90', 'save', 'scroll',
    'segmentation', 'service', 'viewport-settings', 'voi', 'volume-crop',
    'window', 'zoom', 'workspace', 'status-pending',
    'visible', 'hidden', 'locked', 'unlocked', 'fwhm', 'github', 'feedback', 'check', 'chevron-left', 'chevron-right', 'chevron-down', 'chevron-up', 'close', 'folder', 'fullscreen', 'help', 'info',
    'pet-window', 'pseudocolor', 'registration', 'rotate-3d-variant', 'settings',
    'shield', 'slice-next', 'slice-previous', 'view-tile', 'volume-bed',
})

@lru_cache(maxsize=256)
def render_icon(name, tint, accent, width, height):
    # Supersample before the final DPR-sized texture; keeps tiny diagonals and
    # rounded strokes smooth even with the Qt Quick software renderer.
    scale = 2
    image = QImage(width * scale, height * scale, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    if name not in NAMES:
        name = "help"
    color = QColor(tint)
    detail = QColor(accent)
    svg = files("qt_dicom_viewer").joinpath("qml/assets/icons/" + name + ".svg").read_text()
    svg = svg.replace("#aabcc8", color.name() if color.isValid() else "#aabcc8")
    svg = svg.replace("#5dc4c5", detail.name() if detail.isValid() and detail.alpha() else color.name())
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

class SvgIconProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, identifier, size, requestedSize):
        parts = [unquote(p) for p in identifier.split("/")]
        name, tint, accent = (parts + ["#aabcc8", "transparent"])[:3]
        width = min(512, max(1, requestedSize.width() if requestedSize.width() > 0 else 24))
        height = min(512, max(1, requestedSize.height() if requestedSize.height() > 0 else width))
        size.setWidth(width)
        size.setHeight(height)
        return render_icon(name, tint, accent, width, height)
