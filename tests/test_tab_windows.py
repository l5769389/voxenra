"""Move real loaded pages between windows, including interaction and persistence."""
import sys
from PySide6.QtCore import QObject, QPointF, Qt, QMetaObject, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtGui import QGuiApplication
import pytest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene, right_click
from test_tag_qml import find, click
from test_workspace_persistence import draw_length
from test_pet_fusion import paired_series


def open_tabs(app, records):
    tabs = []
    for record in records:
        app.workspaceController.createTab(record.series_instance_uid, 'Synthetic CT', '2d')
        wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
        tabs.append(app.workspaceController.activeTab)
    QTest.qWait(80)
    return tabs


def detached(app, tab):
    manager = app.windowManager
    assert manager.detachTab(tab.tab_config.tab_id)
    session = manager.owner(tab.tab_config.tab_id)
    assert session.detached
    wait_until(lambda: not manager._transfers)
    return session, manager.windows[session.windowId]


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('language', ['zh-CN', 'en-US'])
def test_reorder_menu_and_pointer_actions(sidebar_scene, theme, language):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(language)
    tabs = open_tabs(app, records)
    session = app.windowManager.mainWorkspace
    ids = [tab.tab_config.tab_id for tab in tabs]
    active = session.activeTab
    button = find(window, 'workspaceTab-' + ids[0])
    right_click(window, button)
    menu = window.findChild(QObject, 'tabContextMenu')
    assert menu.property('visible') and menu.property('tabId') == ids[0]
    assert session.activeTab is active
    assert window.findChild(QObject, 'tabMenu-right').property('enabled')
    assert window.findChild(QObject, 'tabMenu-detach').property('visible')
    for name, icon in [('detach', 'tab-detach'), ('close', 'close'), ('others', 'tab-close-others'),
                       ('right', 'tab-close-right'), ('all', 'tab-close-all')]:
        glyph = window.findChild(QObject, 'tabMenu-' + name + '-icon')
        assert glyph.property('iconName') == icon
    QMetaObject.invokeMethod(menu, 'close')
    QTest.qWait(30)
    # A pointer drag commits at the insertion boundary; it does not activate or clone the page.
    drag = find(window, 'tabDrag-' + ids[0])
    start = drag.mapToScene(QPointF(20, 15)).toPoint()
    end = find(window, 'workspaceTab-' + ids[2]).mapToScene(QPointF(180, 15)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 30)
    QTest.keyClick(window, Qt.Key_Escape)
    assert not app.windowManager.dragging
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(30)
    assert session._ids == ids and session.activeTab is active
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 30)
    assert app.windowManager.dragging
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    wait_until(lambda: session._ids == [ids[1], ids[2], ids[0]])
    assert session.activeTab is active
    # Middle click closes its target, regardless of selection.
    target = find(window, 'workspaceTab-' + ids[1])
    QTest.mouseClick(window, Qt.MiddleButton, Qt.NoModifier,
                     target.mapToScene(QPointF(30, 15)).toPoint())
    wait_until(lambda: ids[1] not in app.workspaceController._tab_dict)
    assert session.activeTab is active
    assert not warnings, warnings


def test_detach_move_back_preserves_views_history_and_independent_tools(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    first, second = open_tabs(app, records[:2])
    draw_length(first.activeViewport)
    first.historyController.capture()
    view, history = first.activeViewport, first.historyController
    first.toolController.activateTool('pan')
    second.toolController.activateTool('zoom')
    session, other = detached(app, first)
    main = app.windowManager.mainWorkspace
    assert main.activeTab is second and session.activeTab is first
    assert session.activeViewport is view and session.activeTab.historyController is history
    assert history.canUndo
    assert not other.findChild(QObject, 'sidebarContainer').isVisible()
    assert find(other, 'showMainWindow').isVisible()
    assert other.minimumWidth() == min(960, other.property('availableWindowWidth'))
    right_click(other, find(other, 'workspaceTab-' + first.tab_config.tab_id))
    menu = other.findChild(QObject, 'tabContextMenu')
    assert menu.property('visible')
    assert not other.findChild(QObject, 'tabMenu-detach').property('visible')
    assert other.findChild(QObject, 'tabMenu-detach').property('height') == 0
    assert other.findChild(QObject, 'tabMenu-main').property('visible')
    assert other.findChild(QObject, 'tabMenu-main-icon').property('iconName') == 'tab-return'
    QMetaObject.invokeMethod(menu, 'close')
    QTest.qWait(30)
    assert main.activeTab.toolController.activeTool == 'zoom'
    assert session.activeTab.toolController.activeTool == 'pan'
    # Selecting tools in the independent window does not affect the main one.
    click(other, find(other, 'primaryTool-window'))
    assert first.toolController.activeTool == 'window'
    assert second.toolController.activeTool == 'zoom'
    # Opening a duplicate brings the existing independent tab to the front.
    app.workspaceController.createTab(records[0].series_instance_uid, 'Duplicate', '2d')
    assert len(app.workspaceController._tab_dict) == 2 and session.activeTab is first
    assert app.windowManager.owner(first.tab_config.tab_id) is session
    app.windowManager.moveToMain(first.tab_config.tab_id)
    wait_until(lambda: session.windowId not in app.windowManager.sessions)
    assert main.activeTab is first and first.activeViewport is view
    assert first.historyController is history and history.canUndo
    assert len(view._measure_controller._measurements) == 1
    # Exercise actual destruction, not just hiding the independent window.
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.workspaceController.openSettings()
    QTest.qWait(30)
    assert window.isVisible() and main.activeTabType == 'settings'
    assert not warnings, warnings


def test_drag_out_cancel_and_cross_window_merge(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    first, second = open_tabs(app, records[:2])
    manager = app.windowManager
    key = first.tab_config.tab_id
    bar = manager.bars['main']
    start = bar.mapToGlobal(QPointF(20, 15))
    manager.beginDrag('main', key, start.x(), start.y())
    manager.updateDrag(start.x() + 80, start.y() + 90)
    manager.cancelDrag()
    assert not manager.finishDrag(start.x() + 80, start.y() + 90)
    assert len(manager.sessions) == 1 and manager.mainWorkspace.activeTab is second
    # A drop in the image area must not create a new window.
    manager.beginDrag('main', key, start.x(), start.y())
    assert manager.finishDrag(start.x() + 80, start.y() + 90)
    assert len(manager.sessions) == 1
    manager.beginDrag('main', key, start.x(), start.y())
    assert manager.finishDrag(window.x() + window.width() + 80, window.y() + 100)
    session = manager.owner(key)
    assert session.detached
    wait_until(lambda: not manager._transfers)
    manager.windows[session.windowId].setPosition(window.x() + window.width() + 30, window.y())
    QTest.qWait(40)
    source = manager.bars[session.windowId].mapToGlobal(QPointF(20, 15))
    window.raise_()
    destination = bar.mapToGlobal(QPointF(20, 15))
    manager.beginDrag(session.windowId, key, source.x(), source.y())
    assert manager.finishDrag(destination.x(), destination.y())
    wait_until(lambda: manager.owner(key) is manager.mainWorkspace)
    wait_until(lambda: len(manager.sessions) == 1)
    assert manager.mainWorkspace._ids[0] == key
    assert not warnings, warnings


def test_pointer_tear_off_and_return(sidebar_scene):
    if QGuiApplication.platformName() in ('offscreen', 'minimal'):
        pytest.skip('Desktop mouse-grab acceptance requires a native window platform')
    window, app, records, warnings = sidebar_scene
    first, second = open_tabs(app, records[:2])
    manager, key = app.windowManager, first.tab_config.tab_id
    start = find(window, 'tabDrag-' + key).mapToScene(QPointF(25, 15)).toPoint()
    outside = QPointF(window.width() + 70, 120).toPoint()
    QTest.mousePress(window, Qt.LeftButton, pos=start)
    QTest.mouseMove(window, outside, 40)
    assert manager.dragging
    QTest.mouseRelease(window, Qt.LeftButton, pos=outside)
    wait_until(lambda: manager.owner(key).detached and not manager._transfers)
    session = manager.owner(key)
    other = manager.windows[session.windowId]
    other.setPosition(window.x() + window.width() + 30, window.y())
    window.raise_()
    QTest.qWait(40)
    start = find(other, 'tabDrag-' + key).mapToScene(QPointF(25, 15)).toPoint()
    destination = manager.bars['main'].mapToGlobal(QPointF(20, 15)).toPoint()
    end = other.mapFromGlobal(destination)
    QTest.mousePress(other, Qt.LeftButton, pos=start)
    QTest.mouseMove(other, end, 40)
    QTest.mouseRelease(other, Qt.LeftButton, pos=end)
    wait_until(lambda: len(manager.sessions) == 1)
    assert manager.mainWorkspace._ids[0] == key
    assert manager.mainWorkspace.activeTab is first
    assert second.tab_config.tab_id in manager.mainWorkspace._ids
    assert not warnings, warnings


def test_overflow_edge_scroll_and_close_right(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records)
    session, manager = app.windowManager.mainWorkspace, app.windowManager
    session.openSettings()
    session.openManual('tabs')
    session.openPacs()
    for record in records:
        session.createTab(record.series_instance_uid, 'Tags', 'tag')
    QTest.qWait(80)
    bar = manager.bars['main']
    ids = list(session._ids)
    content = bar.property('contentItem')
    content.setProperty('contentX', 0.)
    start = bar.mapToGlobal(QPointF(25, 15))
    edge = bar.mapToGlobal(QPointF(bar.width() - 5, 15))
    manager.beginDrag('main', ids[0], start.x(), start.y())
    manager.updateDrag(edge.x(), edge.y())
    QTest.qWait(220)
    assert content.property('contentX') > 0
    manager.cancelDrag()
    assert session._ids == ids
    # Close-right is relative to its target, not the selected final tab.
    session.closeTabs(ids[3], 'right')
    assert session._ids == ids[:4]
    session.closeTabs(ids[0], 'all')
    assert not session.tabs and window.isVisible()
    assert not warnings, warnings


def test_close_scope_main_reopen_and_last_window_cancel(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records)
    session, other = detached(app, tabs[0])
    assert window.close()
    QTest.qWait(30)
    assert not window.isVisible() and other.isVisible()
    assert list(app.workspaceController._tab_dict) == [tabs[0].tab_config.tab_id]
    calls = []
    monkeypatch.setattr(app.workspaceDocumentController, 'requestClose', lambda: calls.append(True) or False)
    assert not other.close()
    assert len(calls) == 1 and session.activeTab is tabs[0]
    click(other, find(other, 'showMainWindow'))
    assert window.isVisible() and not app.windowManager.mainWorkspace.tabs
    assert other.close()
    wait_until(lambda: session.windowId not in app.windowManager.sessions)
    assert not app.workspaceController.tabs and window.isVisible()
    assert len(calls) == 1
    assert not warnings, warnings


def test_save_all_windows_and_restore_flattened_order(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records)
    main = app.windowManager.mainWorkspace
    ids = [tab.tab_config.tab_id for tab in tabs]
    main.moveTab(ids[2], 0)
    session, other = detached(app, tabs[0])
    draw_length(tabs[0].activeViewport)
    draw_length(tabs[1].activeViewport)
    from qt_dicom_viewer.ui.controller.measurement_report_controller import capture_results
    rows, _, _ = capture_results(session, app._series_catalog, all_tabs=False)
    all_rows, _, _ = capture_results(session, app._series_catalog, all_tabs=True)
    assert len(rows) == 1 and len(all_rows) == 2
    saved_order = [tab.tab_config.tab_id for tab in app.windowManager.ordered_tabs()]
    assert saved_order == [ids[2], ids[1], ids[0]]
    path = tmp_path / 'multi-window.voxworkspace'
    document = app.workspaceDocumentController
    assert document.save_to(path)
    wait_until(lambda: not document.busy)
    assert not document.isError, document.message
    document.restore_from(path)
    wait_until(lambda: not document.busy)
    assert not document.isError, document.message
    assert len(app.windowManager.sessions) == 1
    assert main._ids == saved_order and main.activeTabId == ids[0]
    assert len(main.activeViewport._measure_controller._measurements) == 1
    assert not document.dirty
    assert not warnings, warnings


def test_loading_failure_retry_close_and_stale_result_after_transfer(sidebar_scene):
    from qt_dicom_viewer.model import RenderFailure
    window, app, records, warnings = sidebar_scene
    registry = app.workspaceController
    requests = []
    registry.renderRequested.disconnect(app.render_service.submit)
    registry.renderRequested.connect(requests.append)
    registry.createTab(records[0].series_instance_uid, 'Pending', '2d')
    tab, opening = registry.activeTab, registry.activeLoadState
    first = requests[-1]
    assert opening.status == 'loading'
    session, other = detached(app, tab)
    assert session.activeLoadState is opening
    failure = RenderFailure(request_id=first.request_id, viewport_id=first.viewport_id, error=RuntimeError('synthetic failure'))
    registry.handleRenderFailure(failure)
    assert opening.status == 'error'
    session.retryActiveTab()
    retry = requests[-1]
    assert retry.request_id != first.request_id and opening.status == 'loading'
    registry.handleRenderFailure(failure)
    assert opening.status == 'loading'
    app.render_service.submit(retry)
    wait_until(lambda: opening.status == 'ready')
    # A different pending page can close without consuming a later callback.
    session.createTab(records[1].series_instance_uid, 'Close while loading', '2d')
    closed_id, pending = session.activeTabId, requests[-1]
    session.closeTab(closed_id)
    registry.handleRenderFailure(RenderFailure(request_id=pending.request_id, viewport_id=pending.viewport_id,
                                               error=RuntimeError('late callback')))
    assert closed_id not in registry._tab_dict and session.activeTab is tab
    assert opening.status == 'ready'
    assert not warnings, warnings


def test_window_local_shortcuts_bulk_close_and_utility_tabs(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records)
    session, other = detached(app, tabs[0])
    session.openManual('tabs')
    wait_until(lambda: session.activeTabType == 'manual')
    manual = session.activeTabId
    original_main = app.windowManager.mainWorkspace.activeTabId
    other.requestActivate()
    QTest.qWait(60)
    tab_modifier = Qt.MetaModifier if sys.platform == 'darwin' else Qt.ControlModifier
    QTest.keyClick(other, Qt.Key_Tab, tab_modifier)
    wait_until(lambda: session.activeTab is tabs[0])
    assert app.windowManager.mainWorkspace.activeTabId == original_main
    QTest.keyClick(other, Qt.Key_Tab, tab_modifier | Qt.ShiftModifier)
    wait_until(lambda: session.activeTabId == manual)
    QTest.keyClick(other, Qt.Key_W, Qt.ControlModifier)
    wait_until(lambda: manual not in app.workspaceController._tab_dict)
    assert session.activeTab is tabs[0]
    # Closing other tabs in the main window cannot close independent tabs.
    main = app.windowManager.mainWorkspace
    main.closeTabs(tabs[1].tab_config.tab_id, 'others')
    assert main._ids == [tabs[1].tab_config.tab_id]
    assert session.activeTab is tabs[0]
    assert not warnings, warnings


def test_failed_presentation_rolls_back_and_preview_does_not_dirty_workspace(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    tabs = open_tabs(app, records[:2])
    manager, document = app.windowManager, app.workspaceDocumentController
    source_id = tabs[0].tab_config.tab_id
    session, other = detached(app, tabs[1])
    original = list(manager.mainWorkspace._ids)
    document._dirty = False
    bar = manager.bars['main']
    p = bar.mapToGlobal(QPointF(30, 15))
    manager.beginDrag('main', source_id, p.x(), p.y())
    manager.updateDrag(p.x() + 30, p.y())
    manager.cancelDrag()
    assert not document.dirty and manager.mainWorkspace._ids == original
    assert manager.moveTab(source_id, session.windowId, 0)
    manager.pageReady('main', source_id, False)
    assert source_id in manager._transfers  # A late source-page callback cannot acknowledge a new mount.
    manager.pageReady(session.windowId, source_id, False)
    assert manager.mainWorkspace._ids == original
    assert manager.owner(source_id) is manager.mainWorkspace
    assert session._ids == [tabs[1].tab_config.tab_id]
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['montage', 'mpr', 'tag', 'settings', 'pacs'])
def test_other_page_types_move_without_rebuilding_controller(sidebar_scene, kind):
    window, app, records, warnings = sidebar_scene
    registry, manager = app.workspaceController, app.windowManager
    if kind == 'settings':
        registry.openSettings()
    elif kind == 'pacs':
        registry.openPacs()
    else:
        registry.createTab(records[0].series_instance_uid, kind, kind)
        wait_until(lambda: registry.activeLoadState.status == 'ready')
    tab = registry.activeTab
    views = dict(tab.viewports_by_id)
    session, other = detached(app, tab)
    assert session.activeTab is tab and dict(tab.viewports_by_id) == views
    assert not manager.mainWorkspace.tabs
    # Empty main window has a usable drop zone while dragging.
    window.raise_()
    other.setPosition(window.x() + window.width() + 30, window.y())
    pump_point = manager.bars[session.windowId].mapToGlobal(QPointF(30, 15))
    manager.beginDrag(session.windowId, tab.tab_config.tab_id, pump_point.x(), pump_point.y())
    end = manager.bars['main'].mapToGlobal(QPointF(30, 15))
    manager.finishDrag(end.x(), end.y())
    wait_until(lambda: len(manager.sessions) == 1)
    assert manager.mainWorkspace.activeTab is tab
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['pet', 'fusion', '4d'])
def test_reconstructed_pages_keep_volume_and_phase(sidebar_scene, paired_series, tmp_path, kind):
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.workspace_snapshot import editable_state, edit_signature
    from test_four_d import _cross_series_four_d
    window, app, records, warnings = sidebar_scene
    _, ct, pet = paired_series
    series = _cross_series_four_d(tmp_path/'phases') if kind == '4d' else [ct, pet]
    app._series_catalog.update(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, series))
    registry = app.workspaceController
    if kind == 'fusion':
        registry.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    else:
        registry.createTab((series[0] if kind == '4d' else pet).series_instance_uid, kind, '4d' if kind == '4d' else 'mpr')
    wait_until(lambda: registry.activeLoadState.status == 'ready')
    tab = registry.activeTab
    if kind == '4d':
        tab.setPhaseIndex(1)
        wait_until(lambda: tab.currentPhaseIndex == 1)
    state = edit_signature(editable_state(tab))
    views, history = dict(tab.viewports_by_id), tab.historyController
    session, other = detached(app, tab)
    app.windowManager.moveToMain(tab.tab_config.tab_id)
    wait_until(lambda: len(app.windowManager.sessions) == 1)
    assert registry.activeTab is tab and tab.viewports_by_id == views
    assert tab.historyController is history and edit_signature(editable_state(tab)) == state
    if kind == '4d':
        assert tab.currentPhaseIndex == 1
    assert not warnings, warnings


@pytest.mark.parametrize("mode", ["Windowed", "Maximized", "FullScreen"])
def test_opening_tabs_preserves_window_size_and_state(sidebar_scene, mode):
    from PySide6.QtGui import QWindow
    window, app, records, warnings = sidebar_scene
    registry = app.workspaceController
    window.showNormal()
    window.resize(1180, 700)
    visibility = getattr(QWindow, mode)
    window.setVisibility(visibility)
    wait_until(lambda: window.visibility() == visibility)
    QTest.qWait(400)
    geometry = window.geometry()
    for index, kind in enumerate(("2d", "mpr", "compare2d", "settings")):
        if kind == "settings":
            registry.openSettings()
        elif kind == "compare2d":
            registry.createCompareTab(*(r.series_instance_uid for r in records[:2]))
        else:
            registry.createTab(records[index].series_instance_uid, kind, kind)
        wait_until(lambda: kind == "settings" or registry.activeLoadState.status == "ready")
        QTest.qWait(80)
        assert window.visibility() == visibility
        assert window.geometry() == geometry
    first = next(iter(registry._tab_dict))
    app.windowManager.activate_tab(first)
    app.windowManager.showMainWindow()
    QTest.qWait(80)
    assert window.visibility() == visibility
    assert window.geometry() == geometry
    assert not warnings, warnings


def test_settings_update_tooltip_handles_detached_anchor(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    app.workspaceController.openSettings()
    wait_until(lambda: window.findChild(QObject, "settingsUpdateBadge") is not None)
    badge = window.findChild(QObject, "settingsUpdateBadge")
    tooltip = next(child for child in badge.children() if child.inherits("QQuickToolTip"))
    # Popup anchors can become null while a settings page is being detached.
    assert tooltip.setProperty("parent", None)
    QTest.qWait(50)
    assert not tooltip.property("visible")
    assert not warnings, warnings
