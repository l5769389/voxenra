"""Maximize the reading area without changing its document or saved layout."""
from copy import deepcopy
from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, find
from test_tab_windows import detached, open_tabs
from test_workspace_persistence import draw_length
from qt_dicom_viewer.model import MeasurementKind


@pytest.mark.parametrize('collapsed', [False, True])
def test_maximize_restores_layout_and_keeps_image_edits(sidebar_scene, tmp_path, collapsed):
    window, app, records, warnings = sidebar_scene
    tab = open_tabs(app, records[:1])[0]
    doc = app.workspaceDocumentController
    doc._autosave.stop()
    sidebar = find(window, 'sidebarContainer')
    right = find(window, 'rightPanel')
    sidebar.setProperty('expandedWidth', 280)
    sidebar.setProperty('collapsed', collapsed)
    app.settingsController.setValue('layout', 'rightPanelWidth', 280)
    app.settingsController.setValue('layout', 'rightPanelCollapsed', collapsed)
    tab.activeViewport.setSliceIndex(2)
    wait_until(lambda: tab.activeViewport._state.slice_index == 2)
    wait_until(lambda: tab.activeViewport._measurement_context(3, 2, kind=MeasurementKind.LENGTH) is not None)
    draw_length(tab.activeViewport)
    tab.historyController.capture()
    # Save first so an unwanted dirty-state change caused by hiding panels is detected.
    assert doc.save_to(tmp_path / 'maximized.voxworkspace')
    wait_until(lambda: not doc.busy)
    layout = deepcopy(app.settingsController.section('layout'))
    left_layout = dict(doc.sidebarLayout)
    state = tab.activeViewport._state
    measurements = deepcopy(tab.activeViewport._measure_controller._measurements)
    area = find(window, 'workspaceLoader')
    original_width = area.width()
    toggle = window.findChild(QObject, 'toggleViewportMaximize')
    assert toggle is not None, 'A fixed maximize/restore action must remain beside the tabs'
    click(window, toggle)
    wait_until(lambda: not sidebar.isVisible() and not right.isVisible())
    assert area.width() > original_width
    assert toggle.isVisible() and toggle.property('checked')
    assert not window.findChild(QObject, 'rightPanelResizeHandle').isVisible()
    assert not doc.dirty
    resized = tab.activeViewport._state
    assert replace(resized, width=state.width, height=state.height) == state
    assert tab.activeViewport._measure_controller._measurements == measurements
    assert window.grabWindow().save(str(tmp_path / f'maximized-{collapsed}.png'))
    click(window, toggle)
    wait_until(lambda: sidebar.isVisible() and right.isVisible())
    assert area.width() == original_width
    assert app.settingsController.section('layout') == layout
    assert doc.sidebarLayout == left_layout
    assert not doc.dirty
    assert not warnings, warnings


def test_maximize_suspends_for_settings_and_is_window_local(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    first, second = open_tabs(app, records[:2])
    toggle = window.findChild(QObject, 'toggleViewportMaximize')
    assert toggle is not None
    click(window, toggle)
    app.workspaceController.openSettings()
    wait_until(lambda: app.windowManager.mainWorkspace.activeTabType == 'settings')
    sidebar = window.findChild(QObject, 'sidebarContainer')
    assert sidebar.isVisible() and not toggle.isVisible()
    app.workspaceController.activateTabId(second.tab_config.tab_id)
    wait_until(lambda: not sidebar.isVisible())
    session, other = detached(app, first)
    other_right = find(other, 'rightPanel')
    assert not other.property('viewportMaximized')
    click(other, find(other, 'toggleViewportMaximize'))
    assert not other_right.isVisible()
    click(window, find(window, 'toggleViewportMaximize'))
    assert sidebar.isVisible() and not other_right.isVisible()
    app.windowManager.moveToMain(first.tab_config.tab_id)
    wait_until(lambda: session.windowId not in app.windowManager.sessions)
    assert not warnings, warnings


def test_maximize_shortcut_keeps_escape_available_to_editing(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    open_tabs(app, records[:1])
    toggle = window.findChild(QObject, 'toggleViewportMaximize')
    assert toggle is not None
    window.requestActivate()
    wait_until(window.isActive)
    QTest.keyClick(window, Qt.Key_F12)
    wait_until(lambda: toggle.property('checked'))
    QTest.keyClick(window, Qt.Key_Escape)
    assert toggle.property('checked')
    QTest.keyClick(window, Qt.Key_F12)
    wait_until(lambda: not toggle.property('checked'))
    assert not warnings, warnings
