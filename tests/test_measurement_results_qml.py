from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import draw_length


@pytest.mark.parametrize('locale,theme', [('zh-CN','dark'), ('en-US','dark'), ('zh-CN','light'), ('en-US','light')])
def test_result_list_actions_and_narrow_panel(sidebar_scene, locale, theme):
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.settingsController.setValue('layout', 'rightPanelWidth', 220)
    window.resize(1000, 760)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab, view = ws.activeTab, ws.activeViewport
    mid = draw_length(view)
    tab.toolController.activateTool('measure')
    wait_until(lambda: find(window, 'measurementResultsToggle').isVisible())
    QTest.qWait(60)
    names = ('measurementName-0', 'measurementVisible-0', 'measurementLock-0', 'deleteMeasurement-0')
    controls = [find(window, name) for name in names]
    centers = [control.mapToScene(QPointF(0, control.height() / 2)).y() for control in controls]
    assert max(centers) - min(centers) < 2
    assert all(control.width() >= 28 for control in controls)
    assert find(window, 'measurementVisible-0').property('iconName') == 'visible'
    click(window, find(window, 'measurementLock-0'))
    assert view.measurementController.presentation(mid)['locked']
    click(window, find(window, 'measurementVisible-0'))
    assert not view.measurementController.measurementItems
    click(window, find(window, 'locateMeasurement-0'))
    assert view.measurementController.measurementItems
    assert view.measurementController.selectedMeasurementId == mid
    field = find(window, 'measurementName-0')
    click(window, field)
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for character in 'Reference':
        QTest.keyClick(window, character)
    QTest.keyClick(window, Qt.Key_Return)
    assert view.measurementController.presentation(mid)['name'] == 'Reference'
    for name in ('measurementName-0','measurementResultsToggle','locateMeasurement-0'):
        assert find(window, name).width() <= 220
    folder = Path('build/p0/ui'); folder.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(folder/f'measurements-{locale}-{theme}.png'))
    click(window, find(window, 'deleteMeasurement-0'))
    assert not tab.measurementResults.items
    assert not warnings, warnings


def test_mpr_result_highlight_follows_active_viewport(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    window.resize(1400, 1040)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', 'mpr')
    tab = ws.activeTab
    views = [v for v in tab.viewports_by_id.values() if v.viewportType in ('axial', 'sagittal')]
    assert len(views) == 2
    wait_until(lambda: all(v.loadState == 'ready' for v in views))
    tab.activateViewport(views[0].viewportId)
    tab.toolController.activateTool('measure')
    for view in views:
        mid = draw_length(view)
        view.measurementController.select_completed(mid)
    first = find(window, 'locateMeasurement-0')
    second = find(window, 'locateMeasurement-1')
    assert [first.property('checked'), second.property('checked')] == [True, False]
    tab.activateViewport(views[1].viewportId)
    assert not find(window, 'locateMeasurement-0').property('checked')
    assert find(window, 'locateMeasurement-1').property('checked')
    click(window, find(window, 'locateMeasurement-0'))
    assert tab.activeViewport is views[0]
    assert all(v.measurementController.selectedMeasurementId for v in views)
    assert find(window, 'locateMeasurement-0').property('checked')
    assert not find(window, 'locateMeasurement-1').property('checked')
    assert not warnings, warnings


def test_more_clears_only_measurements_in_current_viewport_and_restores_focus(sidebar_scene, tmp_path):
    from qt_dicom_viewer.model import ImagePoint, MeasurementKind

    window, app, records, warnings = sidebar_scene
    window.resize(1000, 760)
    app.settingsController.setValue('layout', 'rightPanelWidth', 220)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', 'mpr')
    tab = ws.activeTab
    first, other = list(tab.viewports_by_id.values())[:2]
    wait_until(lambda: all(v.loadState == 'ready' for v in (first, other)))
    tab.activateViewport(first.viewportId)
    tab.toolController.activateTool('measure')
    mid = draw_length(first)
    peer = draw_length(other)
    measure = first.measurementController
    arrow = measure.paste_points([ImagePoint(1, 1), ImagePoint(5, 5)],
                                 first._measurement_context(1, .1, kind=MeasurementKind.ARROW))
    assert arrow
    tab.historyController.capture()
    more = find(window, 'measurementResultsMore')
    click(window, more)
    clear = find(window, 'clearViewportMeasurements')
    origin = clear.mapToScene(QPointF())
    assert 0 <= origin.x() <= window.width() - clear.width()
    assert 0 <= origin.y() <= window.height() - clear.height()
    assert window.grabWindow().save(str(tmp_path / 'measurement-clear-menu.png'))
    before = tab.toolController.activeInteraction
    QTest.keyClick(window, Qt.Key_A)
    assert tab.toolController.activeInteraction == before
    # Leave the menu open across a viewport change. Its original target is now stale.
    tab.activateViewport(other.viewportId)
    assert not clear.isEnabled()
    click(window, clear)
    assert set(measure._measurements) == {mid, arrow}
    assert set(other.measurementController._measurements) == {peer}
    tab.activateViewport(first.viewportId)
    QTest.keyClick(window, Qt.Key_Escape)
    wait_until(more.hasActiveFocus)
    assert mid in measure._measurements
    QTest.keyClick(window, Qt.Key_Space)
    click(window, find(window, 'clearViewportMeasurements'))
    assert set(measure._measurements) == {arrow}
    assert set(other.measurementController._measurements) == {peer}
    click(window, more)
    assert not find(window, 'clearViewportMeasurements').isEnabled()
    QTest.keyClick(window, Qt.Key_Escape)
    tab.historyController.undo()
    assert set(measure._measurements) == {mid, arrow}
    assert set(other.measurementController._measurements) == {peer}
    assert not warnings, warnings


def test_conversion_is_on_the_selected_freehand_result(sidebar_scene, tmp_path):
    from qt_dicom_viewer.model import ImagePoint, MeasurementKind
    from test_tag_qml import descendants

    window, app, records, warnings = sidebar_scene
    window.resize(1400, 1100)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', 'mpr')
    tab = ws.activeTab
    view = tab.activeViewport
    wait_until(lambda: bool(tab.voiController.sources) and not view.render_pending)
    tab.toolController.activateTool('measure')
    measure = view.measurementController
    rois = []
    for column, row in ((39, 16), (53, 67)):
        points = [ImagePoint(column + dx, row + dy) for dx, dy in ((0, 0), (10, 1), (8, 10), (1, 9))]
        rois.append(measure.paste_points(points, view._measurement_context(1, .1, kind=MeasurementKind.FREEHAND)))
    assert all(rois)
    click(window, find(window, 'locateMeasurement-0'))
    button = find(window, 'freehandToSegmentation')
    assert button.property('resultKey') == tab.measurementResults.items[0]['key']
    assert sum(i.objectName() == 'freehandToSegmentation' and i.isVisible()
               for i in descendants(window.contentItem())) == 1
    assert window.grabWindow().save(str(tmp_path / 'measurement-selected-roi.png'))
    click(window, button)
    exchange = app.exportController.dicomResults
    wait_until(lambda: not exchange.busy)
    assert not exchange.isError, exchange.message
    assert [record['source_measurement_id'] for record in tab.voiController.records] == rois[:1]
    assert set(measure._measurements) == set(rois)
    feedback = find(window, 'roiConversionMessage')
    assert feedback.property('text') == exchange.message
    assert 0 <= feedback.mapToScene(QPointF()).y() <= window.height() - feedback.height()
    assert window.grabWindow().save(str(tmp_path / 'measurement-converted-roi.png'))
    click(window, find(window, 'measurementResultsToggle'))
    assert not any(i.objectName() == 'freehandToSegmentation' and i.isVisible()
                   for i in descendants(window.contentItem()))
    assert find(window, 'roiConversionMessage').property('text') == exchange.message
    assert not warnings, warnings


def test_oblique_freehand_result_has_no_conversion_action(sidebar_scene):
    from qt_dicom_viewer.model import ImagePoint, MeasurementKind
    from test_tag_qml import descendants

    window, app, records, warnings = sidebar_scene
    window.resize(1400, 900)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', 'mpr')
    tab = ws.activeTab
    wait_until(lambda: bool(tab.voiController.sources) and not tab._active_mpr_requests)
    source = tab.activeViewport
    tab._handle_crosshair_rotation_requested(source.viewport_config.viewport_type, .3)
    wait_until(lambda: not tab._active_mpr_requests)
    view = next(v for v in tab.viewports_by_id.values() if v is not source)
    tab.activateViewport(view.viewportId)
    tab.toolController.activateTool('measure')
    points = [ImagePoint(x, y) for x, y in ((2, 1), (8, 1), (5, 2))]
    mid = view.measurementController.paste_points(points, view._measurement_context(1, .1, kind=MeasurementKind.FREEHAND))
    assert mid and find(window, 'locateMeasurement-0').property('checked')
    assert not any(i.objectName() == 'freehandToSegmentation' and i.isVisible()
                   for i in descendants(window.contentItem()))
    assert not warnings, warnings
