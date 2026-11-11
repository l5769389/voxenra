"""Flatten only visible nodes; filtering traverses the complete metadata tree."""

from voxplane.i18n.qt import translated_model_data
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal, Property

from voxplane.model.dicom_tags import TagNode


class TagTreeModel(QAbstractListModel):
    countsChanged = Signal()
    _ROLE_NAMES = ("nodeId", "depth", "tagNumber", "tagName", "keyword", "vr", "valueText", "hasChildren", "expanded", "isItem", "matched")
    _ROLES = {Qt.UserRole + index + 1: name.encode() for index, name in enumerate(_ROLE_NAMES)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots: tuple[TagNode, ...] = ()
        self._rows = []
        self._expanded: set[str] = set()
        self._query = ""
        self._total = self._matched = 0

    def roleNames(self):
        return self._ROLES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    @translated_model_data
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return row["tagName"]
        name = self._ROLES.get(role)
        return row.get(name.decode()) if name else None

    @Property(int, notify=countsChanged)
    def totalCount(self):
        return self._total

    @Property(int, notify=countsChanged)
    def matchCount(self):
        return self._matched

    @Property(int, notify=countsChanged)
    def maxVisibleDepth(self):
        return max((row["depth"] for row in self._rows), default=0)

    @property
    def expanded_nodes(self):
        return sorted(self._expanded)

    def set_nodes(self, nodes: tuple[TagNode, ...], *, reset_expansion=True) -> None:
        self._roots = nodes
        if reset_expansion:
            self._expanded.clear()
        self._rebuild()

    def set_query(self, query: str, *, expanded=None) -> None:
        if expanded is not None:
            self._expanded = set(expanded)
        self._query = query.strip().casefold()
        self._rebuild()

    def toggle(self, node_id: str) -> None:
        # Search keeps every matching path visible; it never overwrites manual expansion.
        if self._query:
            return
        if node_id in self._expanded:
            self._expanded.remove(node_id)
        else:
            self._expanded.add(node_id)
        self._rebuild()

    def _rebuild(self) -> None:
        matches = set()
        included = set()
        self._total = 0

        def visit(node):
            if not node.is_item:
                self._total += 1
                compact_tag = node.tag.replace("(", "").replace(")", "").replace(",", "")
                text = " ".join((node.tag, compact_tag, node.name, node.keyword, node.value)).casefold()
                if not self._query or self._query in text:
                    matches.add(node.node_id)
            child_match = False
            for child in node.children:
                child_match = visit(child) or child_match
            if node.node_id in matches or child_match:
                included.add(node.node_id)
                return True
            return False

        for node in self._roots:
            visit(node)
        self._matched = len(matches)
        rows = []

        def flatten(node, depth):
            if self._query and node.node_id not in included:
                return
            expanded = bool(node.children) and (bool(self._query) or node.node_id in self._expanded)
            rows.append(dict(zip(self._ROLE_NAMES, (
                node.node_id, depth, node.tag, node.name, node.keyword, node.vr, node.value,
                bool(node.children), expanded, node.is_item, bool(self._query) and node.node_id in matches,
            ))))
            if expanded:
                for child in node.children:
                    flatten(child, depth + 1)

        for node in self._roots:
            flatten(node, 0)
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countsChanged.emit()
