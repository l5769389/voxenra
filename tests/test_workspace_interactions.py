"""Behavior regression tests for connection feedback, live controls and workspace navigation."""
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.pacs.client import DicomWebClient
from qt_dicom_viewer.settings.preferences import normalize_settings
from qt_dicom_viewer.ui.svg_icon_provider import NAMES, render_icon
from test_dicom_tags import qt_app, wait_until
from test_pacs import controller, pacs_server
from test_pacs_qml import scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, type_text, descendants

QML = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml'


def test_number_commit_and_reset_while_input_keeps_focus(scene):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('measurement')
    QTest.qWait(60)
    field = find(window, 'settingInput-measurement-lineWidth')
    slider = find(window, 'setting-measurement-lineWidth')
    type_text(window, field, '2.75')
    assert field.hasActiveFocus()
    assert slider.property('value') == 1.5
    assert app.settingsController.values['measurement']['lineWidth'] == 1.5
    QTest.keyClick(window, Qt.Key_Return)
    assert slider.property('value') == 2.75
    assert app.settingsController.values['measurement']['lineWidth'] == 2.75
    app.settingsController.resetSection('measurement')
    assert field.property('text') == '1.5'
    assert slider.property('value') == 1.5
    type_text(window, field, '')
    QTest.keyClick(window, Qt.Key_Escape)
    assert field.property('text') == '1.5'
    assert not warnings


def test_collapsible_groups_remember_category_switch_and_corner_focus(scene):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    settings = app.settingsController
    settings.selectCategory('corners')
    QTest.qWait(60)
    first = find(window, 'cornerSelect-topLeft')
    click(window, first)
    click(window, find(window, 'cornerPreview-topRight'))
    assert not first.property('checked') and not first.property('visualFocus')
    assert find(window, 'cornerSelect-topRight').property('checked')
    assert not any('CT · 轴位' in str(i.property('text') or '') for i in descendants(window.contentItem()))
    click(window, find(window, 'settingsGroup-corner-appearance'))
    assert not any(i.isVisible() and i.objectName() == 'setting-corners-enabled' for i in descendants(window.contentItem()))
    settings.selectCategory('scale'); QTest.qWait(30)
    settings.selectCategory('corners'); QTest.qWait(30)
    assert not any(i.isVisible() and i.objectName() == 'setting-corners-enabled' for i in descendants(window.contentItem()))
    click(window, find(window, 'settingsGroup-corner-appearance'))
    assert find(window, 'setting-corners-enabled').isVisible()
    assert not warnings


def test_connection_results_stay_with_profile_and_show_auth_error(controller, pacs_server):
    controller.saveProfile({'name': 'One', 'url': pacs_server.url})
    one = controller.profiles[0]['id']
    controller.testProfile(one)
    assert controller.profiles[0]['testResult']['state'] == 'testing'
    wait_until(lambda: not controller.busy)
    assert controller.profiles[0]['testResult']['state'] == 'success'
    controller.saveProfile({'name': 'Two', 'url': pacs_server.url})
    two = controller.profiles[1]['id']
    pacs_server.error_status = 401
    controller.testProfile(two)
    wait_until(lambda: not controller.busy)
    assert controller.profiles[0]['testResult']['state'] == 'success'
    assert '认证失败' in controller.profiles[1]['testResult']['message']
    controller.setSources(True, False)
    assert '认证失败' in controller.profiles[1]['testResult']['message']
    controller.testDraft({'name': 'Draft', 'url': 'invalid'})
    assert controller.draftTestResult['state'] == 'error'
    assert controller.profiles[0]['testResult']['state'] == 'success'
    controller.clearDraftTest()
    assert not controller.draftTestResult
    controller.saveProfile({**controller.profiles[1], 'url': pacs_server.url + '/changed'})
    assert not controller.profiles[1]['testResult']


def test_test_connection_timeout_cancel_and_stale_callback(controller, monkeypatch):
    class TimeoutOpener:
        def open(self, *args, **kwargs):
            raise TimeoutError()
    monkeypatch.setattr('qt_dicom_viewer.pacs.client.build_opener', lambda *args: TimeoutOpener())
    controller.testDraft({'name': 'Timeout', 'url': 'http://127.0.0.1/dicom-web'})
    wait_until(lambda: not controller.busy)
    assert '超时' in controller.draftTestResult['message']
    entered, release = Event(), Event()
    def blocked(client):
        entered.set()
        release.wait(3)
        return '连接成功'
    monkeypatch.setattr(DicomWebClient, 'test_connection', blocked)
    controller.testDraft({'name': 'Cancel', 'url': 'http://127.0.0.1/dicom-web'})
    wait_until(entered.is_set)
    try:
        controller._finished(controller._number - 1, None, 'stale')
        assert controller.draftTestResult['state'] == 'testing'
        controller.cancel()
    finally:
        release.set()
    wait_until(lambda: not controller.busy)
    assert controller.draftTestResult['state'] == 'cancelled'


@pytest.mark.parametrize('height', [720, 900])
def test_draft_feedback_fixed_beside_buttons_and_source_row(scene, height, tmp_path):
    window, app, warnings = scene
    window.resize(1280, height)
    app.workspaceController.openSettings()
    QTest.qWait(60)
    local, pacs = find(window, 'enableLocalSource'), find(window, 'enablePacsSource')
    assert local.mapToScene(QPointF()).y() == pytest.approx(pacs.mapToScene(QPointF()).y())
    click(window, find(window, 'pacsAddProfile'))
    click(window, find(window, 'pacsTestDraft'))
    message = find(window, 'pacsProfileMessage')
    assert message.isVisible() and message.property('text')
    pos = message.mapToScene(QPointF())
    assert 0 <= pos.y() < pos.y() + message.height() <= height
    assert message.mapToScene(QPointF()).y() < find(window, 'pacsTestDraft').mapToScene(QPointF()).y()
    assert window.grabWindow().save(str(tmp_path / f'connection-feedback-{height}.png'))
    assert not warnings


def test_calendar_selection_clear_and_invalid_date(scene, tmp_path):
    window, app, warnings = scene
    window.resize(1400, 900)
    app.pacsController.saveProfile({'name': 'Demo', 'url': 'http://127.0.0.1/dicom-web'})
    app.workspaceController.openPacs()
    QTest.qWait(60)
    wait_until(lambda: any(item.objectName() == "pacsDateFrom" and item.isVisible()
                           for item in descendants(window.contentItem())))
    field = find(window, 'pacsDateFrom')
    type_text(window, field, '2024-02-01')
    click(window, find(window, 'pacsDateFrom-calendar'))
    QTest.qWait(30)
    assert window.grabWindow().save(str(tmp_path / 'calendar-open.png'))
    click(window, find(window, 'pacsDateFrom-day-29'))
    assert field.property('text') == '2024-02-29'
    assert field.property('validDate')
    type_text(window, field, '2025-02-29')
    assert not field.property('validDate')
    click(window, find(window, 'pacsDateFrom-calendar'))
    click(window, find(window, 'pacsDateFrom-clear'))
    assert field.property('text') == '' and field.property('validDate')
    assert not warnings


def test_scale_presets_preserve_physical_length_and_fit(qt_app):
    assert normalize_settings({'scale': {'enabled': True}})['scale']['lengthMm'] == 100
    view = QQuickView()
    view.setInitialProperties({'pixelsPerMm': 2, 'calibrated': True, 'options': {'enabled': True, 'lengthMm': 100}})
    view.setSource(QUrl.fromLocalFile(str(QML / 'sections/center/viewportArea/ScaleBar.qml')))
    assert view.status() == QQuickView.Ready
    bar = view.rootObject()
    try:
        for width, expected in [(300, 20), (150, 10), (90, 10), (60, 5), (40, 2), (33, .5), (32, 0)]:
            bar.setWidth(width)
            assert bar.property('lengthMm') == expected
            assert bar.property('barPixels') == expected * 2
        bar.setWidth(300)
        bar.setProperty('options', {'enabled': True, 'lengthMm': 20})
        assert bar.property('lengthMm') == 20
        bar.setProperty('calibrated', False)
        assert bar.property('lengthMm') == 0
    finally:
        delete(view)


def test_mru_tab_close_keeps_last_used_open_tab(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Demo', TabType.TWO_D)
    image = ws.activeTabId
    ws.openSettings(); settings = ws.activeTabId
    ws.openPacs(); pacs = ws.activeTabId
    ws.activateTabId(image)
    ws.closeTab(image)
    assert ws.activeTabId == pacs
    ws.closeTab(settings)
    assert ws.activeTabId == pacs
    ws.openSettings()
    ws.closeTab(ws.activeTabId)
    assert ws.activeTabId == pacs
    ws.closeTab(pacs)
    assert not ws.activeTabId and not ws.tabs
    assert not ws._tab_mru
    assert not warnings


@pytest.mark.parametrize('dpr', [1, 1.25, 1.5, 2])
def test_svg_assets_have_transparency_tint_and_native_resolution(qt_app, dpr):
    for name in NAMES:
        frame = render_icon(name, '#45c9e9', '#5dc4c5', int(28 * dpr), int(28 * dpr))
        assert frame.width() == frame.height() == 28 * dpr
        assert frame.pixelColor(0, 0).alpha() == 0
        pixels = [frame.pixelColor(x, y) for x in range(frame.width()) for y in range(frame.height())]
        assert sum(c.alpha() > 128 and c.blue() > c.red() for c in pixels) > 12
        assert any(0 < c.alpha() < 255 for c in pixels), name


@pytest.mark.parametrize('width', [1000, 1400])
def test_profile_button_feedback_and_pacs_scroll_gutters(scene, pacs_server, width, tmp_path):
    window, app, warnings = scene
    window.resize(width, 600)
    pc = app.pacsController
    pc.saveProfile({'name': 'External test', 'url': pacs_server.url})
    identifier = pc.profiles[0]['id']
    app.workspaceController.openSettings()
    QTest.qWait(50)
    click(window, find(window, 'pacsTest-' + identifier))
    wait_until(lambda: not pc.busy)
    message = find(window, 'pacsTestResult-' + identifier)
    assert '连接成功' in message.property('text')
    bottom = message.mapToScene(QPointF(0, message.height())).y()
    assert bottom < window.height()
    assert window.grabWindow().save(str(tmp_path / f'profile-feedback-{width}.png'))
    app.workspaceController.openPacs()
    pc._studies = [dict(uid=str(i), patientName='Example', patientId='Demo', description='Synthetic study', date='2024-02-29', modality='CT', accession='123') for i in range(30)]
    pc._series = [dict(uid=str(i), modality='CT', number=str(i), description='Synthetic series', count=120, instances=120) for i in range(30)]
    pc.studiesChanged.emit(); pc.seriesChanged.emit()
    QTest.qWait(60)
    for name, prefix in [('pacsStudiesList', 'pacsStudy-'), ('pacsSeriesList', 'pacsSeries-')]:
        listing = find(window, name)
        scrollbar = next(i for i in descendants(listing) if i.objectName() == 'appScrollBar')
        assert scrollbar.isVisible()
        for item in descendants(listing):
            if item.isVisible() and item.objectName().startswith(prefix):
                right = item.mapToItem(listing, QPointF(item.width(), 0)).x()
                left = scrollbar.mapToItem(listing, QPointF()).x()
                assert right <= left - 3
    assert window.grabWindow().save(str(tmp_path / f'pacs-gutters-{width}.png'))
    assert not warnings, warnings
