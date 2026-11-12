"""Frozen encoded screenshot: the preview and saved bytes are identical."""
import base64
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot, QBuffer, QIODevice
from PySide6.QtGui import QImage
from voxplane.core.workspace_state import atomic_write
from voxplane.i18n.widgets import QFileDialog
from voxplane.i18n import message as _msg
from voxplane.ui.file_location import reveal_path


class ScreenshotPreviewController(QObject):
    changed = Signal()
    saved = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear()

    @Property(bool, notify=changed)
    def ready(self): return bool(self._data)
    @Property(str, notify=changed)
    def source(self): return self._source
    @Property(str, notify=changed)
    def dimensions(self): return self._dimensions
    @Property(str, notify=changed)
    def error(self): return self._error

    @Slot()
    def clear(self):
        self._data = b''
        self._source = self._dimensions = self._error = self._path = ''
        self._options = {}
        self.changed.emit()

    def set_image(self, image, options, path):
        self.clear()
        buffer = QBuffer(); buffer.open(QIODevice.WriteOnly)
        fmt = options['format']
        if not image.save(buffer, fmt.upper(), options['jpegQuality'] if fmt == 'jpeg' else -1):
            raise ValueError('Cannot encode screenshot')
        self._data = bytes(buffer.data())
        self._options = dict(options)
        self._path = str(path)
        self._source = 'data:image/'+fmt+';base64,'+base64.b64encode(self._data).decode('ascii')
        self._dimensions = f'{image.width()} × {image.height()} px · {fmt.upper()}'
        self.changed.emit()

    def save_to(self, path):
        if not self.ready: return False
        try:
            atomic_write(Path(path), self._data)
            self.saved.emit(str(Path(path).resolve()))
            return True
        except OSError as exc:
            self._error = str(exc); self.changed.emit()
            return False

    @Slot(result=bool)
    def save(self):
        if not self.ready: return False
        extension = 'jpg' if self._options['format'] == 'jpeg' else 'png'
        path, _ = QFileDialog.getSaveFileName(None, _msg('screenshot.export'), self._path,
                                             'JPEG (*.jpg *.jpeg)' if extension == 'jpg' else 'PNG (*.png)')
        if not path: return False
        if not Path(path).suffix: path += '.'+extension
        saved = self.save_to(path)
        if saved and self._options['revealAfter']: reveal_path(Path(path))
        return saved
