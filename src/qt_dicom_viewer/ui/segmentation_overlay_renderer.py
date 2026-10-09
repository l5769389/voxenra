"""Bounded display cache for segmentation planes; never owns quantitative state."""
from collections import OrderedDict
from dataclasses import dataclass
from weakref import ReferenceType, ref

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from qt_dicom_viewer.core.mpr_voi import plane_mask
from qt_dicom_viewer.core.segmentation_display import segmentation_rgba


@dataclass(frozen=True, slots=True)
class _PlaneOverlay:
    plane: object
    source_mask: ReferenceType
    source_geometry: object
    offset: tuple
    style: tuple
    mask: object
    source: str

    def matches(self, evaluation, plane):
        # Committed evaluations and brush samples replace their masks. Preview
        # wrappers may be recreated by QML reads; wrapper identity is irrelevant.
        return (self.plane == plane and self.source_mask() is evaluation.mask
                and self.source_geometry == evaluation.geometry
                and self.offset == tuple(evaluation.offset))

    @property
    def display_bytes(self):
        return self.mask.nbytes + len(self.source)


def _png_source(mask, color, mode, opacity):
    qcolor = QColor(color)
    rgba = segmentation_rgba(mask, (qcolor.red(), qcolor.green(), qcolor.blue()), mode, opacity)
    image = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format_RGBA8888)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64," + bytes(buffer.data().toBase64()).decode("ascii")


class SegmentationOverlayRenderer:
    """One plane per view/segment, additionally bounded across dynamic layouts.

    Input masks are snapshots: callers must replace them after editing. Mask
    sampling is independent of display style, so opacity/color changes reuse
    the plane. Returned PNG strings preserve the existing QML image interface.
    """
    def __init__(self, *, max_entries=64, max_bytes=32 * 1024**2):
        self._entries = OrderedDict()
        self._bytes = 0
        self._max_entries = max_entries
        self._max_bytes = max_bytes

    def source(self, viewport_id, record_id, evaluation, plane, color, mode, opacity):
        key = (viewport_id, record_id)
        cached = self._entries.get(key)
        style = (color, mode, opacity)
        same_plane = cached is not None and cached.matches(evaluation, plane)
        if same_plane and cached.style == style:
            self._entries.move_to_end(key)
            return cached.source
        mask = cached.mask if same_plane else plane_mask(evaluation, plane)
        source = _png_source(mask, *style)
        # A cached 2D image must not keep an obsolete 3D brush/history mask alive.
        entry = _PlaneOverlay(plane, ref(evaluation.mask), evaluation.geometry,
                              tuple(evaluation.offset), style, mask, source)
        self._drop(key)
        if entry.display_bytes <= self._max_bytes and self._max_entries > 0:
            self._entries[key] = entry
            self._bytes += entry.display_bytes
            while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                self._drop(next(iter(self._entries)))
        return source

    def _drop(self, key):
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= entry.display_bytes

    def retain(self, record_ids):
        for key in list(self._entries):
            if key[1] not in record_ids:
                self._drop(key)

    def discard(self, record_id):
        for key in list(self._entries):
            if key[1] == record_id:
                self._drop(key)

    def clear(self):
        self._entries.clear()
        self._bytes = 0
