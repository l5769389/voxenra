from copy import deepcopy
from dataclasses import replace

import pytest

from test_dicom_tags import qt_app, wait_until
from test_cpr_controller import draw
from test_workspace_persistence import populated_app
from qt_dicom_viewer.core.workspace_document import read_document, validate_document
from qt_dicom_viewer.core.workspace_state import dumps, loads
from qt_dicom_viewer.model.render_models import VolumeLoadResult


@pytest.fixture
def cpr_app(qt_app, tmp_path):
    app, record = populated_app(tmp_path, settings_path=tmp_path/'settings.json')
    app.workspaceDocumentController._autosave.stop()
    app.workspaceController.createTab(record.series_instance_uid, "CPR", "cpr")
    wait_until(lambda: app.workspaceController.activeTab.referencesReady)
    tab = app.workspaceController.activeTab
    draw(tab, ((20, 35), (45, 40), (65, 55)))
    yield app, tab, record
    app.shutdown()


def save(app, path):
    doc = app.workspaceDocumentController
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    assert not doc.isError, doc.message
    return read_document(path)


def test_v2_roundtrip_and_closed_path_retention_after_history_reset(cpr_app, tmp_path):
    app, tab, record = cpr_app
    path = tmp_path/'cpr.voxworkspace'
    session = tab.session_state()
    document = save(app, path)
    assert document['version'] == 2
    tab.historyController.reset()
    assert app.workspaceController.closeTab(tab.tab_config.tab_id)
    assert app.workspaceDocumentController.closedTabCount == 1
    document = save(app, path)
    cpr = next(t for t in document['tabs'] if t['type'] == 'cpr')
    assert cpr['closedId'] and cpr['edits']['cpr'] == session
    assert 'modality_pixels' not in dumps(cpr).decode()
    doc = app.workspaceDocumentController
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy, timeout=10000)
    assert not doc.isError, doc.message
    assert doc.reopenLastClosed()
    wait_until(lambda: not doc.busy, timeout=10000)
    assert not doc.isError, doc.message
    restored = app.workspaceController.activeTab
    wait_until(lambda: restored.ready)
    assert restored.session_state() == session


def test_version_one_migrates_without_mutating_input_and_invalid_cpr_is_rejected(cpr_app, tmp_path):
    app, _, _ = cpr_app
    document = save(app, tmp_path/'source.voxworkspace')
    old = deepcopy(document)
    old['tabs'] = [tab for tab in old['tabs'] if tab['type'] != 'cpr']
    old.update(version=1, activeTab=0)
    before = dumps(old)
    migrated = validate_document(old)
    assert migrated['version'] == 2 and dumps(old) == before
    bad = deepcopy(document)
    next(tab for tab in bad['tabs'] if tab['type'] == 'cpr')['edits']['cpr']['selected'] = 'missing'
    with pytest.raises(ValueError):
        validate_document(bad)


def test_restore_rejects_changed_pixels_but_accepts_cache_path_change(cpr_app):
    app, tab, _ = cpr_app
    state = tab.session_state()
    original = tab._volume
    tab._volume_request_id = 'reload'
    tab.handleRenderResult(VolumeLoadResult(response_id='reload',
        viewport_id=tab.viewForRole('reference-a').viewportId, series_uid=original.series_uid,
        volume=replace(original, fingerprint='different-file-path-and-mtime')))
    wait_until(lambda: not tab.busy)
    assert tab.ready
    assert tab.session_state()['source'] == state['source']
    tab._volume_request_id = 'changed'
    tab.handleRenderResult(VolumeLoadResult(response_id='changed',
        viewport_id=tab.viewForRole('reference-a').viewportId, series_uid=original.series_uid,
        volume=replace(original, modality_pixels=original.modality_pixels+100, fingerprint='changed')))
    wait_until(lambda: not tab.busy)
    assert not tab.ready
    assert tab.sourceMismatch
    assert tab.session_state()['paths'] == state['paths']
    tab.setParameter('angle', 20)
    wait_until(lambda: not tab.busy)
    assert not tab.ready and tab.sourceMismatch


def test_missing_source_keeps_cpr_records_when_other_sources_are_opened(cpr_app, tmp_path):
    app, tab, record = cpr_app
    saved = tmp_path/'missing.voxworkspace'
    before = tab.session_state()
    save(app, saved)
    moved = tmp_path/'moved'
    moved.mkdir()
    for instance in record.instances:
        instance.path.rename(moved/instance.path.name)
    doc = app.workspaceDocumentController
    assert doc.restore_from(saved)
    wait_until(lambda: not doc.busy)
    assert doc.hasMissingSources
    doc.skipMissing()
    wait_until(lambda: not doc.busy, timeout=10000)
    assert doc.closedTabCount == 1
    retained = save(app, tmp_path/'retained.voxworkspace')
    cpr = next(t for t in retained['tabs'] if t['type'] == 'cpr')
    assert cpr['edits']['cpr'] == before
    assert retained['series'][0]['sources']


def test_centerline_intervals_belong_to_each_path(cpr_app):
    _, tab, _ = cpr_app
    first = tab.selectedPathId
    tab.setParameter('rangeEnd', 10)
    tab.setParameter('rangeStart', 2)
    draw(tab, ((20, 65), (45, 70), (65, 75)))
    second = tab.selectedPathId
    tab.setParameter('rangeEnd', 8)
    tab.selectPath(first)
    assert tab.parameters['rangeStart'] == 2 and tab.parameters['rangeEnd'] == 10
    tab.selectPath(second)
    assert tab.parameters['rangeStart'] == 0 and tab.parameters['rangeEnd'] == 8
