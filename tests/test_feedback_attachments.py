import ctypes
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QGuiApplication

from qt_dicom_viewer.infrastructure.feedback_mail import (
    email_bytes, validate_attachments, MAX_ATTACHMENT_BYTES,
    MapiMessage, windows_compose)
from qt_dicom_viewer.ui.controller.feedback_controller import FeedbackController, FEEDBACK_EMAIL
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app


def make_files(tmp_path):
    files = [tmp_path / '截图 & 图像.png', tmp_path / '匿名样本.dcm']
    files[0].write_bytes(b'\x89PNG\r\n\x1a\nexample')
    files[1].write_bytes(bytes(128) + b'DICM\0example')
    return files


def test_mime_preserves_all_attachment_bytes_names_and_unicode(tmp_path):
    files = make_files(tmp_path)
    data = email_bytes(FEEDBACK_EMAIL, '测试 & subject', '正文\nsecond line', files)
    mail = BytesParser(policy=policy.default).parsebytes(data)
    assert str(mail['To']) == FEEDBACK_EMAIL and str(mail['Subject']) == '测试 & subject'
    assert mail['X-Unsent'] == '1'
    assert '正文' in mail.get_body().get_content()
    parts = list(mail.iter_attachments())
    assert [p.get_filename() for p in parts] == [p.name for p in files]
    assert [p.get_payload(decode=True) for p in parts] == [p.read_bytes() for p in files]
    assert [p.get_content_type() for p in parts] == ['image/png', 'application/dicom']
    assert str(tmp_path).encode() not in data


def test_validation_deduplicates_and_rejects_directory_missing_or_large(tmp_path):
    files = make_files(tmp_path)
    assert validate_attachments(files + files) == files
    with pytest.raises(ValueError):
        validate_attachments([tmp_path])
    with pytest.raises(OSError):
        validate_attachments([tmp_path / 'missing'])
    big = tmp_path / 'large.zip'
    with big.open('wb') as f:
        f.truncate(MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(ValueError, match='attachmentLimit'):
        validate_attachments([big])


@pytest.mark.parametrize('return_code,expected', [(0, 'done'), (1, 'cancelled'), (2, 'unavailable')])
def test_windows_unicode_api_always_requires_user_composer(tmp_path, return_code, expected):
    files = make_files(tmp_path)
    calls = []
    def send(session, parent, pointer, flags, reserved):
        msg = ctypes.cast(pointer, ctypes.POINTER(MapiMessage)).contents
        assert flags & 0x8  # Never silently send a fully populated message.
        assert flags & 0x40000
        assert msg.subject == '中文主题' and msg.body == '正文'
        assert msg.recipients[0].address == 'SMTP:' + FEEDBACK_EMAIL
        assert [msg.files[i].path for i in range(msg.fileCount)] == [str(p) for p in files]
        calls.append(True)
        return return_code
    assert windows_compose(FEEDBACK_EMAIL, '中文主题', '正文', files,
                           library=SimpleNamespace(MAPISendMailW=send)) == expected
    assert calls


def test_attachment_review_missing_files_and_atomic_export(qt_app, tmp_path, monkeypatch):
    controller = FeedbackController(SettingsController(path=False))
    controller.prepare(None, '')
    files = make_files(tmp_path)
    controller.add_attachments([str(p) for p in files])
    assert len(controller.attachments) == 2 and not controller.attachmentsReviewed
    controller.openDraft('email', 'Title', 'bug', 'Body', True)
    assert controller._checked_attachments() is None
    controller.setAttachmentsReviewed(True)
    target = tmp_path / 'report.eml'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.feedback_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(target), ''))
    controller.saveEmail('Title', 'bug', 'Body', True)
    mail = BytesParser(policy=policy.default).parsebytes(target.read_bytes())
    assert len(list(mail.iter_attachments())) == 2
    assert 'Version:' in mail.get_body().get_content()
    previous = target.read_bytes()
    files[1].unlink()
    controller.saveEmail('Title', 'bug', 'Body', True)
    assert target.read_bytes() == previous
    controller.removeAttachment(1)
    assert not controller.attachmentsReviewed
    controller.add_attachments([str(tmp_path / 'missing')])
    assert len(controller.attachments) == 1
    controller.shutdown()


def test_native_email_receives_full_body_and_files_but_github_does_not(qt_app, tmp_path, monkeypatch):
    controller = FeedbackController(SettingsController(path=False))
    files = make_files(tmp_path)
    controller.add_attachments(files)
    controller.setAttachmentsReviewed(True)
    calls = []
    monkeypatch.setattr(controller, '_compose_attachments', lambda title, body: calls.append((title, body)))
    controller.openDraft('email', 'Title', 'bug', 'x' * 20000, False)
    assert 'x' * 20000 in calls[0][1]
    urls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.feedback_controller.QDesktopServices.openUrl',
                        lambda url: urls.append(url.toString()) or True)
    controller.openDraft('github', 'Title', 'bug', 'Body', False)
    assert str(tmp_path) not in urls[0] and files[0].name not in urls[0]


def test_mac_native_service_prepares_items_without_sending(qt_app, tmp_path):
    import sys
    if sys.platform != 'darwin' or QGuiApplication.platformName() != 'cocoa':
        pytest.skip('Requires native macOS AppKit')
    from qt_dicom_viewer.infrastructure.feedback_mail import MacMailComposer
    composer = MacMailComposer()
    calls = []
    original = composer.call
    def intercept(obj, selector, *args, **kwargs):
        if selector == 'performWithItems:':
            calls.append(selector)  # Do not open Mail or send anything in a test.
            return None
        return original(obj, selector, *args, **kwargs)
    composer.call = intercept
    try:
        result = composer.compose(FEEDBACK_EMAIL, 'Synthetic attachment test', 'Test only', make_files(tmp_path))
        assert calls == (['performWithItems:'] if result else [])
        assert bool(composer._retained) == result
    finally:
        composer.close()
    assert not composer._retained
