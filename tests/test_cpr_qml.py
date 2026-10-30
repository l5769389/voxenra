from pathlib import Path
from contextlib import contextmanager
from dataclasses import replace

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_cpr_controller import cpr, qt_app, draw
from test_cpr_persistence import cpr_app
from test_dicom_tags import wait_until
from test_measurement_qml import _visual_children
from test_series_sidebar import sidebar_scene
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider


@pytest.mark.parametrize('completion', ['enter', 'double-click', 'double-click-existing-point'])
def test_four_views_accept_real_pointer_and_keyboard_path_drawing(cpr, completion):
    view = QQuickView()
    provider = DicomImageProvider()
    cpr.imageUpdateRequested.connect(provider.set_array)
    for viewport in cpr.viewports_by_id.values():
        viewport.refresh_window_image()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.engine().addImageProvider("dicom", provider)
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 700)
    view.setInitialProperties(dict(controller=cpr))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/center/viewportArea/CprPage.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(80)
    try:
        target = next((item for item in _visual_children(view.rootObject())
                       if item.objectName() == "cprViewport-reference-a"), None)
        assert target is not None
        original_size = target.size()
        cpr.startPath()
        QTest.qWait(20)
        assert target.size() == original_size
        for x, y in ((.35, .35), (.5, .5)):
            point = target.mapToScene(QPointF(
                target.width()*x, target.height()*y))
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.qWait(40)
        assert len(cpr.controlPoints) == 2
        point = target.mapToScene(QPointF(target.width()*.65, target.height()*.6))
        if completion == 'enter':
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.keyClick(view, Qt.Key_Return)
        else:
            if completion == 'double-click-existing-point':
                QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
                point += QPointF(1, 1)
            # A realistic second press can drift by a pixel. It must confirm,
            # not add a tiny terminal segment that changes the section normal.
            end = (point + QPointF(1, 1)).toPoint()
            QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        wait_until(lambda: cpr.ready)
        assert len(cpr.paths) == 1
        assert len(cpr.current_path.control_points) == 3
        assert cpr.resultView
        assert not target.isVisible()
        assert target.size() == original_size
        assert not cpr.focusedViewportId
        # A two-pixel correction must move the existing control point, not
        # become a tap (or insert a new point) at the release position.
        cpr.setPathEditing(True)
        QTest.qWait(40)
        before = cpr.current_path.control_points
        start = target.mapToScene(QPointF(target.width()*.35, target.height()*.35)).toPoint()
        end = (QPointF(start) + QPointF(2, 1)).toPoint()
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(view, end, 20)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        wait_until(lambda: not cpr.busy)
        assert len(cpr.current_path.control_points) == 3
        assert cpr.current_path.control_points[0] != before[0]
        assert cpr.current_path.control_points[1:] == before[1:]
        view.rootObject().setProperty("controller", None)
        QCoreApplication.processEvents()
        assert not warnings, "\n".join(warnings)
    finally:
        view.hide()
        delete(view)


@pytest.fixture
def cpr_page(cpr):
    draw(cpr)
    with displayed_cpr_page(cpr) as page:
        yield page


@contextmanager
def displayed_cpr_page(cpr):
    window = QQuickView()
    provider = DicomImageProvider()
    cpr.imageUpdateRequested.connect(provider.set_array)
    for viewport in cpr.viewports_by_id.values():
        viewport.refresh_window_image()
    warnings = []
    window.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window.engine().addImageProvider("dicom", provider)
    window.engine().addImageProvider("navigation", SvgIconProvider())
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.resize(1000, 700)
    window.setInitialProperties(dict(controller=cpr))
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/center/viewportArea/CprPage.qml")))
    assert window.status() == QQuickView.Ready
    window.show()
    QTest.qWait(80)
    try:
        yield window, cpr
    finally:
        window.rootObject().setProperty("controller", None)
        QCoreApplication.processEvents()
        window.hide()
        delete(window)
        assert not warnings, "\n".join(warnings)


def named_item(root, name):
    return next(item for item in _visual_children(root) if item.objectName() == name)


def double_click(window, item):
    point = item.mapToScene(QPointF(item.width()*.7, item.height()*.45)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(50)


def test_done_changes_visible_layout_and_edit_restores_four_views(cpr_page, tmp_path):
    from qt_dicom_viewer.model import WindowLevel
    from qt_dicom_viewer.model.interaction import WindowLevelChange
    window, tab = cpr_page
    root = window.rootObject()
    items = {role: named_item(root, 'cprViewport-' + role)
             for role in ('reference-a', 'reference-b', 'curved', 'cross')}
    cross = tab.viewForRole('cross')
    cross.apply_window_level(WindowLevelChange(WindowLevel(2200, 4400), False))
    cross.setZoom(2)
    tab.setPositionMm(5)
    wait_until(lambda: tab.ready)
    state = cross.viewport_state
    assert all(item.isVisible() for item in items.values())
    assert window.grabWindow().save(str(tmp_path/'editing.png'))
    tab.finishEditing()
    QTest.qWait(80)
    assert not items['reference-a'].isVisible() and not items['reference-b'].isVisible()
    assert items['curved'].isVisible() and items['cross'].isVisible()
    assert items['curved'].width() / items['cross'].width() == pytest.approx(2, abs=.03)
    assert items['curved'].height() > window.height() - 10
    assert window.grabWindow().save(str(tmp_path/'results.png'))
    double_click(window, items['cross'])
    assert tab.focusedViewportId == cross.viewportId
    assert not items['curved'].isVisible()
    QTest.qWait(500)
    double_click(window, items['cross'])
    assert not tab.focusedViewportId and tab.resultView
    assert items['curved'].isVisible() and not items['reference-a'].isVisible()
    window.resize(600, 700)
    QTest.qWait(80)
    assert items['curved'].width() > 590 and items['cross'].width() > 590
    assert items['curved'].height() == items['cross'].height()
    assert window.grabWindow().save(str(tmp_path/'results-narrow.png'))
    tab.setPathEditing(True)
    QTest.qWait(80)
    assert all(item.isVisible() for item in items.values())
    assert replace(cross.viewport_state, width=state.width, height=state.height) == state
    # Returning to edit from a button/shortcut gives the reference keyboard focus.
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(80)
    assert tab.resultView and not tab.pathEditing
    assert replace(cross.viewport_state, width=state.width, height=state.height) == state


def test_main_window_cpr_shortcuts_and_text_input_guards(sidebar_scene, tmp_path):
    from test_tag_qml import find, click
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = ws.activeTab
    wait_until(lambda: tab.referencesReady)
    window.requestActivate()
    QTest.qWait(80)
    reference = find(window, 'cprViewport-reference-a')
    reference.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_N)
    QTest.qWait(30)
    assert tab.drawing
    ref = tab.viewForRole('reference-a')
    ref.cprTap(35, 48, .4)
    ref.cprTap(65, 48, .4)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: tab.resultView)
    QTest.qWait(80)
    assert not reference.isVisible()
    assert window.grabWindow().save(str(tmp_path/'main-results.png'))
    QTest.keyClick(window, Qt.Key_R)
    QTest.qWait(40)
    assert tab.pathEditing and reference.isVisible()
    assert window.grabWindow().save(str(tmp_path/'main-editing.png'))
    click(window, find(window, 'cprDetails'))
    name = find(window, 'cprPathName')
    click(window, name)
    assert name.hasActiveFocus()
    QTest.keyClick(window, Qt.Key_N)
    QTest.keyClick(window, Qt.Key_R)
    assert not tab.drawing and tab.pathEditing
    assert name.hasActiveFocus()
    click(window, find(window, 'cprFinishPath'))
    QTest.qWait(80)
    assert tab.resultView and not name.isVisible()
    QTest.keyClick(window, Qt.Key_N)
    QTest.qWait(40)
    assert tab.drawing and reference.isVisible()
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(40)
    assert tab.resultView and not tab.drawing
    assert not warnings, warnings


def test_cross_section_history_is_visible_when_curved_result_is_maximized(cpr_app):
    from test_workspace_persistence import draw_length
    _, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    measurement = draw_length(cross)
    source = cross.measurementController._sources[measurement]
    tab.finishEditing()
    with displayed_cpr_page(tab) as (window, _):
        curved = named_item(window.rootObject(), 'cprViewport-curved')
        section = named_item(window.rootObject(), 'cprViewport-cross')
        curved.forceActiveFocus()
        tab.focusSingleViewport(tab.viewForRole('curved').viewportId)
        QTest.qWait(20)
        assert curved.isVisible() and not section.isVisible()
        tab.navigate_measurement(cross, source)
        wait_until(lambda: cross.historicalPlane)
        QTest.qWait(20)
        assert tab.resultView and tab.activeViewport is cross
        assert tab.focusedViewportId == cross.viewportId
        assert section.isVisible() and not curved.isVisible()
        assert section.hasActiveFocus() and not curved.hasActiveFocus()


@pytest.mark.parametrize("role", ["reference-a", "reference-b", "curved", "cross"])
def test_cpr_double_click_focus_restore_and_wheel_without_navigation_chrome(cpr_page, role):
    window, tab = cpr_page
    item = named_item(window.rootObject(), "cprViewport-" + role)
    controller = tab.viewForRole(role)
    original_size = item.size()
    names = [child.objectName() for child in _visual_children(window.rootObject())]
    assert "sliceControl" not in names and not any(name.startswith("cprFocus-") for name in names)
    double_click(window, item)
    assert tab.focusedViewportId == controller.viewportId
    assert tab.activeViewport is controller
    assert item.width() > original_size.width() * 1.9
    QTest.qWait(500)
    double_click(window, item)
    assert not tab.focusedViewportId
    assert item.size() == original_size
    wait_until(lambda: tab.ready and not tab.busy)
    index = controller.sliceIndex
    direction = 1 if index < controller.sliceCount - 1 else -1
    point = item.mapToScene(QPointF(item.width()*.5, item.height()*.5))
    event = QWheelEvent(point, QPointF(window.mapToGlobal(point.toPoint())), QPoint(), QPoint(0, -120 * direction),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, event)
    wait_until(lambda: tab.ready and not tab.busy)
    assert controller.sliceIndex == index + direction
    if role in ("curved", "cross"):
        assert tab.viewForRole("curved").sliceIndex == tab.viewForRole("cross").sliceIndex
    assert not tab.focusedViewportId


def test_cpr_overlay_uses_geometry_and_window_without_repeated_patient_or_acquisition_details(cpr_page):
    window, tab = cpr_page
    for role in ("reference-a", "reference-b", "curved", "cross"):
        item = named_item(window.rootObject(), "cprViewport-" + role)
        controller = tab.viewForRole(role)
        controller.cursorController.clearPosition()
        assert named_item(item, "overlay-topRight").property("text") == ""
        assert named_item(item, "overlay-bottomRight").property("text") == ""
        window_text = named_item(item, "overlay-bottomLeft").property("text")
        assert "WW:" in window_text and "WL:" in window_text
        assert "kV:" not in window_text and "thk:" not in window_text
        top = named_item(item, "overlay-topLeft").property("text")
        if role.startswith("reference"):
            assert "Slice:" in top
        else:
            assert "Slice:" not in top  # Samples along a path are not source slices.
        controller.cursorController.updatePosition(10, 10, 125.5)
        cursor = named_item(item, "overlay-bottomRight").property("text")
        assert "125.5" in cursor and "X:" not in cursor and "Rot:" not in cursor
    curved = named_item(window.rootObject(), "cprViewport-curved")
    assert "CPR · THIN" in named_item(curved, "overlay-topLeft").property("text")
    cross = named_item(window.rootObject(), "cprViewport-cross")
    assert "CROSS-SECTION" in named_item(cross, "overlay-topLeft").property("text")
    for item in (curved, cross):
        assert "s: 0.0 /" in named_item(item, "overlay-topLeft").property("text")
    for index in (0, 1):
        selector = named_item(window.rootObject(), "cprPlane-" + str(index))
        reference = named_item(window.rootObject(), "cprViewport-reference-" + ("a" if index == 0 else "b"))
        assert selector not in list(_visual_children(reference))
        assert selector.property("mode") == tab.referencePlanes[index]


def test_cpr_inline_plane_selection_does_not_focus_or_modify_path(cpr_page):
    window, tab = cpr_page
    original = tab.current_path
    selector = named_item(window.rootObject(), "cprPlane-0")
    point = selector.mapToScene(QPointF(selector.width()/2, selector.height()/2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: tab.ready and not tab.busy)
    assert list(tab.referencePlanes) == ["sagittal", "coronal"]
    assert not tab.focusedViewportId
    assert tab.current_path == original
    assert selector.property("mode") == "sagittal"
    window.rootObject().setProperty("anonymousExport", True)
    assert not selector.isVisible()
    window.rootObject().setProperty("anonymousExport", False)
    assert selector.isVisible()


def test_historical_reference_shows_stored_plane_and_explicit_history_status(cpr_app):
    from test_workspace_persistence import draw_length
    _, tab, _ = cpr_app
    reference = tab.viewForRole("reference-a")
    measurement = draw_length(reference)
    source = reference._measure_controller._sources[measurement]
    with displayed_cpr_page(tab) as (window, _):
        tab.setReferencePlane(0, "coronal")
        wait_until(lambda: tab.ready and not tab.busy)
        tab.navigate_measurement(reference, source)
        wait_until(lambda: reference.historicalPlane)
        selector = named_item(window.rootObject(), "cprPlane-0")
        viewport = named_item(window.rootObject(), "cprViewport-reference-a")
        assert reference.overlayInfo["viewPosition"].startswith("Axial")
        assert viewport.property("twoDViewMode") == ""
        assert not selector.isVisible()
        assert "Axial" in named_item(viewport, "overlay-topLeft").property("text")
        assert "HISTORICAL" in named_item(viewport, "overlay-topRight").property("text")
        reference.setSliceIndex(reference.sliceIndex + 1)
        assert reference.historicalPlane and not selector.isVisible()
        wait_until(lambda: not reference.historicalPlane and tab.ready)
        assert selector.isVisible() and selector.property("mode") == "coronal"


def test_cpr_no_footer_and_overlay_state_changes_keep_full_image_bounds(cpr_page):
    window, tab = cpr_page
    items = [named_item(window.rootObject(), "cprViewport-" + role)
             for role in ("reference-a", "reference-b", "curved", "cross")]
    original_sizes = [item.size() for item in items]
    # Cell borders and grid spacing are the only space outside the images.
    assert items[0].height() == pytest.approx((window.height() - 4) / 2 - 4)
    assert not any(item.objectName().startswith("cprStatus-") for item in _visual_children(window.rootObject()))
    tab.startPath()
    QCoreApplication.processEvents()
    assert [item.size() for item in items] == original_sizes
    assert "PREVIOUS RESULT" in named_item(items[2], "overlay-topRight").property("text")
    tab.cancel_operation()
    QCoreApplication.processEvents()
    assert [item.size() for item in items] == original_sizes


def test_reference_position_digit_changes_do_not_move_slice_annotation(cpr_page):
    window, tab = cpr_page
    reference = tab.viewForRole("reference-a")
    viewport = named_item(window.rootObject(), "cprViewport-reference-a")
    position = named_item(viewport, "twoDModePosition")
    row = named_item(viewport, "twoDModeInformation")
    selector = named_item(window.rootObject(), "cprPlane-0")
    widths = []
    for index in (1, 39):
        reference.setSliceIndex(index)
        wait_until(lambda: tab.ready)
        widths.append(position.property("implicitWidth"))
    assert widths[1] > widths[0]
    # Exercise the boundary where the old content-dependent rule changed rows.
    desired = selector.width() + 4 + sum(widths)/2
    window.resize(window.width() + round(4*(desired - row.width())), window.height())
    QTest.qWait(30)
    positions = []
    for index in (1, 39, 1):
        reference.setSliceIndex(index)
        wait_until(lambda: tab.ready)
        corner = named_item(viewport, "overlay-topLeft")
        positions.append((position.x(), position.y(), row.height(), corner.y(), viewport.size()))
    assert positions[0] == positions[1] == positions[2]


def test_path_panel_buttons_and_name_field_work_without_binding_errors(cpr):
    view = QQuickView()
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(280, 1050)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties(dict(toolController=cpr.toolController, toolVisible=True,
                                   viewportController=cpr.activeViewport, tabController=cpr))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/RightPanel.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(40)
    def click(name):
        item = next(item for item in _visual_children(view.rootObject()) if item.objectName() == name)
        point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(20)
    try:
        click("cprNewPath")
        assert cpr.drawing
        fields = {item.objectName(): item for item in _visual_children(view.rootObject())}
        assert not fields['cprFinishPath'].isEnabled()
        ref = cpr.viewForRole('reference-a')
        ref.cprTap(5, 10, .4)
        assert not fields['cprFinishPath'].isEnabled()
        ref.cprTap(15, 10, .4)
        assert fields['cprFinishPath'].isEnabled()
        click('cprFinishPath')
        wait_until(lambda: cpr.ready)
        assert not cpr.drawing and not cpr.pathEditing
        click('cprEditPath')
        assert cpr.pathEditing
        click('cprFinishPath')
        assert not cpr.pathEditing
        click('cprNewPath')
        click("cprCancelPath")
        assert not cpr.drawing
        draw(cpr)
        click("cprDetails")
        click("cprPathName")
        QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
        QCoreApplication.sendEvent(view, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, "Left artery"))
        QTest.keyClick(view, Qt.Key_Return)
        assert cpr.current_path.name == "Left artery"
        assert not warnings, "\n".join(warnings)
    finally:
        view.hide()
        delete(view)


def test_panel_syncs_saved_values_when_loader_assigns_controller_late(cpr):
    draw(cpr)
    cpr.renamePath("Saved vessel")
    cpr.setParameter("angle", 35)
    cpr.setParameter("thickness", 12)
    cpr.setParameter("step", .75)
    wait_until(lambda: cpr.ready and not cpr.busy)
    view = QQuickView()
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setInitialProperties(dict(controller=None))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/right/panels/CprPanel.qml")))
    assert view.status() == QQuickView.Ready
    try:
        # ToolDetailPanel assigns its controller after Loader.onLoaded. Returning
        # from Settings must not present defaults or overwrite saved parameters.
        view.rootObject().setProperty("controller", cpr)
        QCoreApplication.processEvents()
        fields = {item.objectName(): item for item in _visual_children(view.rootObject())}
        assert fields["cprPathName"].property("text") == "Saved vessel"
        assert fields["cprParameter-angle"].property("text") == "35.0"
        assert fields["cprParameter-thickness"].property("text") == "12.0"
        assert fields["cprParameter-step"].property("text") == "0.75"
    finally:
        delete(view)


def test_empty_cpr_results_do_not_show_unavailable_corner_values(cpr):
    def overlay(viewport):
        return next(item for item in _visual_children(viewport)
                    if item.objectName() == "viewportMetadataOverlay")

    view = QQuickView()
    provider = DicomImageProvider()
    cpr.imageUpdateRequested.connect(provider.set_array)
    for viewport in cpr.viewports_by_id.values():
        viewport.refresh_window_image()
    view.engine().addImageProvider('dicom', provider)
    view.engine().addImageProvider('navigation', SvgIconProvider())
    view.setInitialProperties(dict(controller=cpr))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 700)
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/center/viewportArea/CprPage.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(30)
    try:
        targets = {item.objectName(): item for item in _visual_children(view.rootObject())
                   if item.objectName().startswith('cprViewport-')}
        assert overlay(targets['cprViewport-reference-a']).isVisible()
        for role in ('curved', 'cross'):
            assert not overlay(targets['cprViewport-'+role]).isVisible()
        draw(cpr)
        QCoreApplication.processEvents()
        assert overlay(targets['cprViewport-cross']).isVisible()
        cpr.setPositionMm(cpr.totalLength * .8)
        cpr.setParameter('angle', 30)
        wait_until(lambda: cpr.ready and not cpr.busy)
        QCoreApplication.processEvents()
        cross_items = list(_visual_children(targets['cprViewport-cross']))
        directions = next(item for item in cross_items
                          if item.metaObject().className().startswith('DirectionOverlay'))
        label = directions.property('directionLabels')['top']
        assert len(label) == 3
        top = next(item for item in _visual_children(directions)
                   if item.property('text') == label)
        right = next(item for item in cross_items if item.objectName() == 'overlay-topRight')
        assert top.mapToScene(QPointF(top.width(), 0)).x() + 4 <= right.mapToScene(QPointF()).x()
        cpr.deletePath()
        wait_until(lambda: not cpr.busy)
        QCoreApplication.processEvents()
        assert not overlay(targets['cprViewport-cross']).isVisible()
    finally:
        view.hide()
        delete(view)
