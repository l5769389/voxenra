"""User-initiated feedback drafts; no network client or patient-data collection."""
import platform
from urllib.parse import urlencode, quote

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQuick import QQuickWindow

from qt_dicom_viewer import __version__
from qt_dicom_viewer.i18n import message

FEEDBACK_EMAIL = '5769389@qq.com'
ISSUE_URL = 'https://github.com/l5769389/voxenra/issues/new'


class FeedbackController(QObject):
    showDialog = Signal()
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._info = ''
        self._status = ''

    @Property(str, constant=True)
    def email(self):
        return FEEDBACK_EMAIL

    @Property(str, notify=changed)
    def systemInfo(self):
        return self._info

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Slot()
    def show(self):
        self.showDialog.emit()

    @Slot(QObject, str)
    def prepare(self, window, view_type):
        appearance = self._settings.section('appearance')
        system = platform.system()
        version = platform.mac_ver()[0] if system == 'Darwin' else platform.release()
        # Deliberate allowlist. No platform.node(), file paths, DICOM or logs.
        lines = [f'Version: {__version__}', f'OS: {"macOS" if system == "Darwin" else system} {version}',
                 f'Architecture: {platform.machine()}', f'Qt: {qVersion()}',
                 f'Language: {appearance.get("language", "")}',
                 f'Theme: {appearance.get("theme", "dark")}']
        if window is not None:
            lines.append(f'Display scale: {window.devicePixelRatio():g}')
        if isinstance(window, QQuickWindow):
            lines.append(f'Qt Quick backend: {window.rendererInterface().graphicsApi().name}')
        if view_type in ('2d', 'mpr', '3d', '4d', 'compare-2d', 'compare-mpr', 'montage', 'petct-fusion'):
            lines.append(f'View: {view_type}')
        self._info = '\n'.join(lines)
        self._status = ''
        self.changed.emit()

    def _body(self, kind, description, include_info):
        kind = message('feedback.suggestion' if kind == 'suggestion' else 'feedback.bug')
        body = f'{kind}\n\n{description.strip()}'
        if include_info:
            body += '\n\n---\n' + self._info
        return body

    def _copy(self, text):
        QGuiApplication.clipboard().setText(text)

    def _set_status(self, key):
        self._status = message(key)
        self.changed.emit()

    @Slot()
    def copyEmail(self):
        self._copy(FEEDBACK_EMAIL)
        self._set_status('feedback.emailCopied')

    @Slot(str, str, str, bool)
    def copyFeedback(self, title, kind, description, include_info):
        self._copy(title.strip() + '\n\n' + self._body(kind, description, include_info))
        self._set_status('feedback.copied')

    @Slot(str, str, str, str, bool)
    def openDraft(self, channel, title, kind, description, include_info):
        if channel not in ('github', 'email') or not title.strip():
            return
        title = title.strip()[:160]
        body = self._body(kind, description, include_info)
        mail = channel == 'email'
        base = 'mailto:' + FEEDBACK_EMAIL if mail else ISSUE_URL
        key = 'subject' if mail else 'title'
        query = {key: '[Voxenra] ' + title, 'body': body}
        url = base + '?' + urlencode(query, quote_via=quote)
        # URL handlers have different limits. Preserve full drafts via explicit
        # clipboard fallback instead of silently truncating user descriptions.
        copied = len(url) > (1800 if mail else 7500)
        if copied:
            self._copy(title + '\n\n' + body)
            query['body'] = message('feedback.pasteBody')
            url = base + '?' + urlencode(query, quote_via=quote)
        opened = QDesktopServices.openUrl(QUrl(url))
        self._set_status('feedback.openFailed' if not opened else
                         'feedback.pasteHint' if copied else 'feedback.draftOpened')
