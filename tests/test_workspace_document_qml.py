import pytest

from PySide6.QtCore import QObject, QMetaObject, Qt, QPointF
from PySide6.QtTest import QTest

from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_dicom_tags import qt_app, wait_until


def test_workspace_menu_compact_footer_and_restored_width(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    sidebar = find(window, 'sidebarContainer')
    sidebar.setProperty('expandedWidth', 230)
    sidebar.setProperty('collapsed', True)
    entry = find(window, 'sidebarWorkspace')
    assert entry.parentItem().property('iconName') == 'workspace'
    click(window, entry)
    dialog = window.findChild(QObject, 'workspaceDocumentDialog')
    wait_until(lambda: dialog.property('visible'))
    assert dialog.property('height') <= window.height() - 24
    assert dialog.property('width') <= window.width() - 24
    QMetaObject.invokeMethod(dialog, 'close')
    manager = app.workspaceDocumentController
    path = tmp_path / 'layout.voxworkspace'
    manager.save_to(path); wait_until(lambda: not manager.busy)
    sidebar.setProperty('expandedWidth', 300)
    sidebar.setProperty('collapsed', False)
    manager.restore_from(path); wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    assert sidebar.property('expandedWidth') == 230
    assert sidebar.property('collapsed')
    assert not manager.dirty
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US', 'pt-BR'])
def test_export_help_long_result_link_and_measurement_instructions(sidebar_scene, tmp_path, monkeypatch, locale):
    from test_workspace_persistence import draw_length
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage(locale)
    window.resize(1000, 760)
    app.settingsController.setValue('layout', 'rightPanelWidth', 220)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '2D', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    draw_length(tab.activeViewport)
    tab.toolController.activateTool('export')
    report = app.exportController.measurementReport
    path = tmp_path / ('中文测量结果 &' * 12 + '.csv')
    assert report.export_to(path)
    wait_until(lambda: not report.busy)
    assert not report.isError, report.message
    link = find(window, 'measurementReportResultPath')
    wait_until(lambda: link.isVisible())
    QTest.qWait(80)
    panel_width = find(window, 'rightPanel').width()
    assert panel_width == 220
    assert link.property('text') == str(path)
    assert link.property('contentItem').property('truncated')
    calls = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.measurement_report_controller.reveal_path', lambda path: calls.append(path) or True)
    click(window, link)
    assert calls == [str(path)]
    assert window.grabWindow().save(str(tmp_path / 'export-help-links.png'))
    click(window, find(window, 'exportManualLink'))
    wait_until(lambda: ws.activeTabType == 'manual')
    assert ws.manualController.chapterId == 'export'
    ws.activateTabId(tab.tab_config.tab_id)
    wait_until(lambda: ws.activeTab is tab)
    assert report.resultPath == str(path)
    assert len(tab.activeViewport._measure_controller._measurements) == 1
    tab.toolController.activateTool('measure')
    wait_until(lambda: find(window, 'measurementResultsToggle').isVisible())
    QTest.qWait(80)
    listing = find(window, 'measurementResultsToggle')
    assert listing.width() <= panel_width
    assert len(tab.measurementResults.items) == 1
    assert window.grabWindow().save(str(tmp_path / 'measurement-list.png'))
    assert not warnings, warnings


def test_workspace_menu_stays_inside_small_window_with_recovery(sidebar_scene, tmp_path):
    window, app, _, warnings = sidebar_scene
    manager = app.workspaceDocumentController
    manager._recovery_path = tmp_path / 'recovery.voxworkspace'
    manager._recovery_path.write_text('test recovery')
    manager._autosave_enabled = manager._previous_recovery = True
    manager.changed.emit()
    window.setWidth(1000); window.setHeight(600)
    click(window, find(window, 'sidebarWorkspace'))
    dialog = window.findChild(QObject, 'workspaceDocumentDialog')
    wait_until(lambda: dialog.property('visible'))
    assert dialog.property('height') <= 576
    assert dialog.property('y') >= 0
    assert not warnings, warnings


def test_report_controls_and_single_view_layout_binding(sidebar_scene, tmp_path):
    from test_tag_qml import descendants
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'MPR', 'mpr')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    tab.focusSingleViewport(tab.activeViewport.viewportId)
    def layout():
        return next((i for i in descendants(window.contentItem()) if i.property('layoutMode') is not None and i.isVisible()), None)
    wait_until(lambda: layout() is not None and layout().property('singleViewMode'))
    ws.openSettings()
    ws.activateTabId(tab.tab_config.tab_id)
    wait_until(lambda: layout() is not None and layout().property('singleViewMode'))
    window.setWidth(1280)
    app.settingsController.setValue('layout', 'rightPanelWidth', 220)
    QTest.qWait(80)
    tab.toolController.activateTool('export')
    csv, pdf = find(window, 'exportMeasurementCsv'), find(window, 'exportMeasurementPdf')
    wait_until(lambda: csv.isVisible() and pdf.isVisible())
    QTest.qWait(150)
    assert csv.width() > 50 and pdf.width() > 50
    assert csv.mapToScene(QPointF(csv.width(), 0)).x() <= pdf.mapToScene(QPointF()).x()
    assert find(window, 'viewportExportAnonymous').property('checked')
    assert window.grabWindow().save(str(tmp_path / 'workspace-export-panel.png'))
    assert not warnings, warnings
