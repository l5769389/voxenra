"""Feedback routing is explicit, previewable and excludes clinical context."""
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtGui import QGuiApplication
from qt_dicom_viewer.ui.controller.feedback_controller import FeedbackController, FEEDBACK_EMAIL
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app


@pytest.fixture
def feedback(qt_app, monkeypatch):
    controller = FeedbackController(SettingsController(path=False))
    controller.prepare(None, '2d')
    urls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.feedback_controller.QDesktopServices.openUrl',
                        lambda url: urls.append(url.toString()) or True)
    yield controller, urls
    QGuiApplication.clipboard().clear()


def test_drafts_are_encoded_and_info_is_optional(feedback):
    c, urls = feedback
    assert FEEDBACK_EMAIL == '5769389@qq.com'
    assert 'Version:' in c.systemInfo and 'OS:' in c.systemInfo
    assert 'View: 2d' in c.systemInfo
    title = '图像 & 窗口 #问题'
    description = '操作一\nExpected: a+b? & # / 中文'
    for channel in ('github', 'email'):
        c.openDraft(channel, title, 'bug', description, True)
        url = urlsplit(urls[-1]); query = parse_qs(url.query)
        assert query['subject' if channel == 'email' else 'title'] == ['[Voxenra] ' + title]
        assert description in query['body'][0] and c.systemInfo in query['body'][0]
        assert (url.scheme, url.path if channel == 'email' else url.netloc) == (
            ('mailto', FEEDBACK_EMAIL) if channel == 'email' else ('https', 'github.com'))
    c.openDraft('github', title, 'suggestion', description, False)
    assert 'Version:' not in parse_qs(urlsplit(urls[-1]).query)['body'][0]
    count = len(urls)
    c.openDraft('email', ' ', 'bug', description, True)
    c.openDraft('arbitrary', title, 'bug', description, True)
    assert len(urls) == count


@pytest.mark.parametrize('channel', ['github', 'email'])
def test_long_draft_copies_complete_text_instead_of_truncating(feedback, channel):
    c, urls = feedback
    text = '长描述 &\n' * 2000
    c.openDraft(channel, 'Issue', 'bug', text, True)
    assert len(urls[-1]) < 1800
    assert text.strip() in QGuiApplication.clipboard().text()
    assert c.systemInfo in QGuiApplication.clipboard().text()
    assert c.status


def test_copy_and_failed_launch_do_not_claim_submission(feedback, monkeypatch):
    c, urls = feedback
    c.copyFeedback('Title', 'bug', 'Description', False)
    assert 'Description' in QGuiApplication.clipboard().text()
    assert 'Version:' not in QGuiApplication.clipboard().text()
    c.copyEmail()
    assert QGuiApplication.clipboard().text() == FEEDBACK_EMAIL
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.feedback_controller.QDesktopServices.openUrl', lambda url: False)
    c.openDraft('email', 'Title', 'bug', 'Description', True)
    from qt_dicom_viewer.i18n import message
    assert c.status == message('feedback.openFailed')


def test_collection_ignores_unknown_view_and_does_not_read_patient_or_host(feedback, monkeypatch):
    c, _ = feedback
    monkeypatch.setattr('platform.node', lambda: pytest.fail('Hostname must not be collected'))
    c.prepare(None, '/private/patient/name')
    assert 'View:' not in c.systemInfo and '/private' not in c.systemInfo


def test_github_accepts_empty_draft_and_untitled_description(feedback):
    c, urls = feedback
    c.openDraft('github', ' ', 'bug', ' ', True)
    assert urls[-1] == 'https://github.com/l5769389/voxenra/issues/new'
    c.openDraft('github', '', 'bug', 'Steps to reproduce', True)
    query = parse_qs(urlsplit(urls[-1]).query)
    assert 'title' not in query
    assert 'Steps to reproduce' in query['body'][0] and c.systemInfo in query['body'][0]


def test_feedback_icon_is_registered_and_distinct(qt_app):
    from qt_dicom_viewer.ui.svg_icon_provider import NAMES, render_icon
    assert 'feedback' in NAMES
    feedback = render_icon('feedback', '#aabcc8', 'transparent', 32, 32)
    assert not feedback.isNull()
    assert feedback != render_icon('help', '#aabcc8', 'transparent', 32, 32)
