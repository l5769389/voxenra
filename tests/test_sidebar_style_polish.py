"""Visible sidebar actions, stable first tooltip placement and selectable manual content."""
import os
import math
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, QPointF, Qt, QMetaObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_workspace_dialog_layout import workspace_dialog
from qt_pointer import move_pointer
from qt_dicom_viewer.ui.controller.viewport.controller.overlay_presenter import _format_view_position


def open_image(app, record):
    ws = app.workspaceController
    app.panelController.selectSeries(record.series_instance_uid)
    app.settingsController.setValue('layout', 'rightPanelCollapsed', False)
    ws.createTab(record.series_instance_uid, 'Style review', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    return ws.activeViewport


def reveal(window, rail, item):
    point = item.mapToItem(rail.property('contentItem'), QPointF())
    rail.setProperty('contentY', max(0, min(point.y()-10, rail.property('contentHeight')-rail.height())))
    QTest.qWait(50)
    click(window, item)


def test_compact_footer_keeps_export_clear_and_distinct_modality(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    open_image(app, records[0])
    for row in app.panelController.sidebarItems:
        if row['kind'] != 'series':
            arrow = find(window, 'seriesGroupChevron-'+row['key'])
            assert arrow.width() >= 20 and arrow.height() >= 20
    badge = find(window, 'seriesModality-'+records[0].series_instance_uid)
    assert badge.property('label') == 'CT'
    assert badge.height() >= 20
    click(window, find(window, 'sidebarToggle'))
    names = ['sidebarExport','sidebarClear','sidebarWorkspace','sidebarManual','sidebarSettings','sidebarToggle']
    buttons = [find(window, name) for name in names]
    centers = [b.mapToScene(QPointF(b.width()/2,b.height()/2)) for b in buttons]
    assert len({p.x() for p in centers}) == 1
    assert all(centers[i+1].y()-centers[i].y() == 36 for i in range(len(centers)-1))
    assert all(b.isEnabled() for b in buttons)
    assert find(window,'compactModality-'+records[0].series_instance_uid).property('label') == 'CT'
    click(window, buttons[0])
    wait_until(lambda: app.seriesExportController.dialogOpen)
    assert window.grabWindow().save(str(tmp_path/'compact-sidebar-export.png'))
    assert not warnings, warnings


def test_compact_secondary_actions_change_real_view_and_switch_cleanly(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    view = open_image(app, records[0])
    click(window, find(window,'toggleRightPanel'))
    rail = find(window,'compactToolRail')
    reveal(window, rail, find(window,'compactTool-measure'))
    reveal(window, rail, find(window,'compactAction-measure:rect'))
    assert view.activeInteraction == 'measure:rect'
    assert find(window,'rightPanel').property('collapsed')
    assert window.grabWindow().save(str(tmp_path/'compact-measure.png'))
    reveal(window, rail, find(window,'compactTool-rotate'))
    initial = view.viewport_state.rotation_degrees
    reveal(window, rail, find(window,'compactAction-rotate:cw90'))
    assert view.viewport_state.rotation_degrees != initial
    reveal(window, rail, find(window,'compactTool-pseudocolor'))
    name = next(o['colorMap'] for o in view.colorMapOptions if o['colorMap'] != view.activeColorMap)
    popup = window.findChild(QObject, 'compactPalettePopup')
    assert popup is not None and popup.property('visible')
    assert window.grabWindow().save(str(tmp_path/'compact-palette-open.png'))
    anchor = find(window, 'compactTool-pseudocolor').mapToScene(QPointF())
    assert rail.mapToScene(QPointF(popup.property('x') + popup.property('width'), 0)).x() <= anchor.x()
    assert not next(x for x in descendants(window.contentItem()) if x.objectName() == 'compactGroup-pseudocolor').isVisible()
    click(window, find(window,'compactAction-'+name))
    assert not popup.property('visible')
    assert view.activeColorMap == name
    assert window.grabWindow().save(str(tmp_path/'compact-pseudocolor.png'))
    reveal(window, rail, find(window,'compactTool-annotate'))
    reveal(window, rail, find(window,'compactAction-annotate:text'))
    assert view.activeInteraction == 'annotate:text'
    reveal(window, rail, find(window,'compactTool-pan'))
    assert view.activeInteraction == 'pan' and rail.property('expandedTool') == ''
    click(window, find(window,'toggleRightPanel'))
    assert not warnings, warnings


@pytest.mark.parametrize('theme,locale', [('graphite', 'zh-CN'), ('light', 'en-US')])
def test_compact_palette_is_bounded_and_escape_closes(sidebar_scene, theme, locale, tmp_path):
    window, app, records, warnings = sidebar_scene
    open_image(app, records[0])
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    window.resize(1280, 720)
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    reveal(window, rail, find(window, 'compactTool-pseudocolor'))
    popup = window.findChild(QObject, 'compactPalettePopup')
    assert popup.property('visible')
    position = rail.mapToScene(QPointF(popup.property('x'), popup.property('y')))
    assert position.y() >= 0
    assert position.y() + popup.property('height') <= window.height()
    assert position.x() + popup.property('width') <= rail.mapToScene(QPointF()).x()
    assert find(window, 'toolFlyoutHeader').height() == 24
    assert window.grabWindow().save(str(tmp_path / 'palette-flyout.png'))
    trigger = find(window, 'compactTool-pseudocolor')
    # Press must not auto-dismiss before release fires the toggle handler.
    point = trigger.mapToScene(QPointF(trigger.width()/2, trigger.height()/2)).toPoint()
    for _ in range(3):
        QTest.mousePress(window, Qt.LeftButton, pos=point)
        QTest.qWait(25)
        assert popup.property('visible')
        QTest.mouseRelease(window, Qt.LeftButton, pos=point)
        QTest.qWait(50)
        assert not popup.property('visible')
        click(window, trigger)
        assert popup.property('visible')
    click(window, find(window, 'compactPalettePopupClose'))
    assert not popup.property('visible')
    click(window, trigger)
    QTest.mouseClick(window, Qt.LeftButton, pos=QPointF(600, 400).toPoint())
    QTest.qWait(40)
    assert not popup.property('visible')
    click(window, trigger)
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(30)
    assert not popup.property('visible') and rail.property('expandedTool') == ''
    assert not warnings, warnings


def test_manual_body_is_selectable_copyable_and_has_no_duplicate_title(sidebar_scene, tmp_path):
    window, app, _, warnings = sidebar_scene
    app.workspaceController.openManual('quick-start')
    QTest.qWait(100)
    manual = find(window,'operationManual')
    assert not any(i.property('text') == '操作手册' for i in descendants(manual))
    for name in ('manualChapterTitle','manualChapterSummary','manualSectionBody-0'):
        item = find(window,name)
        assert item.property('readOnly') and item.property('selectByMouse')
    body = find(window,'manualSectionBody-0')
    body.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    assert body.property('selectedText')
    previous = QGuiApplication.clipboard().text()
    try:
        QTest.keyClick(window, Qt.Key_C, Qt.ControlModifier)
        assert QGuiApplication.clipboard().text() == body.property('selectedText')
    finally:
        QGuiApplication.clipboard().setText(previous)
    assert window.grabWindow().save(str(tmp_path/'manual-selection.png'))
    assert not warnings, warnings


def test_recovery_location_hover_copy_and_open_closes_card(sidebar_scene, tmp_path, monkeypatch):
    window, app, _, warnings = sidebar_scene
    manager = app.workspaceDocumentController
    dialog, native = workspace_dialog(window)
    QTest.qWait(100)
    native.requestActivate()
    QTest.qWait(80)
    link = dialog.findChild(QObject,'workspaceRecoveryLocation')
    point = link.mapToScene(QPointF(link.width()/2,link.height()/2)).toPoint()
    move_pointer(native, point)
    card = dialog.findChild(QObject,'workspaceRecoveryLocationPopup')
    wait_until(lambda: card.property('visible'))
    # A native popup may steal the link's hover and close after 250 ms.
    # Check continuous visibility before moving the pointer into the card.
    for _ in range(10):
        QTest.qWait(100)
        assert card.property('visible')
    full = card.findChild(QObject,'workspaceRecoveryFullPath')
    assert full.property('text') == str(manager._recovery_path)
    assert card.findChild(QObject,'workspaceRecoveryOpen').property('text') == '打开位置'
    assert card.findChild(QObject,'workspaceRecoveryCopy').property('text') == '复制路径'
    popup = full.window()
    background = card.property('background')
    # Keep the card open while the pointer is on its bottom/right padding.
    move_pointer(popup, background.mapToScene(QPointF(background.width()-3, background.height()-3)).toPoint())
    QTest.qWait(350)
    assert card.property('visible')
    copy = card.findChild(QObject,'workspaceRecoveryCopy')
    move_pointer(popup, copy.mapToScene(QPointF(copy.width()/2,copy.height()/2)).toPoint())
    QTest.qWait(300)
    assert card.property('visible')
    previous = QGuiApplication.clipboard().text()
    try:
        click(popup, copy)
        assert QGuiApplication.clipboard().text() == str(manager._recovery_path)
    finally:
        QGuiApplication.clipboard().setText(previous)
    assert popup.grabWindow().save(str(tmp_path/'workspace-location-card.png'))
    opened = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.workspace_document_controller.reveal_path',lambda path: opened.append(path) or True)
    click(popup, card.findChild(QObject,'workspaceRecoveryOpen'))
    wait_until(lambda: not card.property('visible'))
    assert opened == [str(manager._recovery_path.parent)]
    assert dialog.property('visible')
    assert not warnings, warnings


@pytest.mark.parametrize('angle,expected', [(0,'Axial'),(.001,'Axial'),(1,'Oblique'),(30,'Oblique'),(90,'Coronal')])
def test_plane_name_follows_actual_geometry_instead_of_viewport_slot(angle, expected):
    a=math.radians(angle)
    value=_format_view_position('axial',(0,0,10),(1,0,0,0,math.cos(a),math.sin(a)))
    assert value.startswith(expected+','), value


@pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM') == 'offscreen',reason='Native first-exposure positioning needs a desktop window')
def test_sidebar_tooltip_is_on_right_from_first_exposure(sidebar_scene, tmp_path):
    window, app, _, warnings = sidebar_scene
    click(window, find(window,'sidebarToggle'))
    button=find(window,'sidebarSettings')
    action=button.parentItem()
    tip=next(c for c in action.children() if c.objectName()=='toolbarTooltip')
    observed=[]
    def sample():
        label=tip.property('contentItem')
        if label.window() and label.window().isVisible():
            observed.append(label.window().geometry())
    tip.visibleChanged.connect(sample)
    label=tip.property('contentItem')
    label.windowChanged.connect(lambda *_: sample())
    move_pointer(window, button.mapToScene(QPointF(button.width()/2,button.height()/2)).toPoint())
    wait_until(lambda: tip.property('visible'))
    for _ in range(10):
        sample();QTest.qWait(12)
    assert observed
    anchor=button.mapToGlobal(QPointF(button.width(),button.height()/2))
    assert all(rect.x() >= anchor.x() and rect.top() <= anchor.y() <= rect.bottom() for rect in observed), observed
    assert len({(r.x(),r.y()) for r in observed}) == 1, observed
    assert label.window().grabWindow().save(str(tmp_path/'sidebar-tooltip.png'))
    click(window,button)
    assert not tip.property('visible')
    assert app.workspaceController.activeTabType=='settings'
    assert not warnings,warnings


def test_mpr_rotation_updates_visible_plane_names_and_reset_restores(sidebar_scene, tmp_path):
    from qt_dicom_viewer.model import MprPlane
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Oblique review', 'mpr')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    def settled():
        wait_until(lambda: not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids, timeout=10000)
    def names():
        return {v.viewportType: v.overlayInfo['viewPosition'].split(',')[0] for v in tab.viewports_by_id.values()}
    settled()
    original = names()
    assert set(original.values()) == {'Axial','Coronal','Sagittal'}
    tab._handle_crosshair_rotation_requested(MprPlane.AXIAL, math.radians(23))
    settled()
    assert names() == {'axial':'Axial','coronal':'Oblique','sagittal':'Oblique'}
    tab._handle_mpr_3d_rotation_requested((1.,0.,0.), math.radians(17))
    settled()
    assert set(names().values()) == {'Oblique'}
    QTest.qWait(80)
    assert window.grabWindow().save(str(tmp_path/'mpr-oblique-names.png'))
    tab._handle_mpr_3d_rotation_requested((1.,0.,0.), -math.radians(17))
    tab._handle_crosshair_rotation_requested(MprPlane.AXIAL, -math.radians(23))
    settled()
    assert names() == original
    assert not warnings,warnings


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_compact_reset_restores_all_view_state(sidebar_scene, tmp_path, theme):
    from test_workspace_persistence import draw_length
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    view = open_image(app, records[0])
    initial_style = view.viewport_state.display_style
    draw_length(view)
    view.apply_pan(12, -7)
    view.setZoom(1.5)
    view.applyTransformAction('rotate:cw90')
    view.applyColorMap('blackbody')
    assert view._measure_controller._measurements
    assert view.viewport_state.rotation_degrees != 0
    assert view.viewport_state.display_style != initial_style
    click(window, find(window, 'sidebarToggle'))
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    reveal(window, rail, find(window, 'compactTool-rotate'))
    QTest.qWait(80)
    assert window.grabWindow().save(str(tmp_path / f'compact-groups-{theme}.png'))
    # Reset all must clear unrelated state even when only Pan is selected.
    reveal(window, rail, find(window, 'compactTool-pan'))
    reset = find(window, 'compactToolReset')
    assert reset.parentItem().property('label') == '重置所有'
    assert reset.isEnabled()
    click(window, reset)
    QTest.qWait(80)
    state = view.viewport_state
    assert (state.pan_x, state.pan_y, state.zoom, state.rotation_degrees) == (0, 0, 1, 0)
    assert state.display_style == initial_style
    assert not view._measure_controller._measurements
    assert window.grabWindow().save(str(tmp_path / f'compact-reset-all-{theme}.png'))
    # Expanded detail reset remains scoped to the active tool.
    click(window, find(window, 'toggleRightPanel'))
    view.apply_pan(4, 9)
    view.setZoom(1.5)
    click(window, find(window, 'activeToolReset'))
    assert (view.viewport_state.pan_x, view.viewport_state.pan_y) == (0, 0)
    assert view.viewport_state.zoom == 1.5
    assert not warnings, warnings


def test_compact_layout_and_palette_switch_without_reopening(sidebar_scene, tmp_path):
    from test_mpr_volume_tools_qml import item_window
    window, app, records, warnings = sidebar_scene
    open_image(app, records[0])
    window.resize(1280, 720)
    click(window, find(window, 'toggleRightPanel'))
    layout = window.findChild(QObject, 'compactVolumePanel')
    palette = window.findChild(QObject, 'compactPalettePopup')
    trigger = find(window, 'compactTool-mpr-layout')
    for _ in range(3):
        click(window, trigger)
        assert layout.property('visible')
        click(window, trigger)
        assert not layout.property('visible')
    click(window, trigger)
    header = next(i for i in descendants(layout.property('contentItem'))
                  if i.objectName() == 'toolFlyoutHeader')
    assert header.height() == 24
    native = item_window(header)
    assert native.grabWindow().save(str(tmp_path / 'layout-flyout.png'))
    click(window, find(window, 'compactTool-pseudocolor'))
    assert palette.property('visible') and not layout.property('visible')
    click(window, trigger)
    assert layout.property('visible') and not palette.property('visible')
    # Outside dismissal must still allow the next deliberate click to open.
    QTest.mouseClick(window, Qt.LeftButton, pos=QPointF(600, 400).toPoint())
    QTest.qWait(50)
    assert not layout.property('visible')
    click(window, trigger)
    assert layout.property('visible')
    click(window, find(window, 'compactTool-pan'))
    assert not layout.property('visible')
    assert not warnings, warnings
