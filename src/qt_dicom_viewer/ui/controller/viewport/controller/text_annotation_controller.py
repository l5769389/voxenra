from __future__ import annotations
from qt_dicom_viewer.i18n import message as _msg

from dataclasses import dataclass, replace
import math
from math import isfinite
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QColor

from qt_dicom_viewer.model.dicom_types import FrameDisplayMeta


@dataclass(frozen=True, slots=True)
class TextAnnotation:
    annotation_id: str
    slice_index: int
    tail_column: float
    tail_row: float
    head_column: float
    head_row: float
    text: str
    color: str
    font_size: int
    frame_key: tuple


class TextAnnotationController(QObject):


    annotationsChanged = Signal()
    editorChanged = Signal()
    selectionChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._annotations: dict[str, TextAnnotation] = {}
        self._current_slice: int | None = None
        self._frame_key: tuple | None = None
        self._selected_id = ""
        self._draft_id = ""
        self._text = _msg('text.0307')
        self._color = "#ffd45c"
        self._font_size = 16

    def set_current_slice(self, slice_index: int | None) -> None:
        if slice_index == self._current_slice:
            return
        self.cancelDraft()
        self._current_slice = slice_index
        selected = self._annotations.get(self._selected_id)
        if selected is not None and selected.slice_index != slice_index:
            self._selected_id = ""
            self.selectionChanged.emit()
            self.editorChanged.emit()
        self.annotationsChanged.emit()

    def set_frame(self, series_uid: str, frame: FrameDisplayMeta, *, source_context: tuple = ()) -> None:
        geometry = frame.geometry
        pose = (
            geometry.pixel_spacing.row,
            geometry.pixel_spacing.column,
            *(geometry.image_position_patient or ()),
            *(geometry.image_orientation_patient or ()),
        )
        frame_key = (
            series_uid,
            frame.instance_meta.sop_instance_uid,
            frame.slice_index,
            geometry.rows,
            geometry.columns,
            tuple(
                round(value, 7)
                if isinstance(value, (int, float)) and math.isfinite(value)
                else str(value)
                for value in pose
            ),
        )
        # Reconstructed phases and projections can share both geometry and SOP.
        # Preserve the existing key for ordinary 2D workspace annotations.
        if source_context:
            frame_key += (source_context,)
        if frame_key == self._frame_key and frame.slice_index == self._current_slice:
            return
        self.cancelDraft()
        self._frame_key = frame_key
        self.set_current_slice(frame.slice_index)
        self.clearSelection()
        self.annotationsChanged.emit()

    @Property('QVariantList', notify=annotationsChanged)
    def annotationItems(self) -> list[dict]:
        return [
            {
                "annotationId": annotation.annotation_id,
                "sliceIndex": annotation.slice_index,
                "tailColumn": annotation.tail_column,
                "tailRow": annotation.tail_row,
                "headColumn": annotation.head_column,
                "headRow": annotation.head_row,
                # Retain the old label-anchor fields for API compatibility.
                "column": annotation.tail_column,
                "row": annotation.tail_row,
                "text": annotation.text,
                "color": annotation.color,
                "fontSize": annotation.font_size,
                "selected": annotation.annotation_id == self._selected_id,
                "draft": annotation.annotation_id == self._draft_id,
            }
            for annotation in self._annotations.values()
            if annotation.slice_index == self._current_slice
            and annotation.frame_key == self._frame_key
        ]

    @Property(str, notify=editorChanged)
    def annotationText(self) -> str:
        return self._text

    @Property(str, notify=editorChanged)
    def annotationColor(self) -> str:
        return self._color

    @Property(int, notify=editorChanged)
    def annotationFontSize(self) -> int:
        return self._font_size

    @Property(str, notify=selectionChanged)
    def selectedAnnotationId(self) -> str:
        return self._selected_id

    @Property(bool, notify=selectionChanged)
    def hasSelection(self) -> bool:
        return self._selected_id in self._annotations

    @Property(bool, notify=annotationsChanged)
    def hasAnnotations(self) -> bool:
        return bool(self._annotations)

    def _update_selected(self, **changes) -> None:
        selected = self._annotations.get(self._selected_id)
        if selected is None:
            return
        updated = replace(selected, **changes)
        if updated == selected:
            return
        self._annotations[selected.annotation_id] = updated
        self.annotationsChanged.emit()

    def applyStyleDefaults(self, *, color=None, font_size=None) -> None:
        """Apply changed workspace defaults to existing annotations on every frame."""
        changes = {}
        if color is not None and QColor(color).isValid():
            self._color = QColor(color).name()
            changes["color"] = self._color
        if font_size is not None:
            self._font_size = max(10, min(int(font_size), 48))
            changes["font_size"] = self._font_size
        if not changes:
            return
        updated = {key: replace(item, **changes) for key, item in self._annotations.items()}
        if updated != self._annotations:
            self._annotations = updated
            self.annotationsChanged.emit()
        self.editorChanged.emit()

    @Slot(str)
    def setAnnotationText(self, text: str) -> None:
        text = str(text)[:200]
        if text == self._text:
            return
        self._text = text
        self._update_selected(text=text)
        self.editorChanged.emit()

    @Slot(str)
    def setAnnotationColor(self, color: str) -> None:
        value = QColor(color)
        if not value.isValid():
            return
        color = value.name()
        if color == self._color:
            return
        self._color = color
        self._update_selected(color=color)
        self.editorChanged.emit()

    @Slot(int)
    def setAnnotationFontSize(self, size: int) -> None:
        size = max(10, min(int(size), 48))
        if size == self._font_size:
            return
        self._font_size = size
        self._update_selected(font_size=size)
        self.editorChanged.emit()

    @Slot(float, float)
    @Slot(float, float, float, float)
    def addAnnotation(
            self,
            tail_column: float,
            tail_row: float,
            head_column: float | None = None,
            head_row: float | None = None,
    ) -> None:
        """Add a complete arrow annotation.

        The two-argument form is kept for callers that create annotations
        programmatically; interactive placement always supplies both ends.
        """
        if head_column is None:
            head_column = tail_column + 40.0
        if head_row is None:
            head_row = tail_row - 30.0
        if (
            self._current_slice is None
            or not all(isfinite(value) for value in (
                tail_column, tail_row, head_column, head_row
            ))
            or self._frame_key is None
        ):
            return
        annotation = TextAnnotation(
            annotation_id=str(uuid4()),
            slice_index=self._current_slice,
            tail_column=float(tail_column),
            tail_row=float(tail_row),
            head_column=float(head_column),
            head_row=float(head_row),
            text=self._text.strip(),
            color=self._color,
            font_size=self._font_size,
            frame_key=self._frame_key,
        )
        self._annotations[annotation.annotation_id] = annotation
        self._selected_id = annotation.annotation_id
        self.annotationsChanged.emit()
        self.selectionChanged.emit()

    def selected_copy(self) -> dict | None:
        annotation = self._annotations.get(self._selected_id)
        if (self._draft_id or annotation is None or annotation.frame_key != self._frame_key
                or annotation.slice_index != self._current_slice):
            return None
        return {"kind": "text", "points": [[annotation.tail_column, annotation.tail_row],
                [annotation.head_column, annotation.head_row]], "text": annotation.text,
                "color": annotation.color, "fontSize": annotation.font_size}

    def paste_copy(self, payload, points) -> str:
        if self._draft_id or self._frame_key is None or self._current_slice is None:
            return ""
        (tail_column, tail_row), (head_column, head_row) = points
        if math.hypot(head_column - tail_column, head_row - tail_row) < 0.5:
            return ""
        annotation = TextAnnotation(str(uuid4()), self._current_slice, tail_column, tail_row,
            head_column, head_row, payload["text"], payload["color"], payload["fontSize"], self._frame_key)
        self._annotations[annotation.annotation_id] = annotation
        self.selectAnnotation(annotation.annotation_id)
        self.annotationsChanged.emit()
        return annotation.annotation_id

    def beginAnnotation(self, tail_column: float, tail_row: float) -> bool:
        if (
            self._current_slice is None
            or self._frame_key is None
            or not isfinite(tail_column)
            or not isfinite(tail_row)
        ):
            return False
        self.cancelDraft()
        annotation = TextAnnotation(
            annotation_id=str(uuid4()),
            slice_index=self._current_slice,
            tail_column=float(tail_column),
            tail_row=float(tail_row),
            head_column=float(tail_column),
            head_row=float(tail_row),
            text=self._text.strip(),
            color=self._color,
            font_size=self._font_size,
            frame_key=self._frame_key,
        )
        self._annotations[annotation.annotation_id] = annotation
        self._draft_id = annotation.annotation_id
        self._selected_id = annotation.annotation_id
        self.annotationsChanged.emit()
        self.selectionChanged.emit()
        return True

    def updateAnnotation(self, head_column: float, head_row: float) -> None:
        annotation = self._annotations.get(self._draft_id)
        if (
            annotation is None
            or not isfinite(head_column)
            or not isfinite(head_row)
        ):
            return
        updated = replace(
            annotation,
            head_column=float(head_column),
            head_row=float(head_row),
        )
        if updated == annotation:
            return
        self._annotations[annotation.annotation_id] = updated
        self.annotationsChanged.emit()

    def finishAnnotation(self, head_column: float, head_row: float) -> None:
        annotation = self._annotations.get(self._draft_id)
        if annotation is None:
            return
        self.updateAnnotation(head_column, head_row)
        annotation = self._annotations.get(self._draft_id)
        self._draft_id = ""
        if annotation is None:
            return
        arrow_length = math.hypot(
            annotation.head_column - annotation.tail_column,
            annotation.head_row - annotation.tail_row,
        )
        if arrow_length < 0.5:
            del self._annotations[annotation.annotation_id]
            self._selected_id = ""
            self.selectionChanged.emit()
        self.annotationsChanged.emit()

    def cancelDraft(self) -> None:
        if not self._draft_id:
            return
        draft_id = self._draft_id
        self._draft_id = ""
        self._annotations.pop(draft_id, None)
        if self._selected_id == draft_id:
            self._selected_id = ""
            self.selectionChanged.emit()
        self.annotationsChanged.emit()

    @Slot(float, float, float)
    def selectAnnotationAt(
            self,
            column: float,
            row: float,
            tolerance: float,
    ) -> None:
        if not isfinite(column) or not isfinite(row):
            self.clearSelection()
            return
        tolerance = max(0.0, float(tolerance))
        candidates: list[tuple[float, str]] = []
        for annotation in self._annotations.values():
            if (
                annotation.slice_index != self._current_slice
                or annotation.frame_key != self._frame_key
                or annotation.annotation_id == self._draft_id
            ):
                continue
            distance = _distance_to_segment(
                column,
                row,
                annotation.tail_column,
                annotation.tail_row,
                annotation.head_column,
                annotation.head_row,
            )
            if distance <= tolerance:
                candidates.append((distance, annotation.annotation_id))
        if not candidates:
            self.clearSelection()
            return
        self.selectAnnotation(min(candidates)[1])

    @Slot(str)
    def selectAnnotation(self, annotation_id: str) -> None:
        annotation = self._annotations.get(annotation_id)
        if (
            annotation is None
            or annotation.slice_index != self._current_slice
            or annotation.frame_key != self._frame_key
        ):
            return
        selection_changed = annotation_id != self._selected_id
        self._selected_id = annotation_id
        editor_changed = (
            self._text != annotation.text
            or self._color != annotation.color
            or self._font_size != annotation.font_size
        )
        self._text = annotation.text
        self._color = annotation.color
        self._font_size = annotation.font_size
        if selection_changed:
            self.selectionChanged.emit()
            self.annotationsChanged.emit()
        if editor_changed:
            self.editorChanged.emit()

    @Slot()
    def clearSelection(self) -> None:
        if not self._selected_id:
            return
        self._selected_id = ""
        self.selectionChanged.emit()
        self.annotationsChanged.emit()

    @Slot()
    def deleteSelected(self) -> None:
        if self._selected_id not in self._annotations:
            return
        if self._draft_id == self._selected_id:
            self._draft_id = ""
        del self._annotations[self._selected_id]
        self._selected_id = ""
        self.annotationsChanged.emit()
        self.selectionChanged.emit()

    @Slot()
    def clearAll(self) -> None:
        if not self._annotations:
            return
        self._annotations.clear()
        self._selected_id = ""
        self._draft_id = ""
        self.annotationsChanged.emit()
        self.selectionChanged.emit()


def _distance_to_segment(
        column: float,
        row: float,
        tail_column: float,
        tail_row: float,
        head_column: float,
        head_row: float,
) -> float:
    delta_column = head_column - tail_column
    delta_row = head_row - tail_row
    length_squared = delta_column ** 2 + delta_row ** 2
    if length_squared <= 0:
        return math.hypot(column - tail_column, row - tail_row)
    fraction = (
        (column - tail_column) * delta_column
        + (row - tail_row) * delta_row
    ) / length_squared
    fraction = max(0.0, min(1.0, fraction))
    closest_column = tail_column + fraction * delta_column
    closest_row = tail_row + fraction * delta_row
    return math.hypot(column - closest_column, row - closest_row)
