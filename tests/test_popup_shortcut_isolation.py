"""Foreground controls own their keys, including when Qt creates a second window."""
import pytest

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene
from test_pacs_qml import scene
from test_mpr_volume_tools_qml import item_window
from test_series_sidebar import right_click, sidebar_scene
from test_tag_qml import click, find


def test_native_tab_menu_owns_primary_secondary_and_workspace_keys(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    QTest.keyClick(window, Qt.Key_Z)
    viewport = tab.activeViewport
    viewport.setZoom(4)
    for _ in range(2):
        right_click(window, find(window, 'workspaceTab-' + tab.tab_config.tab_id))
        menu = window.findChild(QObject, 'tabContextMenu')
        wait_until(lambda: menu.property('opened'))
        # Cocoa can leave focusWindow() on the owner while presenting the menu.
        surface = item_window(menu.findChild(QObject, 'tabMenu-close'))
        try:
            assert window.property('shortcutPopupOpen')
            assert not window.property('standardShortcutsAllowed')
            for key in (Qt.Key_2, Qt.Key_P, Qt.Key_F12):
                QTest.keyClick(surface, key)
            assert viewport.zoom == 4 and tab.toolController.activeTool == 'zoom'
            assert not window.property('maximizedReadingArea')
        finally:
            QTest.keyClick(surface, Qt.Key_Escape)
        wait_until(lambda: not menu.property('visible'))
        window.requestActivate()
        wait_until(lambda: window.property('standardShortcutsAllowed'))
    QTest.keyClick(window, Qt.Key_2)
    assert viewport.zoom == 2
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('native', [True, False])
def test_passive_tooltip_preserves_reading_keys(sidebar_scene, native):
    window, app, tab = reading_scene(sidebar_scene)
    button = find(window, 'primaryTool-window')
    action = button.parentItem()
    tip = action.findChild(QObject, 'toolbarTooltip')
    if not native:  # Qt can fall back to a scene item on single-window platforms.
        assert tip.setProperty('popupType', 0)
    tip.setProperty('text', 'Tooltip for keyboard isolation')
    tip.setProperty('requested', True)
    wait_until(lambda: tip.property('opened'))
    try:
        assert window.property('standardShortcutsAllowed')
        QTest.keyClick(window, Qt.Key_P)
        assert tab.toolController.activeTool == 'pan'
    finally:
        tip.setProperty('requested', False)
    assert not sidebar_scene[3], sidebar_scene[3]


def test_widget_modal_temporarily_owns_workspace_keys(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    dialog = QDialog()
    dialog.setModal(True)
    dialog.show()
    try:
        wait_until(lambda: QGuiApplication.focusWindow() is dialog.windowHandle())
        assert not window.property('standardShortcutsAllowed')
        QTest.keyClick(dialog, Qt.Key_F12)
        QTest.keyClick(dialog, Qt.Key_P)
        assert dialog.isVisible() and not window.property('maximizedReadingArea')
        assert tab.toolController.activeTool != 'pan'
    finally:
        dialog.close()
    window.requestActivate()
    wait_until(lambda: window.property('standardShortcutsAllowed'))
    QTest.keyClick(window, Qt.Key_P)
    assert tab.toolController.activeTool == 'pan'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_slice_popup_owns_escape_before_tab_drag(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    manager = app.windowManager
    manager.beginDrag('main', tab.tab_config.tab_id, 20, 20)
    manager.updateDrag(80, 90)
    assert manager.dragging
    try:
        click(window, find(window, 'sliceJumpButton'))
        wait_until(lambda: window.property('shortcutPopupOpen'))
        QTest.keyClick(window, Qt.Key_Escape)
        assert not window.property('shortcutPopupOpen') and manager.dragging
        QTest.keyClick(window, Qt.Key_Escape)
        assert not manager.dragging
    finally:
        manager.cancelDrag()
    assert not sidebar_scene[3], sidebar_scene[3]


def test_calendar_choice_and_child_combo_keep_enter_and_escape_local(scene):
    window, app, warnings = scene
    app.pacsController.saveProfile({'name': 'Test', 'url': 'http://127.0.0.1/dicom-web'})
    app.workspaceController.openPacs()
    field = find(window, 'pacsDateFrom')
    field.setProperty('text', '2024-02-29')
    trigger = find(window, 'pacsDateFrom-calendar')
    click(window, trigger)
    calendar = field.findChild(QObject, 'pacsDateFrom-popup')
    wait_until(lambda: calendar.property('opened'))
    assert window.activeFocusItem() == find(window, 'pacsDateFrom-day-29')
    QTest.keyClick(window, Qt.Key_Return)
    assert not calendar.property('visible') and field.property('text') == '2024-02-29'
    click(window, trigger)
    month = find(window, 'pacsDateFrom-month')
    click(window, month)
    child = next(obj for obj in month.children() if obj.inherits('QQuickPopup'))
    wait_until(lambda: child.property('opened'))
    QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: not child.property('visible'))
    assert calendar.property('opened') and month.property('currentIndex') == 2
    click(window, month)
    QTest.keyClick(window, Qt.Key_Escape)
    assert not child.property('visible') and calendar.property('opened')
    year = find(window, 'pacsDateFrom-year')
    click(window, year)
    QTest.keyClick(window, Qt.Key_Escape)
    assert not calendar.property('visible') and field.property('text') == '2024-02-29'
    assert not warnings, warnings


def test_color_swatch_and_corner_editor_use_the_foreground_choice(scene):
    from test_settings_redesign import open_page
    window, app, warnings = open_page(scene, 'measurement')
    settings = app.settingsController
    picker = find(window, 'colorPicker-measurement-editingColor')
    click(window, picker)
    popup = picker.findChild(QObject, 'colorPickerPopup-measurement-editingColor')
    target = find(window, 'colorChoice-measurement-editingColor-22c55e')
    target.forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Return)
    assert not popup.property('visible') and settings.values['measurement']['editingColor'] == '#22c55e'
    click(window, picker)
    assert target.hasActiveFocus()
    QTest.keyClick(window, Qt.Key_Escape)
    assert not popup.property('visible')
    settings.selectCategory('corners')
    click(window, find(window, 'cornerAddOpen-topRight'))
    choice = find(window, 'cornerChoice-topRight')
    before = settings.values['corners']['topRight'][:]
    selected = choice.property('currentValue')
    QTest.keyClick(window, Qt.Key_Return)
    assert settings.values['corners']['topRight'] == [*before, selected]
    assert not window.property('shortcutPopupOpen')
    assert not warnings, warnings


def test_recovery_card_escape_leaves_its_parent_dialog_open(sidebar_scene):
    from test_workspace_dialog_layout import workspace_dialog
    window, app, records, warnings = sidebar_scene
    dialog, native = workspace_dialog(window)
    link = dialog.findChild(QObject, 'workspaceRecoveryLocation')
    click(native, link)
    card = dialog.findChild(QObject, 'workspaceRecoveryLocationPopup')
    wait_until(lambda: card.property('opened'))
    assert card.property('activeFocus')
    QTest.keyClick(native, Qt.Key_Escape)
    assert not card.property('visible') and dialog.property('opened')
    assert not warnings, warnings


def test_modeless_import_keeps_owner_keys_suspended_after_refocus(sidebar_scene):
    from test_import_dialog_chrome import open_progress
    window, app, tab = reading_scene(sidebar_scene)
    panel = app.panelController
    dialog, surface = open_progress(window, panel)
    try:
        window.requestActivate()
        wait_until(lambda: QGuiApplication.focusWindow() is window)
        assert surface.isVisible() and dialog.property('opened')
        assert not window.property('standardShortcutsAllowed')
        QTest.keyClick(window, Qt.Key_P)
        QTest.keyClick(window, Qt.Key_F12)
        assert tab.toolController.activeTool != 'pan'
        assert not window.property('maximizedReadingArea')
    finally:
        panel._set_scanning(False)
        panel.closeImportTask()
    wait_until(lambda: window.property('standardShortcutsAllowed'))
    QTest.keyClick(window, Qt.Key_P)
    assert tab.toolController.activeTool == 'pan'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_sibling_dialog_suspends_compact_palette_choices(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_C)
    palette = find(window, 'pseudoColorPanel')
    old_color = tab.activeViewport.activeColorMap
    choice = palette.property('options').toVariant()[2]['colorMap']
    assert choice != old_color
    app.feedbackController.show()
    feedback = window.findChild(QObject, 'feedbackDialog')
    wait_until(lambda: feedback.property('opened'))
    QTest.keyClick(window, Qt.Key_3)
    QTest.keyClick(window, Qt.Key_F12)
    assert tab.activeViewport.activeColorMap == old_color and not window.property('maximizedReadingArea')
    QTest.keyClick(window, Qt.Key_Escape)
    wait_until(lambda: not feedback.property('visible'))
    if not palette.isVisible():
        QTest.keyClick(window, Qt.Key_C)
        find(window, 'pseudoColorPanel')
    QTest.keyClick(window, Qt.Key_3)
    assert tab.activeViewport.activeColorMap == choice
    assert not sidebar_scene[3], sidebar_scene[3]


def test_help_and_shortcut_recording_release_their_keys(scene):
    from test_settings_redesign import open_page
    window, app, warnings = open_page(scene, 'workspace')
    button = find(window, 'workspaceExitDescription')
    for key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
        click(window, button)
        popup = button.findChild(QObject, 'workspaceExitDescriptionPopup')
        wait_until(lambda: popup.property('opened'))
        QTest.keyClick(window, key)
        assert not popup.property('visible')
    shortcuts = app.shortcutController
    old = shortcuts.hint('pan')
    shortcuts.beginRecording('pan')
    app.feedbackController.show()
    wait_until(lambda: window.property('shortcutPopupOpen'))
    assert not shortcuts.recordingAction
    QTest.keyClick(window, Qt.Key_Escape)
    assert shortcuts.hint('pan') == old and not window.property('shortcutPopupOpen')
    assert not warnings, warnings


def test_enter_triggers_only_highlighted_tab_menu_command(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    session = app.windowManager.mainWorkspace
    session.openSettings()
    assert len(session.tabs) == 2
    right_click(window, find(window, 'workspaceTab-' + tab.tab_config.tab_id))
    menu = window.findChild(QObject, 'tabContextMenu')
    close = menu.findChild(QObject, 'tabMenu-close')
    wait_until(lambda: menu.property('opened'))
    surface = item_window(close)
    for _ in range(menu.property('count')):
        QTest.keyClick(surface, Qt.Key_Down)
        if close.property('highlighted'):
            break
    assert close.property('highlighted')
    QTest.keyClick(surface, Qt.Key_Return)
    wait_until(lambda: not menu.property('visible'))
    assert len(session.tabs) == 1 and session.activeTabType == 'settings'
    assert not sidebar_scene[3], sidebar_scene[3]
