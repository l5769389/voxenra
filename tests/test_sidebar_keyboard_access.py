"""Keyboard navigation must reveal virtualized rows and clipped toolbar actions."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QGuiApplication, QAccessible, QAccessibleActionInterface
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_sidebar_style_polish import open_image
from test_tag_qml import find, click, descendants
from qt_pointer import move_pointer
from qt_dicom_viewer.model import DicomFolderScanSnapshot


@pytest.fixture(autouse=True)
def all_controls_keyboard(qt_app):
    hints = QGuiApplication.styleHints()
    previous = hints.tabFocusBehavior()
    hints.setTabFocusBehavior(Qt.TabFocusAllControls)
    yield
    hints.setTabFocusBehavior(previous)


@pytest.fixture(autouse=True)
def active_sidebar_window(sidebar_scene):
    window = sidebar_scene[0]
    window.requestActivate()
    wait_until(window.isActive)


def assert_revealed(item, viewport):
    top = item.mapToItem(viewport, QPointF()).y()
    assert -1 <= top and top + item.height() <= viewport.height() + 1, (item.objectName(), top, item.height(), viewport.height())


@pytest.mark.parametrize('compact', [False, True])
def test_long_series_keyboard_reaches_every_row_and_activates(sidebar_scene, tmp_path, compact):
    window, app, records, warnings = sidebar_scene
    window.resize(1280, 720)
    many = [replace(records[0], series_instance_uid=f'1.2.826.9.{i}', series_number=i,
                    series_description=f'Keyboard series {i:03d}') for i in range(40)]
    panel = app.panelController
    panel.clearSeries()
    snapshot = DicomFolderScanSnapshot(tmp_path, 120, 120, 0, many)
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    QTest.qWait(150)
    if compact:
        click(window, find(window, 'sidebarToggle'))
    listing = find(window, 'compactSidebarSeriesList' if compact else 'sidebarSeriesList')
    prefix = 'compactSeries-' if compact else 'series-'
    preceding = find(window, 'compactSidebarPacs' if compact else 'sidebarPatientSearch')
    preceding.forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Tab)
    QTest.qWait(30)
    if not compact:
        assert window.activeFocusItem().objectName().startswith('sidebar-patient-')
        QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Down)
    assert window.activeFocusItem().objectName() == prefix + many[0].series_instance_uid
    for record in many:
        focus = window.activeFocusItem()
        assert focus.objectName() == prefix + record.series_instance_uid
        assert_revealed(focus, listing)
        QTest.keyClick(window, Qt.Key_Tab)
        QTest.qWait(25)
    # The last row must allow Tab to leave the list, not trap keyboard users.
    assert not window.activeFocusItem().objectName().startswith(prefix)
    QTest.keyClick(window, Qt.Key_Backtab)
    QTest.qWait(30)
    assert window.activeFocusItem().objectName() == prefix + many[-1].series_instance_uid
    QTest.keyClick(window, Qt.Key_Space)
    assert many[-1].series_instance_uid in panel.selectedSeriesUids
    assert window.grabWindow().save(str(tmp_path / f'series-keyboard-{compact}.png'))
    for record in reversed(many[:-1]):
        QTest.keyClick(window, Qt.Key_Backtab)
        QTest.qWait(25)
        assert window.activeFocusItem().objectName() == prefix + record.series_instance_uid
        assert_revealed(window.activeFocusItem(), listing)
    QTest.keyClick(window, Qt.Key_Home)
    QTest.qWait(40)
    if not compact:
        assert window.activeFocusItem().objectName().startswith('sidebar-patient-')
        QTest.keyClick(window, Qt.Key_Down)  # Study heading
        QTest.keyClick(window, Qt.Key_Down)  # First series
    assert window.activeFocusItem().objectName() == prefix + many[0].series_instance_uid
    QTest.keyClick(window, Qt.Key_End)
    QTest.qWait(40)
    assert window.activeFocusItem().objectName() == prefix + many[-1].series_instance_uid
    assert_revealed(window.activeFocusItem(), listing)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: app.workspaceController.activeTabType == '2d')
    assert app.workspaceController.activeViewport.viewport_config.series_uid == many[-1].series_instance_uid
    assert not warnings, warnings


def test_compact_series_accessible_press_and_toggle_match_keyboard(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    click(window, find(window, 'sidebarToggle'))
    entry = find(window, 'compactSeries-' + records[0].series_instance_uid)
    interface = QAccessible.queryAccessibleInterface(entry)
    assert interface is not None
    assert interface.role() == QAccessible.Button
    assert records[0].series_description in interface.text(QAccessible.Name)
    actions = interface.actionInterface()
    press = QAccessibleActionInterface.pressAction()
    toggle = QAccessibleActionInterface.toggleAction()
    assert press in actions.actionNames() and toggle in actions.actionNames()
    actions.doAction(toggle)
    assert records[0].series_instance_uid in app.panelController.selectedSeriesUids
    actions.doAction(press)
    wait_until(lambda: app.workspaceController.activeTabType == '2d')
    assert not warnings, warnings


def test_compact_toolbar_tab_reveals_and_activates_last_action(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    open_image(app, records[0])
    window.resize(1280, 720)
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    find(window, 'compactTool-window').forceActiveFocus(Qt.TabFocusReason)
    for _ in range(30):
        focus = window.activeFocusItem()
        assert_revealed(focus, rail)
        if focus.objectName() == 'compactTool-viewport-settings':
            break
        QTest.keyClick(window, Qt.Key_Tab)
        QTest.qWait(30)
    else:
        pytest.fail('Viewport settings was not reachable with Tab')
    assert rail.property('contentY') > 0
    assert window.grabWindow().save(str(tmp_path / 'toolbar-keyboard-last.png'))
    QTest.keyClick(window, Qt.Key_Space)
    assert app.workspaceController.activeTab.toolController.activeTool == 'viewport-settings'
    assert not warnings, warnings


def test_primary_export_keeps_light_icon_on_hover_and_press(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    app.panelController.selectSeries(records[0].series_instance_uid)
    app.settingsController.setValue('appearance', 'theme', 'light')
    button = find(window, 'sidebarExport')
    glyph = next(item for item in descendants(button) if item.objectName() == 'toolbarGlyph')
    outside = QPointF(600, 300).toPoint()
    move_pointer(window, outside)
    QTest.qWait(60)
    normal = glyph.property('iconColor')
    label = next(item for item in descendants(button) if item.objectName() == 'toolbarLabel')
    assert normal.lightnessF() > .95
    assert label.property('color') == normal
    center = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
    move_pointer(window, center)
    QTest.qWait(80)
    assert button.property('hovered')
    assert glyph.property('iconColor') == normal
    assert label.property('color') == normal
    QTest.mousePress(window, Qt.LeftButton, pos=center)
    QTest.qWait(40)
    assert button.property('down')
    assert glyph.property('iconColor') == normal
    assert label.property('color') == normal
    assert window.grabWindow().save(str(tmp_path / 'export-primary-pressed.png'))
    move_pointer(window, outside)
    QTest.mouseRelease(window, Qt.LeftButton, pos=outside)
    assert not warnings, warnings


def test_compact_palette_keyboard_reveals_last_color(sidebar_scene, tmp_path):
    from PySide6.QtCore import QObject
    from test_sidebar_style_polish import reveal
    window, app, records, warnings = sidebar_scene
    view = open_image(app, records[0])
    window.resize(1280, 720)
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    reveal(window, rail, find(window, 'compactTool-pseudocolor'))
    popup = window.findChild(QObject, 'compactPalettePopup')
    first = find(window, 'compactAction-' + view.colorMapOptions[0]['colorMap'])
    scroll = first.parentItem()
    while scroll is not None and scroll.property('contentY') is None:
        scroll = scroll.parentItem()
    assert scroll is not None
    first.forceActiveFocus(Qt.TabFocusReason)
    last_name = 'compactAction-' + view.colorMapOptions[-1]['colorMap']
    for _ in range(len(view.colorMapOptions) + 3):
        focus = window.activeFocusItem()
        assert_revealed(focus, scroll)
        if focus.objectName() == last_name:
            break
        QTest.keyClick(window, Qt.Key_Tab)
        QTest.qWait(25)
    else:
        pytest.fail('Last color map was not reachable')
    assert window.grabWindow().save(str(tmp_path / 'palette-keyboard-last.png'))
    QTest.keyClick(window, Qt.Key_Space)
    assert view.activeColorMap == view.colorMapOptions[-1]['colorMap']
    assert not popup.property('visible')
    assert not warnings, warnings
