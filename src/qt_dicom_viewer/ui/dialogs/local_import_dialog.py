"""One mixed file/directory picker; Qt's native file modes cannot express both."""
from qt_dicom_viewer.i18n import message as _msg, localize

from pathlib import Path
import os
import queue
import threading

from PySide6.QtCore import QEvent, QDir, QFileInfo, QFileSystemWatcher, QTimer, QAbstractTableModel, QLocale, QModelIndex, QItemSelectionModel, QSignalBlocker, QStandardPaths, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QTableView, QVBoxLayout, QApplication, QStyle, QListWidget, QListWidgetItem, QListView
from qt_dicom_viewer.i18n.widgets import QDialog, QLabel, QLineEdit, QPushButton


def apply_import_dialog_theme(widget):
    from qt_dicom_viewer.ui.controller.appearance_controller import current_colors
    colors = current_colors()
    style = """
        QDialog { background: @panelBackground; color: @textPrimary; }
        QLabel { color: @textSecondary; }
        QLineEdit, QTableView { background: @controlBackground; color: @textPrimary;
            border: 1px solid @inputBorder; border-radius: 4px; padding: 5px; }
        QLineEdit:focus, QTableView:focus { border-color: @focusBorder; }
        QTableView::item { height: 28px; }
        QTableView::item:selected { background: @selectionBackground; color: @textPrimary; }
        QListWidget#importFavorites { background: transparent; border: none; }
        QListWidget#importFavorites::item { background: @controlBackground; color: @textPrimary;
            border: 1px solid @controlBorder; border-radius: 4px; padding: 3px 25px 3px 3px; }
        QListWidget#importFavorites::item:hover { background: @controlHover; }
        QListWidget#importFavorites::item:selected { background: @selectionBackground; border-color: @focusBorder; }
        QHeaderView { background: @panelBackgroundStrong; }
        QHeaderView::section { background: @panelBackgroundStrong; color: @textSecondary;
            padding: 6px; border: none; }
        QPushButton { background: @controlBackground; color: @textPrimary; padding: 7px 12px;
            border: 1px solid @controlBorder; border-radius: 4px; }
        QPushButton:hover { background: @controlHover; border-color: @controlHoverBorder; }
        QPushButton:pressed { background: @controlPressed; }
        QPushButton:focus { border-color: @focusBorder; }
        QPushButton:disabled { color: @textDisabled; }
        QPushButton#importManageFavorites { background: transparent; border-color: transparent; padding: 4px 6px; }
        QPushButton#importManageFavorites:hover { background: @controlHover; }
        QPushButton#importFavoriteRemove { background: transparent; border: none; padding: 0; font-size: 16px; }
        QPushButton#importFavoriteRemove:hover { background: @controlHover; }
        QPushButton#importFavoriteRemove:focus { border: 1px solid @focusBorder; }
        QPushButton#importOpen { background: @primaryButtonBackground; color: @textOnPrimary; border-color: @primaryButtonBorder; }
        QPushButton#importOpen:hover { background: @primaryButtonHover; }
        QPushButton#importOpen:pressed { background: @primaryButtonPressed; }
        QPushButton#importOpen:disabled { background: @primaryButtonDisabled; color: @textDisabled; }
    """
    for key in sorted(colors, key=len, reverse=True): style = style.replace('@' + key, colors[key])
    widget.setStyleSheet(style)


class ImportFileModel(QAbstractTableModel):
    """Flat, lazy directory metadata; never change a tree's root index.

    A model reset invalidates old accessible cells before publishing new rows.
    File metadata is read only when shown or used for sorting, not at import.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._files = []
        self._rows = {}

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < 4:
            return localize((_msg('text.0528'), _msg('text.0529'), _msg('text.0165'), _msg('text.0530'))[section])
        return super().headerData(section, orientation, role)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._files)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._files):
            return None
        info = self._files[index.row()]
        column = index.column()
        if role == Qt.DecorationRole and column == 0:
            return QApplication.style().standardIcon(QStyle.SP_DirIcon if info.isDir() else QStyle.SP_FileIcon)
        if role == Qt.DisplayRole:
            if column == 0:
                return info.fileName() or info.absoluteFilePath()
            if column == 1:
                return "" if info.isDir() else QLocale().formattedDataSize(info.size())
            if column == 2:
                return localize(_msg('text.0531')) if info.isDir() else info.suffix().upper()
            if column == 3:
                return info.lastModified().toString('yyyy-MM-dd HH:mm')
        return None

    def set_files(self, files):
        self.beginResetModel()
        self._files = files
        self._rows = {QDir.toNativeSeparators(info.absoluteFilePath()): row for row, info in enumerate(files)}
        self.endResetModel()

    def sort(self, column, order=Qt.AscendingOrder):
        if not 0 <= column < 4:
            return
        keys = (lambda f: f.fileName().casefold(), lambda f: f.size(),
                lambda f: (f.isDir(), f.suffix().casefold()),
                lambda f: f.lastModified().toMSecsSinceEpoch())
        self.layoutAboutToBeChanged.emit()
        # Selection models create their persistent indexes in this signal.
        old = self.persistentIndexList()
        locations = [(self.filePath(i), i.column()) for i in old]
        self._files.sort(key=keys[column], reverse=order == Qt.DescendingOrder)
        self._rows = {QDir.toNativeSeparators(info.absoluteFilePath()): row for row, info in enumerate(self._files)}
        self.changePersistentIndexList(old, [self.index(self._rows[path], col) for path, col in locations])
        self.layoutChanged.emit()

    def index(self, row, column=0, parent=QModelIndex()):
        if isinstance(row, str):
            row = self._rows.get(QDir.toNativeSeparators(QFileInfo(row).absoluteFilePath()), -1)
        return super().index(row, column, parent)

    def filePath(self, index):
        return QDir.toNativeSeparators(self._files[index.row()].absoluteFilePath()) if index.isValid() and 0 <= index.row() < len(self._files) else ""

    def isDir(self, index):
        return self._files[index.row()].isDir() if index.isValid() and 0 <= index.row() < len(self._files) else False


class LocalImportDialog(QDialog):
    def __init__(self, directory="", parent=None, *, favorites=None):
        super().__init__(parent)
        self.setObjectName("localImportDialog")
        self.setWindowTitle(_msg('text.0532'))
        self.resize(880, 560)
        self.setMinimumSize(620, 400)
        self.paths = []
        self._favorites = favorites
        self._favorite_position_timer = QTimer(self)
        self._favorite_position_timer.setSingleShot(True)
        self._favorite_position_timer.timeout.connect(self._position_favorite_remove)
        self._directory = ""
        self._navigation_directory = ""
        self._favorite_request = -1
        self._favorite_path = ""
        self._navigation_id = 0
        self._accept_navigation = 0
        self._loading = False
        self._directory_results = queue.SimpleQueue()
        self._directory_timer = QTimer(self)
        self._directory_timer.setInterval(20)
        self._directory_timer.timeout.connect(self._finish_navigation)
        self._directory_feedback = QTimer(self)
        self._directory_feedback.setSingleShot(True)
        self._directory_feedback.setInterval(300)
        self._directory_feedback.timeout.connect(self._show_directory_feedback)
        self._apply_theme()
        from qt_dicom_viewer.ui.controller import appearance_controller
        appearance = appearance_controller._current() if appearance_controller._current else None
        if appearance is not None: appearance.changed.connect(self._apply_theme)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._apply_theme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        # The native dialog caption owns the only close control on every platform.
        heading = QLabel(_msg('text.0533'))
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)
        location = QHBoxLayout()
        for title, navigate in (
            (_msg('text.0534'), self.up),
            (_msg('text.0535'), lambda: self.navigate(str(Path.home()))),
            (_msg('text.0536'), lambda: self.navigate("")),
        ):
            button = QPushButton(title)
            button.setAutoDefault(False)
            button.clicked.connect(navigate)
            location.addWidget(button)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("importPath")
        self.path_edit.setPlaceholderText(_msg('text.0537'))
        self.path_edit.installEventFilter(self)
        location.addWidget(self.path_edit, 1)
        self.favorite_button = QPushButton(_msg('favorites.addCurrent'))
        self.favorite_button.setObjectName("importFavoriteCurrent")
        self.favorite_button.setAutoDefault(False)
        self.favorite_button.setVisible(favorites is not None)
        self.favorite_button.clicked.connect(self._favorite_current)
        location.addWidget(self.favorite_button)
        self.path_edit.textChanged.connect(self._update_favorite_button)
        if favorites is not None:
            favorites.changed.connect(self._update_favorite_button)
            favorites.busyChanged.connect(self._update_favorite_button)
        layout.addLayout(location)
        self.favorites_header = QHBoxLayout()
        self.favorites_label = QLabel(_msg('favorites.menu'))
        self.favorites_header.addWidget(self.favorites_label)
        self.favorites_header.addStretch(1)
        self.manage_favorites = QPushButton(_msg('favorites.manage'))
        self.manage_favorites.setObjectName('importManageFavorites')
        self.manage_favorites.setAutoDefault(False)
        self.manage_favorites.clicked.connect(lambda: self._favorites.showManager())
        self.favorites_header.addWidget(self.manage_favorites)
        layout.addLayout(self.favorites_header)
        self.favorite_list = QListWidget()
        self.favorite_list.setObjectName('importFavorites')
        self.favorite_list.setViewMode(QListView.ListMode)
        self.favorite_list.setFlow(QListView.LeftToRight)
        self.favorite_list.setWrapping(True)
        self.favorite_list.setResizeMode(QListView.Adjust)
        self.favorite_list.setMovement(QListView.Static)
        self.favorite_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.favorite_list.setTextElideMode(Qt.ElideRight)
        self.favorite_list.setWordWrap(False)
        self.favorite_list.setGridSize(QSize(164, 36))
        self.favorite_list.setIconSize(QSize(16, 16))
        self.favorite_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.favorite_list.itemClicked.connect(self._open_favorite)
        self.favorite_list.installEventFilter(self)
        self.favorite_remove = QPushButton("×", self.favorite_list.viewport())
        self.favorite_remove.setObjectName('importFavoriteRemove')
        self.favorite_remove.setAutoDefault(False)
        self.favorite_remove.setToolTip(_msg('favorites.remove'))
        self.favorite_remove.setAccessibleName(localize(_msg('favorites.remove')))
        self.favorite_remove.setFixedSize(22, 22)
        self.favorite_remove.hide()
        self.favorite_remove.clicked.connect(self._remove_active_favorite)
        self.favorite_list.itemSelectionChanged.connect(self._position_favorite_remove)
        self.favorite_list.verticalScrollBar().valueChanged.connect(self._position_favorite_remove)
        self.favorite_list.viewport().installEventFilter(self)
        layout.addWidget(self.favorite_list)
        if favorites is not None:
            favorites.changed.connect(self._refresh_favorites)
        self._refresh_favorites()
        hint = QLabel(
            _msg('text.0538')
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.model = ImportFileModel(self)
        self._watcher = QFileSystemWatcher(self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._watcher.directoryChanged.connect(lambda _: self._refresh_timer.start(150))
        self._refresh_timer.timeout.connect(self._refresh_directory)
        self.view = QTableView()
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(28)
        self.view.setShowGrid(False)
        self.view.setObjectName("importFileList")
        self.view.setModel(self.model)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.AscendingOrder)
        self.view.setColumnWidth(0, 420)
        self.view.doubleClicked.connect(self.open_item)
        self.view.selectionModel().selectionChanged.connect(self.update_selection)
        layout.addWidget(self.view, 1)
        self.selection_label = QLabel()
        self.selection_label.setMinimumHeight(self.selection_label.fontMetrics().height())
        self.selection_label.setObjectName("importSelectionSummary")
        if favorites is not None:
            favorites.messageChanged.connect(self._favorite_feedback)
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.selection_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = QPushButton(_msg('text.0539'))
        self.cancel_button.setObjectName("importCancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setMinimumWidth(80)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.open_button = QPushButton(_msg('text.0544'))
        self.open_button.setObjectName("importOpen")
        self.open_button.setMinimumWidth(144)
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self.accept)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        initial = (
            directory
            or QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            or str(Path.home())
        )
        self.navigate(initial)

    def _refresh_favorites(self):
        scroll = self.favorite_list.verticalScrollBar().value()
        current = self.favorite_list.currentItem()
        focused_path = current.data(Qt.UserRole) if current else None
        self.favorite_list.clear()
        entries = self._favorites.items if self._favorites is not None else []
        icon = QApplication.style().standardIcon(QStyle.SP_DirIcon)
        for entry in entries:
            label = entry['name']
            if sum(other['name'] == label for other in entries) > 1:
                label += ' · ' + Path(entry['path']).parent.name
            item = QListWidgetItem(icon, label)
            item.setData(Qt.UserRole, entry['path'])
            item.setData(Qt.UserRole + 1, entry['id'])
            item.setToolTip(entry['path'])
            item.setSizeHint(QSize(156, 30))
            self.favorite_list.addItem(item)
            if entry['path'] == focused_path:
                self.favorite_list.setCurrentItem(item)
        self.favorites_label.setVisible(bool(entries))
        self.manage_favorites.setVisible(bool(entries))
        self.favorite_list.setVisible(bool(entries))
        self._size_favorites()
        self._update_favorite_button()
        self.favorite_list.doItemsLayout()
        self.favorite_list.verticalScrollBar().setValue(scroll)
        self._position_favorite_remove()

    def _position_favorite_remove(self, *_):
        selected = self.favorite_list.selectedItems()
        if not selected:
            self.favorite_remove.hide()
            return
        rect = self.favorite_list.visualItemRect(selected[0])
        self.favorite_remove.move(rect.right() - self.favorite_remove.width() - 2, rect.top() + 2)
        self.favorite_remove.setVisible(self.favorite_list.viewport().rect().intersects(rect))
        self.favorite_remove.raise_()

    def _remove_active_favorite(self):
        selected = self.favorite_list.selectedItems()
        if not selected or self._favorites is None:
            return
        identifier = selected[0].data(Qt.UserRole + 1)
        if not self._favorites.remove(identifier):
            self.selection_label.setText(self._favorites.message)
        else:
            self.update_selection()

    def _size_favorites(self):
        available = max(1, self.width() - 48)
        columns = max(1, available // 160)
        cell_width = available // columns
        rows = min(2, (self.favorite_list.count() + columns - 1) // columns)
        self.favorite_list.setGridSize(QSize(cell_width, 36))
        for index in range(self.favorite_list.count()):
            self.favorite_list.item(index).setSizeHint(QSize(cell_width - 8, 30))
        self.favorite_list.setFixedHeight(rows * 36 if rows else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'favorite_list'):
            self._size_favorites()
            self._favorite_position_timer.start(0)

    def hideEvent(self, event):
        self._favorite_position_timer.stop()
        if self._favorites is not None:
            self._favorites.cancelValidation()
        super().hideEvent(event)

    def _open_favorite(self, item):
        # The existing asynchronous navigator handles unavailable/offline paths.
        target = item.data(Qt.UserRole)
        # Clicking the folder already being shown must not clear file selection.
        if not self._loading and target == self._directory:
            return
        if self._loading and self._favorite_request == self._navigation_id and target == self._favorite_path:
            return
        self.navigate(target, typed=True)
        self._favorite_request = self._navigation_id
        self._favorite_path = target

    def _apply_theme(self, *_):
        apply_import_dialog_theme(self)

    def _update_favorite_button(self):
        key = os.path.normcase(os.path.normpath(self._directory))
        saved = self._favorites is not None and any(
            os.path.normcase(os.path.normpath(item['path'])) == key for item in self._favorites.items)
        busy = self._favorites is not None and self._favorites.busy
        self.favorite_button.setText(_msg('favorites.checking' if busy else 'favorites.saved' if saved else 'favorites.addCurrent'))
        if hasattr(self, 'favorite_list'):
            # Keep the requested folder highlighted throughout asynchronous loading.
            # Updating the address or resetting file rows must not select the old folder.
            active = self._navigation_directory if self._loading else self._directory
            active_key = os.path.normcase(os.path.normpath(active))
            with QSignalBlocker(self.favorite_list):
                for index in range(self.favorite_list.count()):
                    item = self.favorite_list.item(index)
                    item.setSelected(os.path.normcase(os.path.normpath(item.data(Qt.UserRole))) == active_key)
            self._position_favorite_remove()
        displayed_key = os.path.normcase(os.path.normpath(self.path_edit.text()))
        self.favorite_button.setEnabled(bool(self._directory) and displayed_key == key
                                       and not self._loading and not saved and not busy)

    def _favorite_current(self):
        if self._favorites is None or not self.favorite_button.isEnabled():
            return
        self._favorites.requestAdd(self._directory)
        self._update_favorite_button()
        if self._favorites.message:
            self.selection_label.setText(self._favorites.message)

    def _favorite_feedback(self):
        if self._favorites.message:
            self.selection_label.setText(self._favorites.message)
        else:
            self.update_selection()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ApplicationPaletteChange:
            self._apply_theme()
        if event.type() == QEvent.LanguageChange and hasattr(self, 'model'):
            self.favorite_remove.setAccessibleName(localize(_msg('favorites.remove')))
            self.model.headerDataChanged.emit(Qt.Horizontal, 0, 3)
            self.view.viewport().update()

    def eventFilter(self, watched, event):
        if (hasattr(self, 'favorite_remove') and watched is self.favorite_list.viewport()
                and event.type() in (QEvent.Resize, QEvent.Show)):
            self._favorite_position_timer.start(0)
        if (watched is getattr(self, 'favorite_list', None)
                and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space)):
            item = self.favorite_list.currentItem()
            if item is not None:
                self._open_favorite(item)
            return True
        if (
            watched is self.path_edit
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        ):
            self.open_typed_path()
            return True
        return super().eventFilter(watched, event)

    def selected_paths(self):
        return [
            self.model.filePath(index)
            for index in self.view.selectionModel().selectedRows(0)
        ]

    def navigate(self, directory, *, typed=False, restore_selection=(), accept_after=False):
        self._navigation_id += 1
        request = self._navigation_id
        self._accept_navigation = request if accept_after else 0
        results = self._directory_results
        self._navigation_directory = directory
        self._loading = True
        self._update_favorite_button()
        self.path_edit.setText(directory)
        self.path_edit.setEnabled(not accept_after)
        self.view.setEnabled(False)
        self.open_button.setEnabled(False)
        self.selection_label.clear()
        self._directory_feedback.start()
        self._directory_timer.start()

        # Filesystem access may wait on a network mount or OS consent. Keep it
        # outside both the GUI thread and Qt's shutdown-waited thread pool.
        # Only the queue is captured: closing the dialog cannot access deleted Qt objects.
        def read_directory():
            try:
                path = Path(directory).expanduser() if directory else None
                selected = list(restore_selection)
                if typed and path.is_file():
                    # Match the canonical directory used by model rows even
                    # when the user entered a directory symlink.
                    selected = [str(path.parent.resolve() / path.name)]
                    path = path.parent
                target = str(path.resolve()) if path is not None else ""
                if target:
                    with os.scandir(target) as entries:
                        files = [QFileInfo(entry.path) for entry in entries if not entry.name.startswith('.')]
                    # An explicitly typed hidden file is still a valid source.
                    if typed and selected and Path(selected[0]).name.startswith('.'):
                        files.append(QFileInfo(selected[0]))
                else:
                    files = QDir.drives()
                for info in files:
                    info.isDir()
                    info.size()
                    info.lastModified()
                results.put((request, target, files, selected, False))
            except (OSError, ValueError):
                results.put((request, directory, [], [], True))

        threading.Thread(target=read_directory, daemon=True, name="import-directory").start()

    def _show_directory_feedback(self):
        if self._loading and self.isVisible():
            self.selection_label.setText(_msg('import.readingDirectory'))

    def _finish_navigation(self):
        while not self._directory_results.empty():
            request, target, files, selected, error = self._directory_results.get()
            if request != self._navigation_id:
                continue
            self._loading = False
            self._directory_feedback.stop()
            accept_after = self._accept_navigation == request
            self._accept_navigation = 0
            self._directory_timer.stop()
            self.path_edit.setEnabled(True)
            self.view.setEnabled(True)
            if error:
                if not accept_after:
                    self.path_edit.setText(self._directory)
                self.update_selection()
                self.selection_label.setText(
                    _msg('favorites.unavailable', path=self._favorite_path)
                    if request == self._favorite_request else _msg('import.directoryUnavailable'))
                continue
            self._directory = target
            self.model.set_files(files)
            if self._watcher.directories() != ([target] if target else []):
                if self._watcher.directories():
                    self._watcher.removePaths(self._watcher.directories())
                if target:
                    self._watcher.addPath(target)
            self.view.sortByColumn(self.view.horizontalHeader().sortIndicatorSection(),
                                   self.view.horizontalHeader().sortIndicatorOrder())
            self.view.setColumnWidth(0, 420)
            self.path_edit.setText(target)
            for path in selected:
                index = self.model.index(path)
                if index.isValid():
                    self.view.selectionModel().select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                    self.view.scrollTo(index)
            self.update_selection()
            if accept_after:
                if selected and set(self.selected_paths()) != set(selected):
                    self.path_edit.setText(selected[0])
                    self.selection_label.setText(_msg('text.0545'))
                    continue
                self.accept()

    def _refresh_directory(self):
        if self.isVisible() and not self._loading:
            self.navigate(self._directory, restore_selection=self.selected_paths())

    def up(self):
        if self._directory:
            parent = str(Path(self._directory).parent)
            self.navigate("" if parent == self._directory else parent)

    def open_typed_path(self):
        self.navigate(self.path_edit.text(), typed=True)

    def open_item(self, index):
        if self.model.isDir(index):
            self.navigate(self.model.filePath(index))
        else:
            self.accept()

    def update_selection(self, *_):
        self._update_favorite_button()
        if self._loading:
            return
        paths = self.selected_paths()
        directories = sum(Path(path).is_dir() for path in paths)
        self.selection_label.setText(
            _msg('text.0541', value1=directories, value2=len(paths) - directories)
            if paths
            else _msg('text.0542')
        )
        self.open_button.setText(_msg('text.0543') if paths else _msg('text.0544'))
        self.open_button.setEnabled(bool(paths or self._directory))

    def accept(self):
        if self._loading:
            return
        if self.path_edit.text() != self._directory:
            self.navigate(self.path_edit.text(), typed=True, accept_after=True)
            return
        paths = self.selected_paths() or ([self._directory] if self._directory else [])
        if not paths or not all(Path(path).exists() for path in paths):
            self.selection_label.setText(_msg('text.0545'))
            return
        self.paths = paths
        super().accept()

    def reject(self):
        self._directory_feedback.stop()
        self._accept_navigation = 0
        super().reject()


def select_import_paths(directory="", favorites=None):
    from qt_dicom_viewer.settings.dialog_locations import current_locations
    history = current_locations()
    if history is not None:
        directory = history.directory("images", directory)
    owner = QGuiApplication.focusWindow()
    dialog = LocalImportDialog(directory, favorites=favorites) if favorites is not None else LocalImportDialog(directory)
    if owner is not None:
        dialog.winId()
        dialog.windowHandle().setTransientParent(owner)
    try:
        paths = dialog.paths if dialog.exec() == QDialog.Accepted else []
        if paths and history is not None:
            history.remember("images", paths[0], directory=Path(paths[0]).is_dir())
        return paths
    finally:
        dialog.deleteLater()
