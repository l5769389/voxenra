"""The real automatic-segmentation dialog follows import completion and errors."""
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.nrrd_exchange import write_nrrd
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, descendants, find


@pytest.fixture
def automatic_scene(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    window.resize(1280, 720)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Automatic segmentation', 'mpr')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    c = app.localSegmentationController
    app.settingsController.setValue('services', 'segmentationOrgans', ['liver'])
    c._checked_config = c._configuration()
    c._environment = {'model_ready': True, 'devices': ['cpu'], 'organs': ['liver', 'spleen']}
    c._environment_state = 'ready'
    job = SimpleNamespace(entered=Event(), release=Event(), failure=None)

    # Replace only the external inference runtime. Preparation, result parsing,
    # queued completion, mask import and QML rendering all use production code.
    def bridge(command, log, cancel, receive, **kwargs):
        root = Path(command[-1])
        assert command[-2] == 'run' and (root / 'source.nrrd').is_file()
        job.entered.set()
        receive({'event': 'stage', 'stage': 'running'})
        assert job.release.wait(5)
        if job.failure:
            log.write_text(job.failure)
            receive({'event': 'error', 'reason': job.failure})
            raise RuntimeError('Process exited with code 1')
        volume = c._target[2]
        mask = np.zeros(volume.modality_pixels.shape, dtype=np.uint8)
        mask[:, 36:60, 36:60] = 1
        write_nrrd(root / 'liver.nrrd', mask, volume.geometry.voxel_to_patient)
        (root / 'result.json').write_text(json.dumps({
            'protocol': 1, 'outputs': {'liver': 'liver.nrrd'}, 'version': 'synthetic',
            'model': 'synthetic', 'device': 'cpu',
        }))
        log.write_text('Synthetic inference completed')

    monkeypatch.setattr('qt_dicom_viewer.ui.controller.local_segmentation_controller.run_process', bridge)
    try:
        yield window, app, ws.activeTab, c, job, warnings
    finally:
        job.release.set()


def open_selection(window, app, locale):
    app.languageController.selectLanguage(locale)
    click(window, find(window, 'primaryTool-segmentation'))
    click(window, find(window, 'automaticSegmentationButton'))
    dialog = window.findChild(QObject, 'automaticSegmentationDialog')
    assert dialog is not None and dialog.property('visible')
    return dialog


def start_job(window, c, job, dialog):
    click(window, find(window, 'automaticSegmentationStart'))
    wait_until(job.entered.is_set)
    assert c.busy and dialog.property('visible')


def verify_result(window, tab, c, dialog, path):
    wait_until(lambda: c.state == 'done')
    assert len(tab.voiController.records) == 1
    assert tab.voiController.selectedId == tab.voiController.records[0]['id']
    wait_until(lambda: not dialog.property('visible'))
    assert find(window, 'automaticSegmentationStatus').property('text') == c.message
    wait_until(lambda: any(i.objectName() == 'mprSegmentationMask' and i.isVisible()
                          and i.property('maskReady') for i in descendants(window.contentItem())))
    assert tab.activeViewport.voiMasks
    assert window.grabWindow().save(str(path))


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_success_closes_selection_after_import_and_reveals_mask(automatic_scene, locale, tmp_path):
    window, app, tab, c, job, warnings = automatic_scene
    dialog = open_selection(window, app, locale)
    assert c.state == 'ready' and not tab.voiController.records
    start_job(window, c, job, dialog)
    job.release.set()
    verify_result(window, tab, c, dialog, tmp_path / ('success-' + locale + '.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_failure_preserves_selection_and_shows_reason_then_allows_retry(automatic_scene, locale, tmp_path):
    window, app, tab, c, job, warnings = automatic_scene
    job.failure = 'Cannot read model weights: <weights-file>'
    dialog = open_selection(window, app, locale)
    start_job(window, c, job, dialog)
    job.release.set()
    wait_until(lambda: c.state == 'error')
    assert dialog.property('visible') and not tab.voiController.records
    message = next(i for i in descendants(dialog.property('contentItem'))
                   if i.isVisible() and i.property('text') == c.message)
    assert job.failure in message.property('text')
    assert message.property('color').name() == app.appearanceController.colors['dangerColor']
    assert app.settingsController.section('services')['segmentationOrgans'] == ['liver']
    assert find(window, 'automaticSegmentationStart').isEnabled()
    assert find(window, 'automaticSegmentationDetails').isVisible()
    assert window.grabWindow().save(str(tmp_path / ('failure-' + locale + '.png')))
    job.failure = None
    job.entered.clear()
    job.release.clear()
    start_job(window, c, job, dialog)
    job.release.set()
    verify_result(window, tab, c, dialog, tmp_path / ('retry-' + locale + '.png'))
    assert not warnings, warnings


def test_deferred_import_keeps_dialog_open_then_closes_selection_and_logs(automatic_scene, tmp_path):
    window, app, tab, c, job, warnings = automatic_scene
    dialog = open_selection(window, app, 'zh-CN')
    start_job(window, c, job, dialog)
    # Another edit can temporarily block the captured target after inference starts.
    tab.voiController._draft = {'blocked_import': True}
    try:
        job.release.set()
        wait_until(lambda: c.state == 'pending' and c._pending is not None)
        assert dialog.property('visible') and not tab.voiController.records
        click(window, find(window, 'automaticSegmentationDetails'))
        details = window.findChild(QObject, 'automaticSegmentationLogDialog')
        assert details is not None and details.property('visible')
    finally:
        tab.voiController._draft = None
    c._poll_target()
    verify_result(window, tab, c, dialog, tmp_path / 'deferred-success.png')
    wait_until(lambda: not details.property('visible'))
    assert not warnings, warnings
