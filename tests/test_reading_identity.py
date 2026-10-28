"""Source identity stays readable without changing workspace or DICOM keys."""
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPointF
from PySide6.QtTest import QTest

from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import phantom_series, sidebar_scene
from test_tab_windows import detached, open_tabs
from test_tag_qml import find, descendants
from test_workspace_persistence import populated_app, draw_length


@pytest.fixture
def identity_app(qt_app, tmp_path):
    first = phantom_series(tmp_path, 1, 'SAME-PATIENT', '1.2.3.1', '20260903')
    second = phantom_series(tmp_path, 2, 'SAME-PATIENT', '1.2.3.2', '20260822')
    records = [replace(record, patient_name='Patient with a very long name', series_number=7,
                       series_description='Original T1 MPRAGE with contrast and fat suppression')
               for record in (first, second)]
    app = AppController(DicomImageProvider(), settings_path=False)
    app.languageController.selectLanguage('en-US')
    app.workspaceDocumentController._autosave.stop()
    snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records)
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    try:
        yield app, records
    finally:
        app.shutdown()


def test_tabs_derive_full_source_identity_without_changing_keys(identity_app):
    app, records = identity_app
    tabs = open_tabs(app, records)
    rows = app.workspaceController.tabs
    assert [r['tabId'] for r in rows] == [tab.tab_config.tab_id for tab in tabs]
    assert rows[0]['tabLabel'] != rows[1]['tabLabel']
    for row, record, tab in zip(rows, records, tabs):
        assert record.patient_name in row['tabLabel']
        assert record.series_description in row['tabLabel']
        assert record.patient_name in row['tabPrimary'] and record.series_description in row['tabPrimary']
        assert 'Series 7' in row['tabSecondary']
        assert record.series_description in row['tabTooltip']
        assert record.patient_id in row['tabTooltip']
        assert tab.tab_config.tab_label == 'Synthetic CT'
        assert tab.tab_config.series_metas[0].series_uid == record.series_instance_uid
    assert '2026/09/03' in rows[0]['tabSecondary']
    assert '2026/08/22' in rows[1]['tabSecondary']
    assert tabs[0].activeViewport.overlayInfo['studyDate'] == '2026/09/03'


def test_missing_values_and_duplicate_identity_have_stable_source_distinction(identity_app):
    app, records = identity_app
    records = [replace(r, study_date='', series_number=None, series_description='') for r in records]
    app._series_catalog.replace(DicomFolderScanSnapshot(Path('.'), 6, 6, 0, records))
    tabs = open_tabs(app, records)
    rows = app.workspaceController.tabs
    assert rows[0]['tabLabel'] != rows[1]['tabLabel']
    assert '[No study date]' in rows[0]['tabLabel']
    assert '[No series number]' in rows[0]['tabLabel']
    assert '[No description]' in rows[0]['tabLabel']
    assert '[No study date]' in rows[0]['tabTooltip']
    before = {row['tabId']: row for row in rows}
    session = app.windowManager.mainWorkspace
    session.moveTab(tabs[0].tab_config.tab_id, 1)
    assert {row['tabId']: row for row in app.workspaceController.tabs} == before
    app.workspaceController.closeTab(tabs[1].tab_config.tab_id)
    assert app.workspaceController.tabs[0] == before[tabs[0].tab_config.tab_id]


def test_comparison_lists_each_source_and_privacy_hides_all_new_identity(identity_app):
    app, records = identity_app
    ws = app.workspaceController
    ws.createCompareTab(*(r.series_instance_uid for r in records))
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    row = ws.tabs[0]
    assert '2026/09/03' in row['tabTooltip'] and '2026/08/22' in row['tabTooltip']
    assert row['tabTooltip'].count('Original T1 MPRAGE') == 2
    notifications = []
    session = app.windowManager.mainWorkspace
    _ = session.tabs
    session._i18n_tabs.connect(lambda: notifications.append(True))
    ws.activeViewport.setViewportSetting('hide-sensitive-info', True)
    QTest.qWait(20)
    private = session.tabs[0]
    for field in ('tabLabel', 'tabPrimary', 'tabSecondary', 'tabTooltip', 'tabPatient', 'tabDescription'):
        assert 'Patient with' not in private[field]
        assert 'Original T1' not in private[field]
        assert 'SAME-PATIENT' not in private[field]
        assert '2026/' not in private[field]
    assert notifications


def test_retired_window_disconnects_identity_notifications(identity_app, monkeypatch):
    import sys
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    from qt_dicom_viewer.ui.controller.window_workspace_controller import WindowWorkspaceController
    app, _ = identity_app
    session = WindowWorkspaceController(app.windowManager, 'retired-test')
    notifications, errors = [], []
    session._i18n_tabs.connect(lambda: notifications.append(True))
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    app.workspaceController.tabPresentationChanged.emit()
    assert notifications
    session.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(session)
    app.workspaceController.tabPresentationChanged.emit()
    assert not errors


def test_identity_rederived_after_retention_and_file_restore(qt_app, tmp_path):
    app, record = populated_app(tmp_path)
    app.languageController.selectLanguage('en-US')
    ws, doc = app.workspaceController, app.workspaceDocumentController
    doc._autosave.stop()
    try:
        original = ws.tabs[0]
        assert '2026/09/03' in original['tabLabel']
        draw_length(ws.activeViewport)
        ws.activeViewport.setViewportSetting('hide-sensitive-info', True)
        assert ws.closeTab(ws.activeTabId)
        assert doc.reopenLastClosed()
        wait_until(lambda: not doc.busy)
        assert '2026/09/03' not in ws.tabs[0]['tabTooltip']
        ws.activeViewport.setViewportSetting('hide-sensitive-info', False)
        assert ws.tabs[0] == original
        path = tmp_path / 'identity.voxworkspace'
        assert doc.save_to(path)
        wait_until(lambda: not doc.busy)
        assert doc.restore_from(path)
        wait_until(lambda: not doc.busy)
        assert not doc.isError, doc.message
        assert ws.tabs[0]['tabLabel'] == original['tabLabel']
        assert ws.tabs[0]['tabTooltip'] == original['tabTooltip']
    finally:
        app.shutdown()


def test_visible_tab_dates_full_tooltip_detach_and_privacy(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage('en-US')
    records = [replace(r, patient_name='Patient with a very long name', series_number=7,
                       series_description='Original T1 MPRAGE with contrast and fat suppression')
               for r in records[:2]]
    app._series_catalog.update(DicomFolderScanSnapshot(Path('.'), 6, 6, 0, records))
    tabs = open_tabs(app, records)
    for tab, date in zip(tabs, ('2026/09/03', '2026/08/22')):
        key = tab.tab_config.tab_id
        secondary = find(window, 'tabSecondary-' + key)
        assert date in secondary.property('text')
        assert not secondary.property('truncated')
        label = find(window, 'tabPrimary-' + key)
        assert records[0].series_description in label.property('text')
        assert label.width() > 50
        patient = find(window, 'tabPatient-' + key)
        assert patient.property('text') == records[0].patient_name
        assert patient.width() > 30
        button = find(window, 'workspaceTab-' + key)
        QTest.mouseMove(window, button.mapToScene(QPointF(40, 15)).toPoint())
        wait_until(lambda: button.findChild(QObject, 'tabTooltip-' + key).property('visible'))
        tooltip = button.findChild(QObject, 'tabTooltip-' + key)
        assert records[0].series_description in tooltip.property('text')
        assert 'Patient with a very long name' in tooltip.property('text')
    artifact = Path('build/reading-controls/identity-tabs.png')
    artifact.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(artifact))
    QTest.mouseMove(window, QPointF(window.width() / 2, window.height() / 2).toPoint())
    QTest.qWait(40)
    assert window.grabWindow().save(str(artifact.with_name('identity-dates.png')))
    session, other = detached(app, tabs[0])
    assert session.tabs[0]['tabTooltip'] == next(row['tabTooltip'] for row in app.workspaceController.tabs if row['tabId'] == tabs[0].tab_config.tab_id)
    key = tabs[0].tab_config.tab_id
    tabs[0].activeViewport.setViewportSetting('hide-sensitive-info', True)
    QTest.qWait(40)
    assert not any(item.isVisible() and '2026/' in item.property('text')
                   for item in descendants(other.contentItem()) if item.objectName() == 'tabSecondary-' + key)
    assert records[0].series_description not in find(other, 'tabPrimary-' + key).property('text')
    assert records[0].series_description not in find(other, 'workspaceTab-' + key).findChild(QObject, 'tabTooltip-' + key).property('text')
    assert not warnings, warnings


def test_legacy_default_date_migration_preserves_custom_layout_and_explicit_removal(qt_app, tmp_path):
    import json
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    from qt_dicom_viewer.settings.preferences import normalize_settings
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps({'schemaVersion': 1, 'corners': {'topRight': ['patientName', 'patientId']}}))
    settings = SettingsController(path=path)
    assert settings.section('corners')['topRight'] == ['patientName', 'patientId', 'studyDate']
    assert settings.removeCornerField('topRight', 2)
    assert SettingsController(path=path).section('corners')['topRight'] == ['patientName', 'patientId']
    custom = normalize_settings({'schemaVersion': 1, 'corners': {'topRight': ['patientId', 'zoom']}})
    assert custom['corners']['topRight'] == ['patientId', 'zoom']


def test_overlay_shows_study_date_and_ww_before_wl_with_privacy(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    tab = open_tabs(app, records[:1])[0]
    top = find(window, 'overlay-topRight')
    assert 'Study date: 2026/09/03' in top.property('text')
    bottom = find(window, 'overlay-bottomLeft').property('text')
    assert bottom.index('WW:') < bottom.index('WL:')
    tab.activeViewport.setViewportSetting('hide-sensitive-info', True)
    assert '2026/09/03' not in top.property('text')
    assert not warnings, warnings


@pytest.mark.parametrize('raw', ['20260230', '20261301', '2026', 'not-a-date'])
def test_invalid_study_date_is_not_presented_as_a_calendar_date(identity_app, raw):
    app, records = identity_app
    record = replace(records[0], study_date=raw)
    app._series_catalog.replace(DicomFolderScanSnapshot(Path('.'), 3, 3, 0, [record]))
    tab = open_tabs(app, [record])[0]
    row = app.workspaceController.tabs[0]
    assert '[Invalid study date]' in row['tabSecondary']
    assert raw in row['tabTooltip']
    assert tab.activeViewport.overlayInfo['studyDate'] == '--'


def test_added_2d_source_updates_label_and_its_privacy(identity_app):
    app, records = identity_app
    tab = open_tabs(app, records[:1])[0]
    layout = tab.twoDLayout
    layout.setLayout('1x2')
    assert layout.loadSeries(1, records[1].series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    row = app.windowManager.mainWorkspace.tabs[0]
    assert '2026/09/03' in row['tabTooltip'] and '2026/08/22' in row['tabTooltip']
    tab.activeViewport.setViewportSetting('hide-sensitive-info', True)
    QTest.qWait(10)
    assert '2026/' not in app.windowManager.mainWorkspace.tabs[0]['tabTooltip']


from test_pet_fusion import paired_series


def test_fusion_overlay_distinguishes_source_dates_and_ct_window_order(sidebar_scene, paired_series):
    window, app, _, warnings = sidebar_scene
    _, ct, pet = paired_series
    ct, pet = replace(ct, study_date='20261001'), replace(pet, study_date='20261002')
    app._series_catalog.update(DicomFolderScanSnapshot(Path('.'), 6, 6, 0, [ct, pet]))
    ws = app.workspaceController
    ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    def overlay():
        return next((item for item in descendants(window.contentItem())
                     if item.objectName() == 'viewportMetadataOverlay'
                     and item.property('viewportController') is not None
                     and item.property('viewportController').viewportRole == 'fusion'), None)
    wait_until(lambda: overlay() is not None)
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    item = overlay()
    def field(key):
        return QQmlExpression(QQmlEngine.contextForObject(item), item, 'field("' + key + '")').evaluate()[0]
    assert 'CT study date: 2026/10/01' in field('studyDate')
    assert 'PET study date: 2026/10/02' in field('studyDate')
    assert field('window').index('CT WW:') < field('window').index('WL:')
    item.property('viewportController').setViewportSetting('hide-sensitive-info', True)
    assert field('studyDate') == ''
    assert not warnings, warnings


def test_tooltip_retains_source_study_time_precision(identity_app):
    app, records = identity_app
    record = replace(records[0], study_time='093012.125')
    app._series_catalog.replace(DicomFolderScanSnapshot(Path('.'), 3, 3, 0, [record]))
    open_tabs(app, [record])
    assert 'Study time: 09:30:12.125' in app.workspaceController.tabs[0]['tabTooltip']


def test_same_visible_identity_different_patient_ids_remains_distinguishable(identity_app):
    app, records = identity_app
    records = [replace(record, study_date='20260903', patient_id='PATIENT-' + str(index))
               for index, record in enumerate(records)]
    app._series_catalog.replace(DicomFolderScanSnapshot(Path('.'), 6, 6, 0, records))
    open_tabs(app, records)
    rows = app.workspaceController.tabs
    assert rows[0]['tabPrimary'] != rows[1]['tabPrimary']
    assert 'PATIENT-0' in rows[0]['tabTooltip']
    assert 'PATIENT-1' in rows[1]['tabTooltip']


def test_malformed_partial_study_time_remains_literal():
    from qt_dicom_viewer.ui.reading_identity import format_study_time
    assert format_study_time('0912.5') == '0912.5'
