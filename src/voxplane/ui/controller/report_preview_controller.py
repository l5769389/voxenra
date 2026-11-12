"""Own one frozen PDF and its raster preview; saving never recaptures results."""
from pathlib import Path
from tempfile import TemporaryDirectory
from shiboken6 import delete
from PySide6.QtCore import QObject, Property, Signal, Slot, QSize, QUrl
from PySide6.QtPdf import QPdfDocument
from PySide6.QtGui import QImage, QPainter, QColor
from voxplane.core.workspace_state import atomic_write
from voxplane.i18n.widgets import QFileDialog
from voxplane.i18n import message as _msg
from voxplane.i18n.messages import localize


class ReportPreviewController(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._suggested_path = ''
        self._data = b''
        self._temporary = None
        self._pages = []
        self._error = ''

    @Property('QStringList', notify=changed)
    def pages(self): return list(self._pages)

    @Property(bool, notify=changed)
    def ready(self): return bool(self._data)

    @Property(str, notify=changed)
    def error(self): return self._error

    @Slot()
    def clear(self):
        self._suggested_path = ''
        self._data = b''
        self._pages = []
        if self._temporary:
            self._temporary.cleanup()
            self._temporary = None
        self._error = ''
        self.changed.emit()

    def set_pdf(self, data, *, suggested_path=None):
        self.clear()
        self._suggested_path = str(suggested_path or localize(_msg('text.0396', value1='pdf')))
        document = QPdfDocument(self)
        try:
            try:
                self._temporary = TemporaryDirectory(prefix='report-preview-')
                directory = Path(self._temporary.name)
                pdf = directory/'frozen.pdf'
                pdf.write_bytes(data)
                if document.load(str(pdf)) != QPdfDocument.Error.None_:
                    raise ValueError('Cannot render PDF preview')
                for page in range(document.pageCount()):
                    size = document.pagePointSize(page)
                    target = QSize(round(size.width()*1.5), round(size.height()*1.5))
                    image = document.render(page, target)
                    if not image.isNull():
                        opaque = QImage(image.size(), QImage.Format_RGB32)
                        opaque.fill(QColor('white'))
                        painter = QPainter(opaque)
                        painter.drawImage(0, 0, image)
                        painter.end()
                        image = opaque
                    path = directory/f'page-{page}.png'
                    if image.isNull() or not image.save(str(path)):
                        raise ValueError('Cannot render PDF preview')
                    self._pages.append(QUrl.fromLocalFile(str(path)).toString())
            finally:
                # QPdfDocument can retain the file handle until destruction on
                # Windows. Release it before cleanup or a reentrant changed slot.
                document.close()
                delete(document)
            self._data = bytes(data)
            self.changed.emit()
            return True
        except Exception as exc:
            self.clear()
            self._error = str(exc)
            self.changed.emit()
            return False

    def save_to(self, path):
        if not self._data: return False
        try:
            atomic_write(Path(path), self._data)
            return True
        except OSError as exc:
            self._error = str(exc)
            self.changed.emit()
            return False

    @Slot(result=bool)
    def save(self):
        if not self.ready: return False
        path, _ = QFileDialog.getSaveFileName(None, _msg('text.0395'), self._suggested_path, 'PDF (*.pdf)')
        return bool(path) and self.save_to(path if path.lower().endswith('.pdf') else path+'.pdf')
