"""Organ selection must preserve the user's position and keyboard focus."""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from shiboken6 import isValid

from qt_dicom_viewer.i18n.messages import builtin
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_local_segmentation_completion_qml import automatic_scene, open_selection
from test_tag_qml import click, descendants, find


@pytest.fixture
def organ_scene(automatic_scene):
    window, app, tab, controller, job, warnings = automatic_scene
    controller._environment['organs'] = [key.removeprefix('autoSeg.organ.')
        for key in builtin()['messages'] if key.startswith('autoSeg.organ.')]
    open_selection(window, app, 'en-US')
    window.requestActivate()
    hints = QGuiApplication.styleHints()
    previous = hints.tabFocusBehavior()
    hints.setTabFocusBehavior(Qt.TabFocusAllControls)
    try:
        yield window, app, controller, find(window, 'automaticSegmentationOrgans'), warnings
    finally:
        hints.setTabFocusBehavior(previous)


def bottom_rows(organs):
    QMetaObject.invokeMethod(organs, 'positionViewAtEnd')
    QTest.qWait(60)
    rows = [item for item in descendants(organs)
            if item.isVisible() and item.property('checked') is not None
            and 0 <= item.mapToItem(organs, QPointF()).y() < organs.height() - item.height()]
    return sorted(rows, key=lambda item: item.mapToItem(organs, QPointF()).y())


@pytest.mark.parametrize('theme', ['dark', 'graphite', 'light'])
def test_mouse_selection_keeps_long_list_position(organ_scene, theme, tmp_path):
    window, app, controller, organs, warnings = organ_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    row = bottom_rows(organs)[-2]
    before = organs.property('contentY')
    assert before > organs.height()
    name = row.property('text')
    selected = next(o['selected'] for o in controller.organs if o['name'] == name)
    click(window, row)
    wait_until(lambda: next(o['selected'] for o in controller.organs if o['name'] == name) != selected)
    QTest.qWait(60)
    assert abs(organs.property('contentY') - before) < 1
    assert isValid(row) and row.property('checked') != selected
    click(window, row)
    assert next(o['selected'] for o in controller.organs if o['name'] == name) == selected
    assert abs(organs.property('contentY') - before) < 1
    destination = Path(os.environ.get('VOXENRA_ORGAN_CAPTURES', tmp_path))
    destination.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(destination / f'organ-selection-{theme}.png'))
    assert not warnings, warnings


def test_filtered_selection_keeps_keyboard_focus_and_selection_across_search(organ_scene):
    window, app, controller, organs, warnings = organ_scene
    search = find(window, 'automaticSegmentationSearch')
    search.setProperty('text', 'rib')
    QTest.qWait(60)
    rows = bottom_rows(organs)
    row, following = rows[-3:-1]
    name = row.property('text')
    before = organs.property('contentY')
    selected = next(o['selected'] for o in controller.organs if o['name'] == name)
    row.forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Space)
    wait_until(lambda: next(o['selected'] for o in controller.organs if o['name'] == name) != selected)
    QTest.qWait(60)
    assert isValid(row) and row.hasActiveFocus()
    assert abs(organs.property('contentY') - before) < 1
    QTest.keyClick(window, Qt.Key_Tab)
    assert following.hasActiveFocus()
    search.setProperty('text', name)
    QTest.qWait(60)
    matches = [item for item in descendants(organs) if item.property('text') == name
               and item.property('checked') is not None]
    assert len(matches) == 1 and matches[0].property('checked') != selected
    search.setProperty('text', 'no such organ')
    QTest.qWait(60)
    assert organs.property('count') == 0
    search.setProperty('text', '')
    QTest.qWait(60)
    assert organs.property('count') == len(controller.organs)
    assert next(o['selected'] for o in controller.organs if o['name'] == name) != selected
    assert not warnings, warnings
