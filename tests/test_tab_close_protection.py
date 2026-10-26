"""Closing views retains completed work without a destructive-action prompt."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from qt_dicom_viewer.core.workspace_state import loads
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length
from test_series_sidebar import sidebar_scene
from test_tab_windows import open_tabs, detached


@pytest.fixture(autouse=True)
def no_close_prompt(monkeypatch):
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('Closing a tab must not prompt'))


def test_saved_and_restored_edits_close_without_changing_saved_file(qt_app, tmp_path):
    app, _ = populated_app(tmp_path)
    ws, doc = app.workspaceController, app.workspaceDocumentController
    try:
        draw_length(ws.activeViewport)
        path = tmp_path/'saved.voxworkspace'
        assert doc.save_to(path)
        wait_until(lambda: not doc.busy)
        original = path.read_bytes()
        assert doc.restore_from(path)
        wait_until(lambda: not doc.busy)
        assert not ws.activeTab.historyController.canUndo
        assert ws.closeTab(ws.activeTabId)
        assert not ws.tabs and doc.closedTabCount == 1 and doc.dirty
        assert path.read_bytes() == original
    finally:
        app.shutdown()


def test_bulk_close_keeps_all_edited_results(sidebar_scene):
    _, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records)
    for tab in tabs:
        draw_length(tab.activeViewport)
    app.windowManager.mainWorkspace.closeTabs(tabs[0].tab_config.tab_id, 'all')
    assert not app.workspaceController.tabs and app.workspaceDocumentController.closedTabCount == 3
    for snapshot in app.workspaceController._closed_tab_snapshots.values():
        assert any(v.get('measurements') for v in loads(snapshot)['edits']['views'].values())
    assert not warnings, warnings


def test_detached_window_close_retains_results(sidebar_scene):
    _, app, records, warnings = sidebar_scene
    first, _ = open_tabs(app, records[:2])
    draw_length(first.activeViewport)
    session, other = detached(app, first)
    key = first.tab_config.tab_id
    assert other.close()
    wait_until(lambda: not other.isVisible())
    assert key in app.workspaceController._closed_tab_snapshots
    assert app.workspaceDocumentController.reopenLastClosed()
    wait_until(lambda: not app.workspaceDocumentController.busy)
    assert len(app.workspaceController.activeViewport._measure_controller._measurements) == 1
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['annotation', 'voi', 'segmentation'])
def test_nonmeasurement_results_retained_without_undo_history(qt_app, tmp_path, kind):
    from test_mpr_voi_controller import draw
    app, record = populated_app(tmp_path)
    try:
        ws = app.workspaceController
        if kind == 'annotation':
            tab = ws.activeTab
            tab.activeViewport._text_annotation_controller.addAnnotation(1, 1, 5, 5)
        else:
            ws.createTab(record.series_instance_uid, 'MPR', 'mpr')
            wait_until(lambda: ws.activeLoadState.status == 'ready')
            tab = ws.activeTab
            if kind == 'segmentation':
                tab._voi_controller.newSegment()
            else:
                tab.toolController.activateTool('voi')
                draw(tab._voi_controller, tab.activeViewport)
        key = tab.tab_config.tab_id
        tab.historyController.reset()
        assert ws.closeTab(key)
        assert key in ws._closed_tab_snapshots
        assert app.workspaceDocumentController.reopenLastClosed()
        wait_until(lambda: not app.workspaceDocumentController.busy)
        assert not app.workspaceDocumentController.isError
        if kind == 'annotation':
            assert ws.activeViewport._text_annotation_controller._annotations
        else:
            assert ws.activeTab._voi_controller.records
    finally:
        app.shutdown()


@pytest.mark.parametrize('gesture', ['button', 'middle', 'shortcut', 'viewport'])
def test_visible_close_gestures_retain_results(sidebar_scene, gesture):
    from test_tag_qml import find
    window, app, records, warnings = sidebar_scene
    tab = open_tabs(app, records[:1])[0]
    draw_length(tab.activeViewport)
    key = tab.tab_config.tab_id
    if gesture == 'viewport':
        tab.closeRequested.emit()
    elif gesture in ('button', 'middle'):
        target = find(window, 'workspaceTab-' + key)
        QTest.mouseClick(window, Qt.LeftButton if gesture == 'button' else Qt.MiddleButton, Qt.NoModifier,
                         target.mapToScene(QPointF(target.width()-18 if gesture == 'button' else 30, 15)).toPoint())
    else:
        window.requestActivate(); QTest.qWait(30)
        QTest.keyClick(window, Qt.Key_W, Qt.ControlModifier)
    wait_until(lambda: not app.workspaceController.tabs)
    assert key in app.workspaceController._closed_tab_snapshots
    assert not warnings, warnings


def test_mpr_comparison_group_segment_retained(sidebar_scene):
    from test_compare_mpr import open_pair
    _, app, records, warnings = sidebar_scene
    tab = open_pair(app, records)
    tab.groups[1]._voi_controller.newSegment()
    assert app.workspaceController.closeTab(tab.tab_config.tab_id)
    assert app.workspaceDocumentController.reopenLastClosed()
    wait_until(lambda: not app.workspaceDocumentController.busy)
    assert not app.workspaceDocumentController.isError
    assert app.workspaceController.activeTab.groups[1]._voi_controller.records
    assert not warnings, warnings


@pytest.mark.parametrize('kind,completed', [('mtf', False), ('fwhm', False), ('mtf', True), ('fwhm', True), ('qa', True)])
def test_analysis_only_results_retained(qt_app, tmp_path, kind, completed):
    from test_mtf_controller import bead_render, deliver_frame
    from test_water_qa_controller import water_render
    app, _ = populated_app(tmp_path)
    try:
        ws = app.workspaceController
        tab, view = ws.activeTab, ws.activeViewport
        deliver_frame(view, water_render(view) if kind == 'qa' else bead_render(view))
        controller = getattr(view, '_' + kind + '_controller')
        if kind == 'qa':
            tab.toolController.selectService('service:qa')
        else:
            assert controller.applyRoi(63, 63, 8, 3)
        if completed:
            wait_until(lambda: controller.status != 'calculating')
            assert controller.status == 'ready', controller.error
        key = tab.tab_config.tab_id
        tab.historyController.reset()
        assert ws.closeTab(key)
        record = loads(ws._closed_tab_snapshots[key])
        saved = next(v['analyses'][kind] for v in record['views'].values() if kind in v.get('analyses', {}))
        assert saved['records'] if completed else saved['roi']['measurements']
    finally:
        app.shutdown()
