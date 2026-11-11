"""Stable, keyed rows for the virtualized patient/series sidebar."""

from difflib import SequenceMatcher

from voxplane.i18n.qt import translated_model_data
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal, Slot


class SeriesSidebarModel(QAbstractListModel):
    structureAboutToChange = Signal(bool)
    structureChanged = Signal(bool)
    ROW_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._query = ""

    def roleNames(self):
        return {self.ROW_ROLE: b"modelData"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    @translated_model_data
    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and 0 <= index.row() < len(self._rows) and role == self.ROW_ROLE:
            return self._rows[index.row()]
        return None

    @Slot(int, result=str)
    def keyAt(self, index):
        return self._rows[index]["key"] if 0 <= index < len(self._rows) else ""

    @Slot(str, result=int)
    def indexOfKey(self, key):
        return next((i for i, row in enumerate(self._rows) if row["key"] == key), -1)

    def update_rows(self, rows, query):
        old_keys = [row["key"] for row in self._rows]
        new_keys = [row["key"] for row in rows]
        reset_scroll = query != self._query
        structural = old_keys != new_keys or reset_scroll
        if structural:
            self.structureAboutToChange.emit(reset_scroll)
        self._query = query
        # Reverse edits leave the indexes of earlier unchanged spans intact.
        for operation, start, end, new_start, new_end in reversed(
            SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_opcodes()
        ):
            if operation == "equal":
                continue
            if end > start:
                self.beginRemoveRows(QModelIndex(), start, end - 1)
                del self._rows[start:end]
                self.endRemoveRows()
            if new_end > new_start:
                self.beginInsertRows(QModelIndex(), start, start + new_end - new_start - 1)
                self._rows[start:start] = rows[new_start:new_end]
                self.endInsertRows()
        for index, row in enumerate(rows):
            if row != self._rows[index]:
                self._rows[index] = row
                self.dataChanged.emit(self.index(index), self.index(index), [self.ROW_ROLE])
        if structural:
            self.structureChanged.emit(reset_scroll)
