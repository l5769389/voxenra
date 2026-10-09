"""Window limits reserve usable image space, including small-screen adaptation."""
import pytest
from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtTest import QTest
from shiboken6 import delete, isValid
from test_dicom_tags import (
    qt_app as qt_app,  # noqa: PLC0414 - register the shared pytest fixture
)
from test_dicom_tags import wait_until
from test_resizable_view_layout import drag
from test_series_sidebar import drag_width
from test_series_sidebar import (
    sidebar_scene as sidebar_scene,  # noqa: PLC0414 - shared pytest fixture
)
from test_tab_windows import detached
from test_tag_qml import click, find
from test_two_d_layout import open_scene

from qt_dicom_viewer.ui.window_geometry import WindowGeometry


def test_destroying_sized_windows_does_not_invalidate_shared_screens(qt_app):
    screens = QGuiApplication.screens()
    for _ in range(3):
        window = QWindow()
        geometry = WindowGeometry(window)
        geometry.shutdown()
        delete(window)
        assert all(isValid(screen) and not screen.availableGeometry().isEmpty() for screen in screens)


def assert_reading_area(window):
    area = find(window, 'workspaceLoader')
    assert area.width() >= window.property('minimumReadingWidth')
    assert area.height() >= window.property('minimumReadingHeight')
    corner = area.mapToScene(QPointF(area.width(), area.height()))
    assert corner.x() <= window.width() - 10
    assert corner.y() <= window.height() - 10
    return area


def test_default_and_minimum_window_keep_four_viewports_usable(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    assert (window.width(), window.height()) == (1440, 900)
    assert (window.minimumWidth(), window.minimumHeight()) == (1280, 720)
    assert QGuiApplication.screenAt(window.position()).availableGeometry().contains(window.frameGeometry())
    layout.setLayout('2x2')
    for index in range(1, 4):
        assert layout.loadSeries(index, records[0].series_instance_uid)
        wait_until(lambda: tab.activeViewport.loadState == 'ready')
    assert window.grabWindow().save(str(tmp_path / 'default-four-views.png'))
    window.resize(1, 1)
    QTest.qWait(100)
    assert (window.width(), window.height()) == (1280, 720)
    assert_reading_area(window)
    for index in range(4):
        cell = find(window, f'twoDCell-{index}')
        assert cell.width() >= 318 and cell.height() >= 258
        assert not find(window, f'twoDPlane-{index}').property('contentItem').property('truncated')
    assert window.grabWindow().save(str(tmp_path / 'minimum-four-views.png'))
    assert not warnings, warnings


def test_sidebar_drags_and_collapse_cannot_take_reserved_image_space(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    open_scene(app, records)
    window.resize(1280, 720)
    QTest.qWait(60)
    drag_width(window, 350)
    drag(window, 'rightPanelResizeHandle', -300)
    assert_reading_area(window)
    assert find(window, 'sidebarContainer').width() == 348
    assert find(window, 'rightPanel').width() == 240
    click(window, find(window, 'sidebarToggle'))
    click(window, find(window, 'toggleRightPanel'))
    assert_reading_area(window)
    assert (window.minimumWidth(), window.minimumHeight()) == (1280, 720)
    click(window, find(window, 'sidebarToggle'))
    click(window, find(window, 'toggleRightPanel'))
    assert_reading_area(window)
    assert not warnings, warnings


@pytest.mark.parametrize('size,left_compact,right_compact', [
    ((1366, 728), False, False), ((1024, 700), True, False), ((800, 600), True, True),
])
def test_small_desktop_fits_without_overwriting_panel_preferences(sidebar_scene, monkeypatch, tmp_path,
                                                                 size, left_compact, right_compact):
    window, app, records, warnings = sidebar_scene
    open_scene(app, records)
    app.settingsController.setValue('layout', 'rightPanelWidth', 420)
    sidebar = find(window, 'sidebarContainer')
    sidebar.setProperty('expandedWidth', 350)
    preferences = dict(app.workspaceDocumentController.sidebarLayout)
    geometry = app.windowManager._window_geometry['main']
    real_area = geometry.client_area()
    desktop = QRect(real_area.topLeft(), real_area.size())
    desktop.setWidth(size[0])
    desktop.setHeight(size[1])
    monkeypatch.setattr(geometry, 'client_area', lambda: desktop)
    geometry.fit()
    QTest.qWait(80)
    assert desktop.contains(window.geometry())
    assert window.width() >= window.minimumWidth() and window.height() >= window.minimumHeight()
    assert_reading_area(window)
    assert sidebar.property('compact') == left_compact
    assert find(window, 'rightPanel').property('collapsed') == right_compact
    assert not sidebar.property('collapsed')
    assert not app.settingsController.values['layout']['rightPanelCollapsed']
    assert app.settingsController.values['layout']['rightPanelWidth'] == 420
    assert app.workspaceDocumentController.sidebarLayout == preferences
    if left_compact:
        assert not find(window, 'sidebarToggle').isEnabled()
    if right_compact:
        assert not find(window, 'toggleRightPanel').isEnabled()
    assert window.grabWindow().save(str(tmp_path / 'small-desktop.png'))
    monkeypatch.setattr(geometry, 'client_area', lambda: real_area)
    geometry.fit()
    geometry.initialize()
    wait_until(lambda: sidebar.width() == 350)
    assert not sidebar.property('compact')
    assert sidebar.width() == 350
    assert not find(window, 'rightPanel').property('collapsed')
    window.resize(1600, 900)
    wait_until(lambda: find(window, 'rightPanel').width() == 420)
    assert_reading_area(window)
    assert not warnings, warnings


def test_detached_window_uses_same_reading_minimum(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    tab, _ = open_scene(app, records)
    session, other = detached(app, tab)
    assert (other.width(), other.height()) == (1120, 840)
    assert (other.minimumWidth(), other.minimumHeight()) == (960, 720)
    other.resize(1, 1)
    QTest.qWait(80)
    assert (other.width(), other.height()) == (960, 720)
    assert_reading_area(other)
    assert other.grabWindow().save(str(tmp_path / 'detached-minimum.png'))
    app.windowManager.moveToMain(tab.tab_config.tab_id)
    wait_until(lambda: session.windowId not in app.windowManager.sessions)
    assert_reading_area(window)
    assert not warnings, warnings
