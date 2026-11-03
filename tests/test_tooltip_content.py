"""Verify the text and visibility of real controls, including stateful commands."""
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest

from qt_pointer import move_pointer
from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, find, settled_point
from test_workspace_persistence import draw_length


def test_window_favorite_has_one_hint_and_keeps_current_window(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    app.languageController.selectLanguage('en-US')
    v = tab.activeViewport
    before = v.windowCenter, v.windowWidth
    name = 'windowFavorite-' + v.windowPresets[0]['presetId']
    star = find(window, name)
    tip = star.findChild(QObject, name + '-hint')
    window.requestActivate()
    wait_until(window.isActive)
    move_pointer(window, settled_point(star))
    wait_until(lambda: star.property('hovered') and window.isActive())
    QTest.qWait(tip.property('delay') + 100)
    assert tip.property('visible'), (star.property('hovered'), tip.property('requested'), window.isActive())
    assert 'favorite' in tip.property('text').lower()
    QTest.mouseClick(window, Qt.LeftButton, pos=settled_point(star))
    wait_until(lambda: find(window, name).property('checked'))
    assert (v.windowCenter, v.windowWidth) == before
    selected = find(window, name)
    assert selected.property('hintText') == 'Remove favorite'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_measurement_tooltip_describes_next_action(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    app.languageController.selectLanguage('en-US')
    draw_length(tab.activeViewport)
    QTest.keyClick(window, Qt.Key_M)
    for name, before, after in [('measurementVisible-0', 'Hide measurement', 'Show measurement'),
                                ('measurementLock-0', 'Lock measurement', 'Unlock measurement')]:
        button = find(window, name)
        assert button.property('hintText') == before
        state = button.property('checked')
        click(window, button)
        button = find(window, name)
        wait_until(lambda: button.property('hintText') == after)
        assert button.property('checked') != state
        assert QAccessible.queryAccessibleInterface(button).text(QAccessible.Name) == after
    assert not sidebar_scene[3], sidebar_scene[3]
