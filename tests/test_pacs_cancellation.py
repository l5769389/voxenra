"""Cancelled test workers cannot mutate a newer PACS operation."""
from threading import Event
import pytest
from PySide6.QtTest import QTest

from qt_dicom_viewer.pacs.client import PacsError
from test_pacs import controller, pacs_server
from test_dicom_tags import qt_app, wait_until


def test_cancel_finished_test_before_queued_callback(controller, pacs_server):
    controller.testDraft({'name': 'Old', 'url': pacs_server.url})
    assert controller._pool.waitForDone(2000)
    assert controller.busy
    controller.cancel()
    assert not controller.busy
    QTest.qWait(20)
    assert controller.draftTestResult['state'] == 'cancelled'


@pytest.mark.parametrize('late_error', [False, True])
def test_cancelled_test_cannot_override_new_query(controller, pacs_server, monkeypatch, late_error):
    entered, release = Event(), Event()
    def blocked(client):
        entered.set()
        assert release.wait(5)
        if late_error:
            raise PacsError('Old error')
        return 'Old success'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.pacs_controller.DicomWebClient.test_connection', blocked)
    assert controller.saveProfile({'name': 'PACS', 'url': pacs_server.url})
    try:
        controller.testProfile(controller.selectedProfileId)
        wait_until(entered.is_set)
        controller.cancel()
        assert controller.profiles[0]['testResult']['state'] == 'cancelled'
        controller.queryStudies({}, 20)
        wait_until(lambda: not controller.busy)
        message = controller.message
        assert len(controller.studies) == 1
        release.set()
        assert controller._pool.waitForDone(2000)
        QTest.qWait(20)
        assert controller.message == message and not controller.isError
        assert len(controller.studies) == 1
        assert controller.profiles[0]['testResult']['state'] == 'cancelled'
    finally:
        release.set()


def test_repeated_cancellations_remove_queued_jobs_and_bound_workers(controller, pacs_server, monkeypatch):
    entered = [Event(), Event()]
    release = Event()
    def blocked(client):
        entered[int(client.profile.name)].set()
        assert release.wait(5)
        return 'Old success'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.pacs_controller.DicomWebClient.test_connection', blocked)
    try:
        for index in range(2):
            controller.testDraft({'name': str(index), 'url': pacs_server.url})
            wait_until(entered[index].is_set)
            controller.cancel()
        for index in range(10):
            controller.testDraft({'name': 'queued', 'url': pacs_server.url})
            controller.cancel()
            assert not controller.busy
        assert controller._pool.activeThreadCount() == 2
        assert len(controller._jobs) == 2
        release.set()
        assert controller._pool.waitForDone(2000)
        QTest.qWait(20)
        assert not controller._jobs
        assert controller.draftTestResult['state'] == 'cancelled'
    finally:
        release.set()


def test_saving_retested_failed_draft_replaces_old_success(controller, pacs_server, monkeypatch):
    draft = {'name': 'PACS', 'url': pacs_server.url}
    controller.testDraft(draft)
    wait_until(lambda: not controller.busy)
    assert controller.saveProfile(draft)
    saved = controller.profiles[0]
    assert saved['testResult']['state'] == 'success'
    def failed(client):
        raise PacsError('Latest connection failure')
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.pacs_controller.DicomWebClient.test_connection', failed)
    controller.testDraft(saved)
    wait_until(lambda: not controller.busy)
    assert controller.saveProfile(saved)
    assert controller.profiles[0]['testResult'] == {'state': 'error', 'message': 'Latest connection failure'}
    assert controller.profiles[0]['status'] == '连接失败'
