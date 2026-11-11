"""The icon footer and standard undo/redo share actual document history."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_input_settings_qml import reading_scene, visible_viewport
from test_tag_qml import find, click, type_text, descendants, settled_point
from test_water_qa_controller import water_render, deliver_frame, wait_qa
from qt_pointer import activate_window, move_pointer


def test_icon_footer_history_shortcuts_text_and_dialog_isolation(sidebar_scene, qt_app):
    window, app, tab = reading_scene(sidebar_scene)
    activate_window(window)
    view = tab.activeViewport
    deliver_frame(view, water_render(view))
    qa, history = view.qaController, tab.historyController
    tab.toolController.selectService('service:qa'); wait_qa(qt_app, qa)
    history.reset()
    before = qa.currentResult
    qa.deleteRoi('left'); history.capture()
    edited = qa.currentResult
    QTest.qWait(40)
    buttons = [find(window, key) for key in ('qaUndo','qaRedo','exportQaReport','activeToolReset')]
    assert len({b.mapToScene(QPointF()).y() for b in buttons}) == 1
    assert buttons[0].isEnabled() and not buttons[1].isEnabled()
    for button, shortcut in zip(buttons[:2], (history.undoShortcutText, history.redoShortcutText)):
        assert shortcut in button.parentItem().property('tooltipText')
        assert not button.parentItem().property('showLabel')
        move_pointer(window, settled_point(button))
        wait_until(lambda: button.property('hovered'))
        # The tooltip itself has a 500 ms delay; waiting exactly 500 ms races
        # the native timer. Observe its visible state before checking history.
        wait_until(lambda: button.parentItem().property('tooltipVisible'))
    click(window, buttons[0]); assert qa.currentResult == before
    click(window, find(window, 'qaRedo')); assert qa.currentResult == edited
    viewport = visible_viewport(window)
    viewport.forceActiveFocus()
    QTest.keySequence(window, QKeySequence(QKeySequence.Undo))
    assert qa.currentResult == before
    QTest.keySequence(window, QKeySequence(QKeySequence.Redo))
    assert qa.currentResult == edited
    # Input editing has its own undo; no changes to the circles/history.
    # Narrow native desktops automatically collapse the series panel. Hiding
    # the tools panel gives the real search field enough room to be displayed.
    app.settingsController.setValue('layout', 'rightPanelCollapsed', True)
    search = find(window,'sidebarPatientSearch')
    wait_until(search.isVisible)
    type_text(window, search, 'abc')
    assert search.hasActiveFocus() and search.property('text') == 'abc'
    QTest.keySequence(window, QKeySequence(QKeySequence.Undo))
    assert qa.currentResult == edited and history.canUndo
    search.setProperty('text','')
    viewport.forceActiveFocus()
    app.feedbackController.show(); QTest.qWait(40)
    assert window.property('shortcutPopupOpen')
    QTest.keySequence(window, QKeySequence(QKeySequence.Undo))
    assert qa.currentResult == edited
    QTest.keyClick(window, Qt.Key_Escape); QTest.qWait(30)
    viewport.forceActiveFocus()
    QTest.keySequence(window, QKeySequence(QKeySequence.Undo))
    assert qa.currentResult == before
    assert not sidebar_scene[3], sidebar_scene[3]
