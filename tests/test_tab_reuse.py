"""Opening a view resumes its live session; recovery keeps historical sessions."""
import pytest
from PySide6.QtCore import QObject, QMetaObject, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QWindow

from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length
from test_compare_2d import comparison
from test_series_sidebar import sidebar_scene, right_click
from test_tab_windows import open_tabs, detached
from test_tag_qml import find, click
from test_workspace_dialog_layout import workspace_dialog
from test_pet_fusion import paired_series
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider


@pytest.mark.parametrize('kind', ['2d', 'mpr', 'cpr', '3d', 'montage', 'tag'])
def test_open_series_view_resumes_existing_controller(qt_app, tmp_path, kind):
    app, record = populated_app(tmp_path)
    try:
        ws = app.workspaceController
        ws.createTab(record.series_instance_uid, 'Original', kind)
        original = ws.activeTab
        original_ids = set(ws._tab_dict)
        app.panelController.openSeriesView(record.series_instance_uid, kind)
        assert ws.activeTab is original
        assert set(ws._tab_dict) == original_ids
    finally:
        app.shutdown()


def test_repeated_open_keeps_edits_and_explicit_sessions(qt_app, tmp_path):
    app, record = populated_app(tmp_path)
    try:
        ws = app.workspaceController
        first = ws.activeTab
        mid = draw_length(first.activeViewport)
        first.historyController.capture()
        ws.createTab(record.series_instance_uid, 'Independent', '2d', new_session=True)
        second = ws.activeTab
        assert second is not first
        ws.activateTabId(first.tab_config.tab_id)
        app.panelController.openSeriesView(record.series_instance_uid, '2d')
        assert ws.activeTab is first and len(ws.tabs) == 2
        assert mid in first.activeViewport._measure_controller._measurements
        assert first.historyController.canUndo
        ws._close_tab(first.tab_config.tab_id)
        app.panelController.openSeriesView(record.series_instance_uid, '2d')
        assert ws.activeTab is second and len(ws.tabs) == 1
    finally:
        app.shutdown()


@pytest.mark.parametrize('kind,method', [('compare2d', 'createMultiCompareTab'), ('comparempr', 'createMprCompareTab')])
def test_same_comparison_sources_resume_but_other_sources_stay_separate(comparison, kind, method):
    app, records = comparison
    ws = app.workspaceController
    uids = [record.series_instance_uid for record in records]
    create = getattr(ws, method)
    args = lambda selected: (selected,) if kind == 'compare2d' else tuple(selected)
    create(*args(uids[:2]))
    original = ws.activeTab
    create(*args(list(reversed(uids[:2]))))
    assert ws.activeTab is original and len(ws.tabs) == 1
    create(*args(uids[:2]), new_session=True)
    assert ws.activeTab is not original and len(ws.tabs) == 2
    if kind == 'compare2d':
        create(uids[1:])
        assert len(ws.tabs) == 3
        create(uids)
        assert len(ws.tabs) == 4
    ws.createTab(uids[0], 'Single', '2d')
    assert ws.activeTabType == '2d'
    assert original in ws._tab_dict.values()


@pytest.mark.parametrize('kind,method', [('compare2d', 'createMultiCompareTab'), ('comparempr', 'createMprCompareTab')])
def test_comparison_undo_close_does_not_replace_live_session(comparison, kind, method):
    app, records = comparison
    ws, doc = app.workspaceController, app.workspaceDocumentController
    uids = [record.series_instance_uid for record in records[:2]]
    create = getattr(ws, method)
    args = (uids,) if kind == 'compare2d' else tuple(uids)
    create(*args)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    historical = ws.activeTab
    draw_length(historical.activeViewport)
    assert ws.closeTab(ws.activeTabId)
    create(*args)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    live = ws.activeTab
    assert doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert not doc.isError, doc.message
    assert ws.activeTab is not live and len(ws.tabs) == 2
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert not live.activeViewport._measure_controller._measurements


def test_sidebar_open_activates_detached_owner_without_moving_tab(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    first, second = open_tabs(app, records[:2])
    session, other = detached(app, first)
    app.windowManager.mainWorkspace.activateTabId(second.tab_config.tab_id)
    other.showMinimized()
    app.panelController.openSeriesView(records[0].series_instance_uid, '2d')
    wait_until(lambda: app.windowManager.focusedWindowId == session.windowId)
    assert app.workspaceController.activeTab is first
    assert app.windowManager.owner(first.tab_config.tab_id) is session
    assert app.windowManager.mainWorkspace.activeTab is second
    assert len(app.workspaceController.tabs) == 2
    assert other.isVisible() and other.visibility() != QWindow.Minimized
    assert not warnings, warnings


def test_empty_tab_strip_reopens_and_home_workspace_omit_restore(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    tab, = open_tabs(app, records[:1])
    draw_length(tab.activeViewport)
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(ws.activeTabId)
    QTest.qWait(100)
    assert find(window, 'workspaceEmptyState').isVisible()
    assert window.findChild(QObject, 'homeReopenClosedTab') is None
    dialog, native = workspace_dialog(window)
    assert dialog.findChild(QObject, 'reopenClosedTab') is None
    QMetaObject.invokeMethod(dialog, 'close')
    QTest.qWait(60)
    bar = app.windowManager.bars['main']
    assert bar.isVisible() and bar.height() >= 30
    right_click(window, bar)
    menu = window.findChild(QObject, 'tabContextMenu')
    assert menu.property('visible')
    restore = window.findChild(QObject, 'tabMenu-reopen')
    assert restore.property('enabled')
    click(restore.window(), restore)
    wait_until(lambda: not doc.busy and ws.activeTab is not None)
    assert not doc.isError and len(ws.activeViewport._measure_controller._measurements) == 1
    assert doc.closedTabCount == 0
    # Keyboard recovery remains available after the final view is closed again.
    assert ws.closeTab(ws.activeTabId)
    window.requestActivate()
    QTest.qWait(80)
    QTest.keyClick(window, Qt.Key_T, Qt.ControlModifier | Qt.ShiftModifier)
    wait_until(lambda: not doc.busy and ws.activeTab is not None)
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert not warnings, warnings


def test_fusion_pair_reuse_and_undo_preserve_independent_registration(qt_app, tmp_path, paired_series):
    _, ct, pet = paired_series
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet])
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws, doc = app.workspaceController, app.workspaceDocumentController
        pair = (ct.series_instance_uid, pet.series_instance_uid)
        ws.createFusionTab(*pair)
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        historical = ws.activeTab
        historical.matrix[0, 3] = 1.5
        historical._registration_changed = True
        ws.createFusionTab(*pair)
        assert ws.activeTab is historical and len(ws.tabs) == 1
        assert ws.closeTab(ws.activeTabId)
        ws.createFusionTab(*pair)
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        live = ws.activeTab
        assert doc.reopenLastClosed()
        wait_until(lambda: not doc.busy, timeout=20000)
        assert not doc.isError, doc.message
        assert ws.activeTab is not live and len(ws.tabs) == 2
        assert ws.activeTab.matrix[0, 3] == 1.5 and live.matrix[0, 3] == 0
        ws.createFusionTab(*pair)
        assert ws.activeTab.matrix[0, 3] == 1.5 and len(ws.tabs) == 2
        path = tmp_path / 'fusion-sessions.voxworkspace'
        assert doc.save_to(path)
        wait_until(lambda: not doc.busy)
        assert doc.restore_from(path)
        wait_until(lambda: not doc.busy, timeout=20000)
        assert not doc.isError, doc.message
        assert sorted(tab.matrix[0, 3] for tab in ws._tab_dict.values()) == [0, 1.5]
    finally:
        app.shutdown()


def test_stack_navigation_reuses_restored_session_after_original_closed(qt_app, tmp_path):
    app, record = populated_app(tmp_path)
    try:
        ws = app.workspaceController
        first_id = ws.activeTabId
        ws.createTab(record.series_instance_uid, 'Restored', '2d', new_session=True)
        restored = ws.activeTab
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        draw_length(restored.activeViewport)
        ws._close_tab(first_id)
        ws.openSeriesSlice(record.series_instance_uid, 1, 100, 500, False)
        assert ws.activeTab is restored and len(ws.tabs) == 1
        assert len(restored.activeViewport._measure_controller._measurements) == 1
        wait_until(lambda: restored.activeViewport.sliceIndex == 1)
    finally:
        app.shutdown()



def test_four_d_reuse_preserves_selected_phase_and_explicit_phase_subset(qt_app, tmp_path):
    from test_four_d import _cross_series_four_d
    records = _cross_series_four_d(tmp_path)
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws = app.workspaceController
        uid = records[0].series_instance_uid
        ws.createTab(uid, 'Historical phases', '4d', phase_identifiers=(0, 2), new_session=True)
        original = ws.activeTab
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        original.setPhaseIndex(1)
        wait_until(lambda: original.currentPhaseIndex == 1 and not original._active_mpr_requests)
        app.panelController.openSeriesView(uid, '4d')
        assert ws.activeTab is original and len(ws.tabs) == 1
        assert original.currentPhaseIndex == 1
        assert original.tab_config.series_metas[0].phase_identifiers == (0, 2)
        # A different anchor series in the same temporal group is still distinct.
        app.panelController.openSeriesView(records[1].series_instance_uid, '4d')
        assert ws.activeTab is not original and len(ws.tabs) == 2
    finally:
        app.shutdown()


def test_blank_strip_restore_keeps_remaining_tab(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    first, second = open_tabs(app, records[:2])
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(second.tab_config.tab_id)
    QTest.qWait(80)
    bar = app.windowManager.bars['main']
    # Use unused space beyond the one remaining tab, preserving its selection.
    point = bar.mapToScene(QPointF(bar.width() - 15, bar.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, point)
    QTest.qWait(40)
    menu = window.findChild(QObject, 'tabContextMenu')
    assert menu.property('visible') and menu.property('tabId') == ''
    assert not window.findChild(QObject, 'tabMenu-all').property('enabled')
    restore = window.findChild(QObject, 'tabMenu-reopen')
    assert restore.property('enabled')
    click(restore.window(), restore)
    wait_until(lambda: not doc.busy and len(ws.tabs) == 2)
    assert first in ws._tab_dict.values()
    assert not doc.isError and not warnings


@pytest.mark.parametrize('requested', ['original', 'replacement'])
def test_series_reuse_tracks_replaced_2d_cell_source(comparison, requested):
    app, records = comparison
    ws = app.workspaceController
    first, second = [record.series_instance_uid for record in records[:2]]
    ws.createTab(first, 'Original source', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    replaced_tab = ws.activeTab
    assert replaced_tab.twoDLayout.loadSeries(0, second)
    wait_until(lambda: replaced_tab.activeViewport.loadState == 'ready')
    draw_length(replaced_tab.activeViewport)
    uid = first if requested == 'original' else second
    app.panelController.openSeriesView(uid, '2d')
    assert ws.activeViewport.viewport_config.series_uid == uid
    if requested == 'replacement':
        assert ws.activeTab is replaced_tab and len(ws.tabs) == 1
    else:
        assert ws.activeTab is not replaced_tab and len(ws.tabs) == 2
    assert replaced_tab.activeViewport.viewport_config.series_uid == second
    assert len(replaced_tab.activeViewport._measure_controller._measurements) == 1


def test_single_series_open_preserves_multi_source_2d_layout(comparison):
    app, records = comparison
    ws = app.workspaceController
    first, second = [record.series_instance_uid for record in records[:2]]
    ws.createTab(first, 'Multi-source', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    multi = ws.activeTab
    multi.twoDLayout.setLayout('1x2')
    assert multi.twoDLayout.loadSeries(1, second)
    wait_until(lambda: multi.activeViewport.loadState == 'ready')
    draw_length(multi.activeViewport)
    app.panelController.openSeriesView(first, '2d')
    single = ws.activeTab
    assert single is not multi and len(ws.tabs) == 2
    assert single.activeViewport.viewport_config.series_uid == first
    assert [cell['seriesUid'] for cell in multi.twoDLayout.cells] == [first, second]
    assert len(multi.activeViewport._measure_controller._measurements) == 1
    app.panelController.openSeriesView(first, '2d')
    assert ws.activeTab is single and len(ws.tabs) == 2
