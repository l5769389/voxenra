"""Exercise actual Qt controls and capture theme states for visual review."""
from copy import deepcopy
import os
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlProperty

from qt_dicom_viewer.ui.theme_palette import palette_for
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, find
from test_workspace_persistence import draw_length


def capture(window, name, tmp_path):
    destination = Path(os.environ.get('THEME_REVIEW_OUTPUT', tmp_path))
    destination.mkdir(parents=True, exist_ok=True)
    image = window.grabWindow() if hasattr(window, 'grabWindow') else window.grab().toImage()
    assert not image.isNull()
    assert image.save(str(destination / (name + '.png')))


def test_theme_switch_controls_dialogs_and_image_state(sidebar_scene, qt_app, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1280, 800)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Theme review CT', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    view = ws.activeViewport
    image_tab = ws.activeTab
    find(window, "dicomPixelLayer")
    assert not window.grabWindow().isNull()
    wait_until(lambda: view._state.width > 100 and view._state.height > 100)
    draw_length(view)
    click(window, find(window, 'series-' + records[0].series_instance_uid))
    initial_state = deepcopy(view._state)
    initial_measurements = deepcopy(view._measure_controller._measurements)
    click(window, find(window, 'sidebarSettings'))
    click(window, find(window, 'settingsCategory-appearance'))
    QTest.qWait(150)
    choices = [find(window, 'themeChoice-' + key) for key in ('dark', 'graphite', 'light')]
    assert len({round(item.mapToScene(QPointF()).y()) for item in choices}) == 1
    app.workspaceDocumentController._autosave.stop()
    app.workspaceDocumentController._dirty = False
    for theme in ('light', 'dark', 'graphite'):
        button = find(window, 'themeChoice-' + theme)
        center = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
        QTest.mouseMove(window, center)
        QTest.qWait(80)
        assert button.property('hovered')
        capture(window, theme + '-hover', tmp_path)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
        assert button.property('down')
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center)
        QTest.qWait(120)
        assert button.property('checked')
        assert app.appearanceController.theme == theme
        assert app.settingsController.values['appearance']['theme'] == theme
        palette = palette_for(theme)
        assert qt_app.palette().color(QPalette.Window).name() == palette['panelBackground']
        assert view._state == initial_state
        assert view._measure_controller._measurements == initial_measurements
        assert not app.workspaceDocumentController.dirty
        capture(window, theme + '-settings', tmp_path)
        dialog = LocalImportDialog(str(tmp_path))
        try:
            dialog.show(); QTest.qWait(100)
            assert palette['panelBackground'] in dialog.styleSheet()
            assert dialog.open_button.isEnabled()
            capture(dialog, theme + '-import', tmp_path)
            QTest.mouseClick(dialog.cancel_button, Qt.LeftButton)
            assert not dialog.isVisible()
        finally:
            dialog.close(); dialog.deleteLater()
        # QML dialog uses the same source as QWidget dialogs.
        click(window, find(window, 'sidebarExport'))
        popup = window.findChild(QObject, 'exportDialog')
        assert popup.property('visible')
        assert popup.property('background').property('color').name() == palette['panelBackgroundStrong']
        capture(window, theme + '-export', tmp_path)
        click(window, find(window, 'exportDialogClose'))
        assert not app.seriesExportController.dialogOpen
    restored = SettingsController(path=app.settingsController._path)
    assert restored.values['appearance']['theme'] == 'graphite'
    window.resize(1000, 640); QTest.qWait(100)
    capture(window, 'graphite-compact-settings', tmp_path)
    assert find(window, 'themeChoice-light').isVisible()
    app.languageController.selectLanguage('en-US')
    QTest.qWait(80)
    capture(window, 'graphite-compact-english', tmp_path)
    window.resize(1280, 800)
    click(window, find(window, 'workspaceTab-' + image_tab.tab_config.tab_id))
    click(window, find(window, 'primaryTool-measure'))
    QTest.qWait(100)
    assert ws.activeViewport is view
    assert view._state == initial_state
    assert view._measure_controller._measurements == initial_measurements
    border = find(window, 'viewportSelectionBorder')
    assert QQmlProperty(border, 'border.color').read().name() == palette_for('graphite')['viewportActiveBorder']
    assert QQmlProperty(border, 'border.width').read() == 2
    count = find(window, 'seriesCount-' + records[0].series_instance_uid)
    assert count.property('color').name() == palette_for('graphite')['textSecondary']
    capture(window, 'graphite-viewer', tmp_path)
    assert not warnings, warnings


def test_manual_figure_repaints_on_live_theme_switch(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1280, 800)
    ws = app.workspaceController
    ws.openManual('voi')
    figure = find(window, 'voiManualFigure')
    reading = find(window, 'manualReadingArea')
    QTest.qWait(150)
    # Position the diagram in the reading area to inspect its actual pixels.
    position = figure.mapToItem(reading, QPointF(0, 0))
    reading.setProperty('contentY', max(0, reading.property('contentY') + position.y() - 60))
    for theme in ('light', 'dark', 'graphite'):
        app.settingsController.setValue('appearance', 'theme', theme)
        QTest.qWait(120)
        image = window.grabWindow()
        point = figure.mapToScene(QPointF(4, 4))
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(point.x()*scale), round(point.y()*scale)).name() == palette_for(theme)['diagramBackground']
        capture(window, theme + '-manual', tmp_path)
    assert not warnings, warnings
