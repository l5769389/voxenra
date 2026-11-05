"""Measurement tools stay reachable while scrolling a long tab result list."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.model import ImagePoint, MeasurementKind
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_sidebar_keyboard_access import all_controls_keyboard  # Use full keyboard navigation on macOS.
from test_tag_qml import click, descendants, find
from test_window_sizing import fit_desktop
from test_window_template_scroll import wheel


@pytest.mark.parametrize('size,panel_width,short', [
    ((1440, 1000), 320, False),
    ((1280, 720), 240, False),
    ((1280, 480), 240, True),
])
def test_measurement_tools_and_results_scroll(sidebar_scene, monkeypatch, tmp_path, size, panel_width, short):
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: workspace.activeViewport.loadState == 'ready')
    app.settingsController.setValue('layout', 'rightPanelWidth', panel_width)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    fit_desktop(window, app, monkeypatch, size)
    view = workspace.activeViewport
    # Populate three source frames so locating the last row verifies navigation.
    for slice_index in range(3):
        view.setSliceIndex(slice_index)
        wait_until(lambda: view._frame_meta.slice_index == slice_index)
        context = view._measurement_context(3, 2, kind=MeasurementKind.LENGTH)
        for index in range(8):
            x, y = 28 + 23 * (index % 2), 24 + 13 * (index // 2)
            points = [ImagePoint(x, y), ImagePoint(x + 6 + index, y + 3)]
            assert view.measurementController.paste_points(points, context)
    results = workspace.activeTab.measurementResults
    assert len(results.items) == 24
    results.locate(results.items[0]['key'])
    wait_until(lambda: view._frame_meta.slice_index == 0 and results.items[0]['selected'])

    click(window, find(window, 'primaryTool-measure'))
    length = find(window, 'measureEntry-length')
    click(window, find(window, 'measureEntry-ellipse'))
    assert workspace.activeTab.toolController.activeInteraction == 'measure:ellipse'
    click(window, length)
    assert workspace.activeTab.toolController.activeInteraction == 'measure:length'
    outer = find(window, 'toolDetailFlickable')
    assert outer.property('contentHeight') <= outer.height() + 1
    listing = find(window, 'measurementScroll')
    heading = find(window, 'measurementModeHeading')
    heading_pos = heading.mapToScene(QPointF())
    toggle = find(window, 'measurementResultsToggle')
    results_heading_pos = toggle.mapToScene(QPointF())
    grid_pos = length.mapToScene(QPointF())
    assert listing.height() < listing.property('contentHeight')

    for _ in range(20):
        wheel(window, listing, -1200)
        if listing.property('atYEnd'):
            break
    assert listing.property('atYEnd')
    assert outer.property('contentY') == 0
    assert heading.mapToScene(QPointF()) == heading_pos
    if short:
        assert length.mapToScene(QPointF()).y() < grid_pos.y()
        assert heading.property('text') == length.property('label')
    else:
        assert length.mapToScene(QPointF()) == grid_pos
        assert toggle.mapToScene(QPointF()) == results_heading_pos
    QTest.keyClick(window, Qt.Key_A)
    angle = find(window, 'measureEntry-angle')
    assert angle.property('checked') and workspace.activeTab.toolController.activeInteraction == 'measure:angle'
    if short:
        assert heading.property('text') == angle.property('label')
    last = find(window, 'locateMeasurement-23')
    top = listing.mapToScene(QPointF()).y()
    bottom = last.mapToScene(QPointF(0, last.height())).y()
    assert top < bottom <= top + listing.height() + 1
    click(window, last)
    wait_until(lambda: view._frame_meta.slice_index == 2 and results.items[-1]['selected'])
    assert window.grabWindow().save(str(tmp_path / f'measurement-{size[0]}x{size[1]}-bottom.png'))
    for _ in range(20):
        wheel(window, listing, 240, pixel=True)
        if listing.property('atYBeginning'):
            break
    assert listing.property('atYBeginning')
    assert length.mapToScene(QPointF()) == grid_pos
    assert window.grabWindow().save(str(tmp_path / f'measurement-{size[0]}x{size[1]}-top.png'))
    # Forward Tab follows visual order, including when the grid moves inside the scroller.
    find(window, 'measureEntry-freehand').forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Tab)
    assert toggle.hasActiveFocus()
    for _ in range(65):
        QTest.keyClick(window, Qt.Key_Tab)
        focused = window.activeFocusItem()
        if not short and focused.objectName() == 'measurementResultsMore':
            assert heading_pos.y() < focused.mapToScene(QPointF()).y() < listing.mapToScene(QPointF()).y()
            continue
        focus_y = focused.mapToItem(listing, QPointF()).y()
        assert -1 <= focus_y <= listing.height() - focused.height() + 1, focused.objectName()
        if focused.objectName() == 'locateMeasurement-10':
            break
    assert focused.objectName() == 'locateMeasurement-10'
    assert listing.property('contentY') > 0
    toggle.forceActiveFocus(Qt.BacktabFocusReason)
    click(window, toggle)
    wait_until(lambda: abs(listing.property('contentHeight') - listing.height()) <= 1)
    assert listing.property('atYBeginning') and listing.property('atYEnd')
    assert not warnings, warnings


def test_resize_keeps_measurement_selection_and_fold_state(sidebar_scene, monkeypatch):
    from test_workspace_persistence import draw_length

    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: workspace.activeViewport.loadState == 'ready')
    draw_length(workspace.activeViewport)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    fit_desktop(window, app, monkeypatch, (1280, 720))
    click(window, find(window, 'primaryTool-measure'))
    ellipse = find(window, 'measureEntry-ellipse')
    click(window, ellipse)
    toggle = find(window, 'measurementResultsToggle')
    click(window, toggle)
    selected = workspace.activeTab.measurementResults.items[0]['key']
    heading = find(window, 'measurementModeHeading')
    for size, short in [((1280, 480), True), ((1280, 720), False)]:
        fit_desktop(window, app, monkeypatch, size)
        assert (heading.property('text') == ellipse.property('label')) == short
        assert ellipse.property('checked')
        assert not any(i.objectName() == 'locateMeasurement-0' and i.isVisible()
                       for i in descendants(window.contentItem()))
        find(window, 'measureEntry-freehand').forceActiveFocus(Qt.TabFocusReason)
        QTest.keyClick(window, Qt.Key_Tab)
        assert toggle.hasActiveFocus()
    click(window, toggle)
    click(window, find(window, 'locateMeasurement-0'))
    assert [(r['key'], r['selected']) for r in workspace.activeTab.measurementResults.items] == [(selected, True)]
    assert not warnings, warnings
