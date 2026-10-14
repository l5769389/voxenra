"""Rendered regression checks for scoped feedback and cancellable PACS drafts."""
from threading import Event

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.pacs.client import PacsError
from test_pacs_qml import scene
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, type_text, descendants
from test_local_segmentation_completion_qml import automatic_scene, open_selection, start_job, verify_result


def test_saved_corrected_pacs_replaces_rendered_failure(scene, monkeypatch, tmp_path):
    window, app, warnings = scene
    pacs = app.pacsController
    app.workspaceController.openDataSources()
    assert pacs.saveProfile({'name': 'Synthetic', 'url': 'http://127.0.0.1:8042/wrong'})
    profile_id = pacs.profiles[0]['id']
    def fail(self):
        raise PacsError('Old endpoint failure')
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.pacs_controller.DicomWebClient.test_connection', fail)
    pacs.testProfile(profile_id)
    wait_until(lambda: not pacs.busy)
    assert pacs.profiles[0]['testResult']['state'] == 'error'
    click(window, find(window, 'pacsEdit-' + profile_id))
    type_text(window, find(window, 'pacsProfileUrl'), 'http://127.0.0.1:8042/corrected')
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.pacs_controller.DicomWebClient.test_connection', lambda self: 'New endpoint success')
    click(window, find(window, 'pacsTestDraft'))
    wait_until(lambda: not pacs.busy)
    click(window, find(window, 'pacsSaveProfile'))
    QTest.qWait(50)
    assert pacs.profiles[0]['testResult'] == {'state': 'success', 'message': 'New endpoint success'}
    feedback = find(window, 'pacsTestResult-' + profile_id)
    assert feedback.isVisible() and feedback.property('text') == 'New endpoint success'
    assert feedback.property('color').name() == app.appearanceController.colors['successColor']
    assert window.grabWindow().save(str(tmp_path / 'pacs-corrected.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('failure', [None, 'Cannot read model weights'])
def test_segmentation_feedback_only_on_target_tab(automatic_scene, failure, tmp_path):
    window, app, tab, c, job, warnings = automatic_scene
    job.failure = failure
    dialog = open_selection(window, app, 'zh-CN')
    start_job(window, c, job, dialog)
    job.release.set()
    wait_until(lambda: c.state == ('error' if failure else 'done'))
    if failure:
        dialog.close()
    else:
        verify_result(window, tab, c, dialog, tmp_path / 'segmentation-target.png')
    # A phase switch within the same tab must also hide terminal feedback.
    tab.voiController.set_phase(1)
    QTest.qWait(30)
    assert not any(item.objectName() == 'automaticSegmentationStatus' and item.isVisible()
                   for item in descendants(window.contentItem()))
    tab.voiController.set_phase(None)
    QTest.qWait(30)
    assert find(window, 'automaticSegmentationStatus').isVisible()
    ws = app.workspaceController
    uid = next(uid for uid in app._series_catalog.snapshot() if uid != c._target[2].series_uid)
    ws.createTab(uid, 'Different CT', 'mpr')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    assert ws.activeTab is not tab and not ws.activeTab.voiController.records
    click(window, find(window, 'primaryTool-segmentation'))
    QTest.qWait(50)
    assert not any(item.objectName() == 'automaticSegmentationStatus' and item.isVisible()
                   for item in descendants(window.contentItem()))
    assert window.grabWindow().save(str(tmp_path / 'segmentation-other.png'))
    ws.activateTabId(tab.tab_config.tab_id)
    QTest.qWait(50)
    assert find(window, 'automaticSegmentationStatus').property('text') == c.message
    assert not warnings, warnings


@pytest.mark.parametrize('dismiss', ['cancel', 'close', 'escape'])
def test_draft_test_can_close_and_late_result_cannot_overwrite_retry(scene, monkeypatch, dismiss, tmp_path):
    window, app, warnings = scene
    pacs = app.pacsController
    entered, release = Event(), Event()
    def delayed(client):
        if client.profile.name == 'Old':
            entered.set()
            assert release.wait(10)
            return 'Old success'
        return 'New success'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.pacs_controller.DicomWebClient.test_connection', delayed)
    app.workspaceController.openDataSources()
    click(window, find(window, 'pacsAddProfile'))
    type_text(window, find(window, 'pacsProfileName'), 'Old')
    type_text(window, find(window, 'pacsProfileUrl'), 'http://127.0.0.1:8042')
    dialog = window.findChild(QObject, 'pacsProfileDialog')
    try:
        click(window, find(window, 'pacsTestDraft'))
        wait_until(entered.is_set)
        old_cancel = pacs._cancel
        if dismiss == 'escape':
            QTest.keyClick(window, Qt.Key_Escape)
        else:
            button = find(window, 'pacsCancelProfile' if dismiss == 'cancel' else 'pacsProfileDialogClose')
            assert button.isEnabled()
            click(window, button)
        QTest.qWait(50)
        assert not dialog.property('visible') and not pacs.busy
        assert old_cancel.is_set()
        click(window, find(window, 'pacsAddProfile'))
        type_text(window, find(window, 'pacsProfileName'), 'New')
        type_text(window, find(window, 'pacsProfileUrl'), 'http://127.0.0.1:8042/new')
        click(window, find(window, 'pacsTestDraft'))
        wait_until(lambda: not pacs.busy, 2000)
        assert pacs.draftTestResult == {'state': 'success', 'message': 'New success'}
        release.set()
        assert pacs._pool.waitForDone(2000)
        QTest.qWait(50)
        assert pacs.draftTestResult == {'state': 'success', 'message': 'New success'}
        assert find(window, 'pacsProfileMessage').property('text') == 'New success'
        assert window.grabWindow().save(str(tmp_path / ('pacs-retry-' + dismiss + '.png')))
    finally:
        release.set()
    assert not warnings, warnings
