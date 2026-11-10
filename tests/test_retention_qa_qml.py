import pytest
from PySide6.QtCore import QObject, QMetaObject, QPointF, Qt
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene, right_click
from test_tag_qml import find, click
from test_workspace_dialog_layout import workspace_dialog
from test_workspace_persistence import draw_length
from test_water_qa_controller import water_render, deliver_frame


def tab_strip_reopen_item(window, app):
    bar = app.windowManager.bars['main']
    wait_until(bar.isVisible)
    right_click(window, bar)
    menu = window.findChild(QObject, 'tabContextMenu')
    wait_until(lambda: menu.property('visible'))
    undo = window.findChild(QObject, 'tabMenu-reopen')
    assert undo.isVisible() and undo.isEnabled()
    return undo


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US', 'pt-BR'])
def test_retained_tab_strip_and_shortcut(sidebar_scene, tmp_path, locale):
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage(locale)
    window.resize(1000, 600)
    ws, doc = app.workspaceController, app.workspaceDocumentController
    doc._autosave.stop()
    ws.createTab(records[0].series_instance_uid, 'Image', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    draw_length(ws.activeViewport)
    assert ws.closeTab(ws.activeTabId)
    QTest.qWait(80)
    assert find(window, 'workspaceEmptyState').isVisible()
    assert window.findChild(QObject, 'homeReopenClosedTab') is None
    dialog, native = workspace_dialog(window)
    assert dialog.findChild(QObject, 'reopenClosedTab') is None
    QMetaObject.invokeMethod(dialog, 'close')
    wait_until(lambda: not dialog.property('visible'))
    QTest.qWait(60)
    undo = tab_strip_reopen_item(window, app)
    assert undo.property('text') != 'workspace.reopenClosed'
    caption = next(item for item in undo.property('contentItem').childItems()
                   if item.property('text') == undo.property('text'))
    assert not caption.property('truncated')
    assert undo.window().grabWindow().save(str(tmp_path/f'reopen-{locale}.png'))
    click(undo.window(), undo)
    wait_until(lambda: not doc.busy and ws.activeTab is not None)
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    ws.closeTab(ws.activeTabId)
    window.requestActivate(); wait_until(window.isActive)
    QTest.keyClick(window, Qt.Key_T, Qt.ControlModifier | Qt.ShiftModifier)
    wait_until(lambda: not doc.busy and ws.activeTab is not None)
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert not warnings, warnings


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_qa_actual_buttons_keyboard_and_noop_drag(sidebar_scene, tmp_path, theme):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance','theme',theme)
    window.resize(1280, 900)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'QA', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    view, tab = ws.activeViewport, ws.activeTab
    deliver_frame(view, water_render(view))
    click(window, find(window,'primaryTool-service'))
    click(window, find(window,'serviceEntry-qa'))
    qa, history = view.qaController, tab.historyController
    wait_until(lambda: qa.status == 'ready')
    QTest.qWait(80)
    history.reset()
    original = qa.currentResult
    center = qa.roiItems[0]
    qa.begin_drag(center['column'], center['row']); qa.end_drag(center['column'], center['row'])
    history.capture(); assert not history.canUndo
    flick = find(window, 'toolDetailFlickable')
    def visible_click(name):
        target = find(window, name)
        y = target.mapToItem(flick, QPointF()).y()
        flick.setProperty('contentY', max(0, flick.property('contentY') + y - 40))
        QTest.qWait(60)
        click(window, target)
    visible_click('waterQaDelete-center')
    wait_until(lambda: history.canUndo)
    assert len(qa.roiItems) == 4
    visible_click('qaUndo')
    assert qa.currentResult == original
    visible_click('qaRedo')
    assert len(qa.roiItems) == 4
    window.requestActivate()
    QTest.keyClick(window, Qt.Key_Z, Qt.ControlModifier)
    wait_until(lambda: len(qa.roiItems) == 5)
    assert qa.currentResult == original
    assert window.grabWindow().save(str(tmp_path/f'qa-history-{theme}.png'))
    assert not warnings, warnings


def test_reopened_tab_keeps_slice_slider_and_image_in_sync(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    ws, doc = app.workspaceController, app.workspaceDocumentController
    doc._autosave.stop()
    ws.createTab(records[0].series_instance_uid, 'Image', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    ws.activeViewport.apply_slice_index(2)
    wait_until(lambda: ws.activeViewport._frame_meta.slice_index == 2)
    draw_length(ws.activeViewport)
    wait_until(lambda: find(window, 'sliceControl').property('value') == 3)
    assert ws.closeTab(ws.activeTabId)
    # The installed app can display the new view before its saved state arrives.
    # Ensure that ordering rather than relying on the fixture's fast rendering.
    from qt_dicom_viewer.ui.controller import workspace_document_controller as module
    apply_snapshot = module.apply_tab_snapshot
    def restore_after_slider_is_visible(tab, record):
        doc._restore_timer.stop()
        try:
            wait_until(lambda: find(window, 'sliceControl') is not None)
            QTest.qWait(60)
            assert find(window, 'sliceControl').property('value') == 1
            apply_snapshot(tab, record)
        finally:
            doc._restore_timer.start()
    monkeypatch.setattr(module, 'apply_tab_snapshot', restore_after_slider_is_visible)
    undo = tab_strip_reopen_item(window, app)
    click(undo.window(), undo)
    wait_until(lambda: not doc.busy and ws.activeLoadState.status == 'ready')
    assert ws.activeViewport.sliceIndex == 2
    assert ws.activeViewport._frame_meta.slice_index == 2
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert find(window, 'sliceControl').property('value') == 3
    assert find(window, 'sliceJumpButton').property('text') == '3'
    assert not warnings, warnings


def test_series_open_reuses_tab_and_tab_menu_undo_preserves_fresh_view(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws, doc = app.workspaceController, app.workspaceDocumentController
    click(window, find(window, 'series-' + records[0].series_instance_uid))
    click(window, find(window, 'openView-2d'))
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    edited = ws.activeTab
    draw_length(edited.activeViewport)
    click(window, find(window, 'openView-2d'))
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    assert ws.activeTab is edited and len(ws.tabs) == 1
    assert len(edited.activeViewport._measure_controller._measurements) == 1
    assert ws.closeTab(edited.tab_config.tab_id)
    click(window, find(window, 'openView-2d'))
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    fresh = ws.activeTab
    assert fresh is not edited and not fresh.activeViewport._measure_controller._measurements
    right_click(window, find(window, 'workspaceTab-' + ws.activeTabId))
    undo = window.findChild(QObject, 'tabMenu-reopen')
    wait_until(lambda: undo.isVisible() and undo.isEnabled())
    click(undo.window(), undo)
    wait_until(lambda: not doc.busy and ws.activeTab is not fresh)
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert not fresh.activeViewport._measure_controller._measurements

    path = tmp_path / 'independent.voxworkspace'
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy)
    assert not doc.isError, doc.message
    assert sorted(len(tab.activeViewport._measure_controller._measurements)
                  for tab in app.windowManager.ordered_tabs()) == [0, 1]
    assert not warnings, warnings
