import logging
import numpy as np

from PySide6.QtCore import QObject, Signal, Property, Slot

from voxplane.model import PixelValueMeta, ViewportConfig, PointerDisplayMeta
from voxplane.utils.utils import _display_number
logger = logging.getLogger(__name__)

class CursorController(QObject):

    cursorInfoChanged = Signal()

    def __init__(self,viewport_config:ViewportConfig, parent=None):
        super().__init__(parent)
        self.viewport_config = viewport_config
        self._pointer_meta: PointerDisplayMeta | None = None
        self._pixel_value_meta = PixelValueMeta(
            unit=(
                "HU"
                if viewport_config.series_meta.modality.strip().upper() == "CT"
                else ""
            )
        )

    def set_pixel_value_meta(self, meta: PixelValueMeta) -> None:
        if (
            not meta.unit
            and self.viewport_config.series_meta.modality.upper() == "CT"
        ):
            meta = PixelValueMeta(unit="HU", source_unit="HU")
        if meta == self._pixel_value_meta:
            return
        self._pixel_value_meta = meta
        self.cursorInfoChanged.emit()

    def resample(self, pixels):
        pointer = self._pointer_meta
        if pointer is None:
            return
        col, row = int(pointer.pointer_x), int(pointer.pointer_y)
        if pixels is None or not (0 <= row < pixels.shape[0] and 0 <= col < pixels.shape[1]):
            self.clearPosition()
        elif np.isfinite(pixels[row, col]) or self.viewport_config.role == "fusion":
            self.updatePosition(col, row, float(pixels[row, col]))
        else:
            self.clearPosition()


    @Property('QVariantMap', notify=cursorInfoChanged)
    def cursorInfo(self) -> dict:
        pointer = self._pointer_meta

        if pointer is None:
            return {
                "inside": False,
                "x": "--",
                "y": "--",
                "value": "--",
                "unit": self._pixel_value_meta.unit if not self.viewport_config.series_meta.supports_ct_analysis else "",
                "label": self._value_label(),
            }

        return {
            "inside": True,
            "x": _display_number(
                pointer.pointer_x,
                precision=0,
            ),
            "y": _display_number(
                pointer.pointer_y,
                precision=0,
            ),
            "value": _display_number(
                pointer.pointer_value,
                precision=(
                    3
                    if self.viewport_config.series_meta.modality.upper() in ("PT", "MR")
                    else 1
                ),
            ),
            "unit": self._pixel_value_meta.unit,
            "label": self._value_label(),
        }

    def _value_label(self) -> str:
        if not self.viewport_config.series_meta.supports_ct_analysis:
            return "Value"
        return (
            "PET"
            if self.viewport_config.series_meta.modality.upper() == "PT"
            else "CT"
            if self.viewport_config.series_meta.modality.upper() == "CT"
            else "MR" if self.viewport_config.series_meta.modality.upper() == "MR"
            else "Value"
        )

    @Slot(float, float)
    def updatePosition(
        self,
        column: float,
        row: float,
        value: float,
    ) -> None:
        self._pointer_meta = PointerDisplayMeta(
            pointer_x=column,
            pointer_y=row,
            pointer_value=value
        )
        self.cursorInfoChanged.emit()

    @Slot()
    def clearPosition(self) -> None:
        if self._pointer_meta is None:
            return
        self._pointer_meta = None
        self.cursorInfoChanged.emit()
