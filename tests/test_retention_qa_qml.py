import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_workspace_dialog_layout import workspace_dialog
from test_workspace_persistence import draw_length
from test_water_qa_controller import water_render, deliver_frame


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US', 'pt-BR'])
def test_retained_tab_home_dialog_and_shortcut(sidebar_scene, tmp_path, locale):
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
    home = find(window, 'homeReopenClosedTab')
    assert home.isVisible() and home.isEnabled()
    click(window, home)
    wait_until(lambda: not doc.busy)
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    ws.closeTab(ws.activeTabId)
    dialog, native = workspace_dialog(window)
    button = dialog.findChild(QObject, 'reopenClosedTab')
    assert button.isVisible() and button.isEnabled()
    manual = dialog.findChild(QObject, 'workspaceManualLink')
    assert button.x() >= manual.x() + manual.width()
    assert button.width() >= button.implicitWidth()
    native.grabWindow().save(str(tmp_path/f'reopen-{locale}.png'))
    click(native, button)
    wait_until(lambda: not doc.busy and not dialog.property('visible'))
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
