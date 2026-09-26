"""User-initiated feedback drafts; no network client or patient-data collection."""
import platform
import sys
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode, quote

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, qVersion, QSaveFile, QIODevice
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQuick import QQuickWindow

from qt_dicom_viewer import __version__
from qt_dicom_viewer.i18n import message

FEEDBACK_EMAIL = '5769389@qq.com'
from qt_dicom_viewer.i18n.widgets import QFileDialog
from qt_dicom_viewer.infrastructure.feedback_mail import (
    validate_attachments, email_bytes, MacMailComposer, windows_compose)

ISSUE_URL = 'https://github.com/l5769389/voxenra/issues/new'


class FeedbackController(QObject):
    showDialog = Signal()
    attachmentsChanged = Signal()
    mailFinished = Signal(str)
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._info = ''
        self._status = ''
        self._attachments = []
        self._reviewed = False
        self._busy = False
        self._mac_mail = None
        self.mailFinished.connect(self._mail_finished)

    @Property(list, notify=attachmentsChanged)
    def attachments(self):
        result = []
        for path in self._attachments:
            try:
                size = path.stat().st_size if path.is_file() else -1
            except OSError:
                size = -1
            result.append(dict(name=path.name, size=size))
        return result

    @Property(bool, notify=attachmentsChanged)
    def attachmentsReviewed(self):
        return self._reviewed

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Slot(bool)
    def setAttachmentsReviewed(self, value):
        self._reviewed = value
        self.attachmentsChanged.emit()

    @Slot()
    def chooseAttachments(self):
        if self._busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(None, message('feedback.chooseAttachments'), '',
            message('feedback.fileFilter'))
        if paths:
            self.add_attachments(paths)

    def add_attachments(self, paths):
        try:
            selected = validate_attachments([*self._attachments, *paths])
        except (OSError, ValueError) as exc:
            self._attachment_error(exc)
            return
        self._attachments = selected
        self._reviewed = False
        self._status = ''
        self.attachmentsChanged.emit()
        self.changed.emit()

    @Slot(int)
    def removeAttachment(self, index):
        if not self._busy and 0 <= index < len(self._attachments):
            del self._attachments[index]
            self._reviewed = False
            self.attachmentsChanged.emit()

    def _attachment_error(self, exc):
        self._set_status('feedback.attachmentLimit' if str(exc) == 'feedback.attachmentLimit'
                         else 'feedback.attachmentInvalid')

    def _checked_attachments(self):
        if not self._reviewed:
            self._set_status('feedback.reviewRequired')
            return None
        try:
            return validate_attachments(self._attachments)
        except (OSError, ValueError) as exc:
            self._attachment_error(exc)
            return None

    @Slot(str, str, str, bool)
    def saveEmail(self, title, kind, description, include_info):
        if self._busy or not title.strip() or not self._attachments:
            return
        paths = self._checked_attachments()
        if paths is None:
            return
        filename, _ = QFileDialog.getSaveFileName(None, message('feedback.saveEmail'),
            'Voxenra-feedback.eml', 'Email (*.eml)')
        if not filename:
            return
        if Path(filename).resolve() in paths:
            self._set_status('feedback.saveFailed')
            return
        try:
            payload = email_bytes(FEEDBACK_EMAIL, '[Voxenra] ' + title[:160],
                                  self._body(kind, description, include_info), paths)
            file = QSaveFile(filename)
            if not file.open(QIODevice.WriteOnly) or file.write(payload) != len(payload) or not file.commit():
                raise OSError('write failed')
        except (OSError, ValueError):
            self._set_status('feedback.saveFailed')
            return
        self._set_status('feedback.savedEmail')

    def _compose_attachments(self, title, body):
        paths = self._checked_attachments()
        if paths is None:
            return
        if sys.platform == 'darwin' and QGuiApplication.platformName() == 'cocoa':
            try:
                if self._mac_mail is None:
                    self._mac_mail = MacMailComposer()
                opened = self._mac_mail.compose(FEEDBACK_EMAIL, title, body, paths)
            except (OSError, AttributeError, ValueError):
                opened = False
            self._set_status('feedback.attachmentDraft' if opened else 'feedback.mailUnavailable')
        elif sys.platform == 'win32':
            self._busy = True
            self._set_status('feedback.mailBusy')
            def run():
                try:
                    result = windows_compose(FEEDBACK_EMAIL, title, body, paths)
                except (OSError, AttributeError, ValueError):
                    result = 'unavailable'
                try:
                    self.mailFinished.emit(result)
                except RuntimeError:
                    pass  # Application closed while the system composer was open.
            Thread(target=run, daemon=True).start()
        else:
            self._set_status('feedback.mailUnavailable')

    @Slot(str)
    def _mail_finished(self, result):
        self._busy = False
        self._set_status('feedback.mailCancelled' if result == 'cancelled' else
                         'feedback.mailReturned' if result == 'done' else 'feedback.mailUnavailable')

    def shutdown(self):
        if self._mac_mail is not None:
            self._mac_mail.close()

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
        if self._busy or channel not in ('github', 'email') or (channel == 'email' and not title.strip()):
            return
        title = title.strip()[:160]
        body = self._body(kind, description, include_info)
        mail = channel == 'email'
        if mail and self._attachments:
            self._compose_attachments('[Voxenra] ' + title, body)
            return
        base = 'mailto:' + FEEDBACK_EMAIL if mail else ISSUE_URL
        key = 'subject' if mail else 'title'
        query = {'body': body} if title or description.strip() else {}
        if title:
            query[key] = '[Voxenra] ' + title
        url = base + ('?' + urlencode(query, quote_via=quote) if query else '')
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
