"""Manage application-local directory bookmarks without changing image data."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QHeaderView,
                              QHBoxLayout, QTableWidgetItem, QVBoxLayout)

from qt_dicom_viewer.i18n import message as _msg, localize
from qt_dicom_viewer.i18n.widgets import QDialog, QFileDialog, QLabel, QLineEdit, QPushButton
from .local_import_dialog import apply_import_dialog_theme
from .reorder_table import ReorderTable


def choose_favorite_directory(controller, id=""):
    # Do not inspect an old offline path to choose an initial directory.
    directory = QFileDialog.getExistingDirectory(
        QApplication.activeModalWidget(), _msg('favorites.choose'), "")
    if directory:
        return controller.requestReplacement(id, directory) if id else controller.requestAdd(directory)
    return False


class FavoriteDirectoriesDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName('favoriteDirectoriesDialog')
        self.setWindowTitle(_msg('favorites.manage'))
        self.resize(760, 510)
        self.setMinimumSize(560, 420)
        apply_import_dialog_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.empty = QLabel(_msg('favorites.empty'))
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.table = ReorderTable(2)
        self.table.rowMoveRequested.connect(controller.move)
        self.table.setObjectName('favoriteDirectoryList')
        self.table.setHorizontalHeaderLabels([localize(_msg('text.0528')), localize(_msg('favorites.path'))])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.setColumnWidth(0, 180)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        tools = QHBoxLayout()
        self.add_button = self._button('favoriteDirectoryAdd', 'favorites.add', controller.chooseAndAdd)
        self.remove_button = self._button('favoriteDirectoryRemove', 'favorites.remove', lambda: controller.remove(self.current_id()))
        tools.addWidget(self.add_button)
        tools.addWidget(self.remove_button)
        tools.addStretch(1)
        tools.addWidget(QLabel(_msg("sort.drag")))
        layout.addLayout(tools)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(_msg('text.0528')))
        self.name = QLineEdit()
        self.name.setObjectName('favoriteDirectoryName')
        self.name.setMaxLength(120)
        self.name.returnPressed.connect(self._rename)
        self.name.textChanged.connect(self._name_changed)
        name_row.addWidget(self.name, 1)
        self.rename_button = self._button('favoriteDirectoryRename', 'favorites.saveName', self._rename)
        name_row.addWidget(self.rename_button)
        layout.addLayout(name_row)
        self.path = QLabel()
        self.path.setObjectName('favoriteDirectoryPath')
        self.path.setTextFormat(Qt.PlainText)
        self.path.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.path.setWordWrap(True)
        self.path.setMinimumWidth(0)
        layout.addWidget(self.path)
        self.replace_button = self._button('favoriteDirectoryReplace', 'favorites.replace', lambda: controller.chooseReplacement(self.current_id()))
        self.replace_button.setMaximumWidth(200)
        layout.addWidget(self.replace_button)
        self.status = QLabel()
        self.status.setObjectName('favoriteDirectoryStatus')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.close_button = self._button('favoriteDirectoryClose', 'text.0621', self.accept)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        controller.changed.connect(self.refresh)
        controller.messageChanged.connect(self._message)
        controller.busyChanged.connect(self._busy_changed)
        self.refresh()
        self._message()

    def _button(self, name, key, action):
        button = QPushButton(_msg(key))
        button.setObjectName(name)
        button.setAutoDefault(False)
        button.clicked.connect(action)
        return button

    def current_id(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else ''

    def refresh(self):
        selected, row = self.current_id(), self.table.currentRow()
        items = self.controller.items
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        for index, entry in enumerate(items):
            name = QTableWidgetItem(entry['name'])
            name.setData(Qt.UserRole, entry['id'])
            self.table.setItem(index, 0, name)
            path_item = QTableWidgetItem(entry['path'])
            path_item.setToolTip(entry['path'])
            name.setToolTip(entry['name'])
            self.table.setItem(index, 1, path_item)
        self.table.blockSignals(False)
        self.empty.setVisible(not items)
        self.add_button.setEnabled(len(items) < 32 and not self.controller.busy)
        if items:
            index = next((i for i, entry in enumerate(items) if entry['id'] == selected),
                         max(0, min(row, len(items) - 1)))
            self.table.selectRow(index)
        self._selected()

    def _selected(self):
        entry = next((e for e in self.controller.items if e['id'] == self.current_id()), None)
        self.name.setText(entry['name'] if entry else '')
        self.path.setText(entry['path'] if entry else '')
        for widget in [self.name, self.rename_button, self.replace_button, self.remove_button]:
            widget.setEnabled(entry is not None)
        self._name_changed()
        self._busy_changed()

    def _busy_changed(self):
        self.add_button.setEnabled(len(self.controller.items) < 32 and not self.controller.busy)
        self.replace_button.setEnabled(bool(self.current_id()) and not self.controller.busy)

    def hideEvent(self, event):
        self.controller.cancelValidation()
        super().hideEvent(event)

    def _name_changed(self):
        if not hasattr(self, 'rename_button'):
            return
        entry = next((e for e in self.controller.items if e['id'] == self.current_id()), None)
        value = self.name.text().strip()
        self.rename_button.setEnabled(bool(entry and value and value != entry['name']))

    def _rename(self):
        if self.current_id() and self.rename_button.isEnabled():
            self.controller.rename(self.current_id(), self.name.text())

    def _message(self):
        from qt_dicom_viewer.ui.controller.appearance_controller import current_colors
        self.status.setText(self.controller.message)
        self.status.setVisible(bool(self.controller.message))
        colors = current_colors()
        self.status.setStyleSheet('color: ' + colors['dangerColor' if self.controller.isError else 'textSecondary'])


def show_favorite_directories(controller):
    owner = QGuiApplication.focusWindow()
    dialog = FavoriteDirectoriesDialog(controller)
    if owner is not None:
        dialog.winId()
        dialog.windowHandle().setTransientParent(owner)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
