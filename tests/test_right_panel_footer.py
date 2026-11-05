"""Footer commands remain reachable alongside long lists in the reading sidebar."""
import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, descendants, find
from test_window_sizing import fit_desktop
from test_window_template_scroll import wheel


@pytest.mark.parametrize('height,theme', [(720, 'dark'), (480, 'light')])
def test_palette_list_cannot_displace_the_footer(sidebar_scene, monkeypatch, tmp_path, height, theme):
    window, app, tab = reading_scene(sidebar_scene)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    fit_desktop(window, app, monkeypatch, (1280, height))
    view = tab.activeViewport
    view.setZoom(2)
    click(window, find(window, 'primaryTool-pseudocolor'))
    listing = find(window, 'toolDetailFlickable')
    reset = find(window, 'activeToolReset')
    right = find(window, 'rightPanel')
    QTest.qWait(60)
    assert window.grabWindow().save(str(tmp_path / 'palette-top.png'))
    initial = reset.mapToScene(QPointF())
    heading = find(window, 'PseudoColorPanelHeading')
    heading_position = heading.mapToScene(QPointF())
    last_key = view.colorMapOptions[-1]['colorMap']
    for _ in range(20):
        wheel(window, listing, -1200)
        if listing.property('atYEnd'):
            break
    assert listing.property('atYEnd') and listing.property('contentY') > 0
    last = find(window, 'colorMap-' + last_key)
    assert heading.mapToScene(QPointF()) == heading_position
    assert reset.mapToScene(QPointF()) == initial
    assert listing.mapToScene(QPointF(0, listing.height())).y() <= initial.y()
    assert 0 < right.height() - reset.mapToItem(right, QPointF(0, reset.height())).y() <= 12
    # The wheel helper sends ScrollUpdate. End the gesture before clicking a row.
    point = last.mapToScene(QPointF(last.width() / 2, last.height() / 2))
    QCoreApplication.sendEvent(window, QWheelEvent(point, QPointF(window.mapToGlobal(point.toPoint())),
        QPoint(), QPoint(), Qt.NoButton, Qt.NoModifier, Qt.ScrollEnd, False))
    wait_until(lambda: not listing.property('moving'))
    classic = find(window, 'colorMap-blackBody')
    caption = next(item for item in descendants(classic) if item.objectName() == 'paletteCaption')
    assert not caption.property('truncated')
    click(window, last)
    wait_until(lambda: view.activeColorMap == last_key and last.property('checked'))
    assert window.grabWindow().save(str(tmp_path / 'palette-bottom.png'))
    click(window, reset)
    assert view.activeColorMap == 'grayscale' and view.zoom == 2
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    reset_all = find(window, 'compactToolReset')
    rail_position = reset_all.mapToScene(QPointF())
    for _ in range(20):
        wheel(window, rail, -1200)
        if rail.property('atYEnd'):
            break
    assert rail.property('atYEnd') and rail.property('contentY') > 0
    assert reset_all.mapToScene(QPointF()) == rail_position
    assert rail.mapToScene(QPointF(0, rail.height())).y() <= rail_position.y()
    click(window, reset_all)
    assert view.zoom == 1
    assert not sidebar_scene[3], sidebar_scene[3]
