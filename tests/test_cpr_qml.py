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
        wait_until(lambda: len(cpr.controlPoints) == 2)
        point = target.mapToScene(QPointF(target.width()*.65, target.height()*.6))
        if completion == 'enter':
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.keyClick(view, Qt.Key_Return)
        else:
            if completion == 'double-click-existing-point':
                QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
                wait_until(lambda: len(cpr.controlPoints) == 3)
                point += QPointF(1, 1)
            # A realistic second press can drift by a pixel. It must confirm,
            # not add a tiny terminal segment that changes the section normal.
            end = (point + QPointF(1, 1)).toPoint()
            QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        wait_until(lambda: cpr.ready)
        assert len(cpr.paths) == 1
        count = 2 if completion == "double-click" else 3
        assert len(cpr.current_path.control_points) == count
        assert not cpr.resultView
        assert target.isVisible()
        assert target.size() == original_size
        assert not cpr.focusedViewportId
        # A two-pixel correction must move the existing control point, not
        # become a tap (or insert a new point) at the release position.
        assert not cpr.pathEditing
        QTest.qWait(40)
        before = cpr.current_path.control_points
        start = target.mapToScene(QPointF(target.width()*.35, target.height()*.35)).toPoint()
        end = (QPointF(start) + QPointF(2, 1)).toPoint()
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(view, end, 20)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        wait_until(lambda: not cpr.busy)
        assert cpr.pathEditing and len(cpr.current_path.control_points) == count
        assert cpr.current_path.control_points[0] != before[0]
        assert cpr.current_path.control_points[1:] == before[1:]
        edited = cpr.current_path
        middle = target.mapToScene(QPointF(target.width()*.425 + 1, target.height()*.425)).toPoint()
        QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, middle)
        wait_until(lambda: not cpr.pathEditing)
        assert not cpr.resultView and cpr.current_path == edited
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
    tab.setReferenceBrowsing(False)
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
    assert items['curved'].height() == pytest.approx(2 * items['cross'].height(), abs=6)
    assert window.grabWindow().save(str(tmp_path/'results-narrow.png'))
    tab.setPathEditing(True)
    QTest.qWait(80)
    assert all(item.isVisible() for item in items.values())
    assert replace(cross.viewport_state, width=state.width, height=state.height) == state
    # Returning to edit from a button/shortcut gives the reference keyboard focus.
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(80)
    assert not tab.resultView and not tab.pathEditing
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
    wait_until(lambda: tab.ready)
    assert not tab.resultView and reference.isVisible()
    QTest.keyClick(window, Qt.Key_V)
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
    assert not tab.resultView and not tab.pathEditing
    reference.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_V)
    wait_until(lambda: tab.resultView)
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
    tab.setReferenceBrowsing(False)
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
        assert named_item(item, "overlay-topRight").property("text") == (
            "" if role.startswith("reference") else QCoreApplication.translate("", "cpr.statusCurrentResult") + "\nPath 1 · r1")
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
        assert QCoreApplication.translate("", "cpr.statusHistoricalPlane") in named_item(viewport, "overlay-topRight").property("text")
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
    assert QCoreApplication.translate("", "cpr.statusPreviousResult") in named_item(items[2], "overlay-topRight").property("text")
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
        assert not {'cprEditPath', 'cprNewPath', 'cprAdditionalPath'} & fields.keys()
        ref.cprTap(10, 10, .4)
        assert cpr.pathEditing
        click('cprFinishPath')
        assert not cpr.pathEditing
        ref.cprTap(5, 20, .4)
        assert cpr.drawing
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
        assert fields["cprParameter-angle"].property("text") == "35"
        assert fields["cprParameter-thickness"].property("text") == "12"
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


def test_numeric_position_history_return_and_locked_browse_ui(cpr_app, tmp_path):
    from copy import deepcopy
    from test_workspace_persistence import draw_length
    _, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    mid = draw_length(cross)
    source = deepcopy(cross.measurementController._sources[mid])
    saved_items = deepcopy(cross.measurementController.measurementItems)
    tab.setPositionMm(27.0)
    tab.setParameter('angle', 45)
    wait_until(lambda: tab.ready and not tab.busy)
    tab.setReferenceBrowsing(False)
    tab.navigate_measurement(cross, source)
    wait_until(lambda: cross.historicalPlane and not cross.render_pending)
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(320, 1050)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties(dict(toolController=tab.toolController, toolVisible=True,
                                   viewportController=cross, tabController=tab))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/RightPanel.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(40)
    def item(name):
        return named_item(view.rootObject(), name)
    def click(name):
        target = item(name)
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                        target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint())
        QTest.qWait(30)
    try:
        assert item('cprHistoricalSource').isVisible()
        assert '0.0' in item('cprHistoricalSource').property('text')
        assert item('cprCurrentParameters').isVisible()
        assert item('cprParameter-angle').property('text') == '45'
        assert view.grabWindow().save(str(tmp_path/'historical-current-panel.png'))
        click('cprReturnCurrent')
        wait_until(lambda: tab.ready and not tab.busy and not cross.historicalPlane)
        assert tab.activeViewport == cross
        assert tab.positionMm > 26
        assert cross.measurementController._sources[mid] == source
        tab.navigate_measurement(cross, source)
        wait_until(lambda: cross.historicalPlane and not cross.render_pending)
        assert cross.measurementController.measurementItems == saved_items
        click('cprPositionInput')
        QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
        QCoreApplication.sendEvent(view, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, '12.34'))
        QTest.keyClick(view, Qt.Key_Return)
        wait_until(lambda: tab.ready and not tab.busy and not cross.historicalPlane)
        assert abs(tab.positionMm - 12.34) < tab.current_settings.step_mm
        assert float(item('cprPositionInput').property('text')) == pytest.approx(tab.positionMm, abs=1e-6)
        before = tab.positionMm
        click('cprNextSample')
        wait_until(lambda: tab.ready and not tab.busy)
        assert tab.positionMm > before
        click('cprPreviousSample')
        wait_until(lambda: tab.ready and not tab.busy)
        assert tab.positionMm == pytest.approx(before)
        original = tab.current_path
        click('cprReferenceBrowse')
        assert not tab.resultView and not tab.pathEditing
        assert not item('cprFinishPath').isVisible()
        assert view.grabWindow().save(str(tmp_path/'reference-locked-panel.png'))
        click('cprReferenceBrowse')
        assert tab.resultView and tab.current_path == original
        assert not warnings, '\n'.join(warnings)
    finally:
        view.hide()
        delete(view)


def test_locked_reference_layout_pointer_and_wheel_preserve_path(cpr_page):
    window, tab = cpr_page
    tab.setReferenceBrowsing(False)
    tab.setReferenceBrowsing(True)
    QTest.qWait(30)
    original = tab.current_path
    target = named_item(window.rootObject(), 'cprViewport-reference-a')
    assert target.isVisible() and not tab.pathEditing
    point = target.mapToScene(QPointF(target.width() * .5, target.height() * .5)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseMove(window, point + QPoint(15, 5), 20)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point + QPoint(15, 5))
    ref = tab.viewForRole('reference-a')
    before = ref.sliceIndex
    wheel = QWheelEvent(QPointF(point), QPointF(window.mapToGlobal(point)), QPoint(), QPoint(0, 120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, wheel)
    wait_until(lambda: ref.sliceIndex != before and not tab.busy)
    assert ref.sliceIndex != before
    assert tab.current_path == original
    assert tab.drawing and tab.pointCount == 1
    tab.cancel_operation()
    tab.setPathEditing(True)
    assert ref.cprEditing and tab.pathEditing


def test_click_empty_image_then_select_and_delete_another_visible_path(cpr_page):
    window, tab = cpr_page
    ref = tab.viewForRole('reference-a')
    viewport = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(viewport, 'cprPathOverlay')

    def tap(column, row):
        pos = overlay.mapToScene(overlay.pixel(column, row)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)

    original = tab.current_path
    tap(8, 29)
    assert tab.drawing and tab.pointCount == 1  # No double-click timeout for feedback.
    tap(28, 29)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: tab.ready and not tab.busy)
    second = tab.current_path
    assert not tab.drawing and second != original and len(tab.paths) == 2
    assert overlay.property('otherTraces')
    tap(10, 10)
    QTest.keyClick(window, Qt.Key_Delete)
    wait_until(lambda: tab.ready and not tab.busy)
    assert len(tab.paths) == 1 and tab.current_path == second
    QTest.keyClick(window, Qt.Key_Backspace)
    assert len(tab.paths) == 1 and ref.cprPathInput and not tab.pathEditing
    tap(18, 29)
    wait_until(lambda: overlay.property('wholePathSelected'))
    assert tab.pathEditing and tab.current_path == second
    QTest.keyClick(window, Qt.Key_Escape)
    # The first tap of a double-click on blank image must not leave a draft.
    double_click(window, viewport)
    assert tab.focusedViewportId == ref.viewportId and not tab.drawing
    assert tab.current_path == second


def test_cpr_uses_one_native_precision_cursor_while_placing_and_dragging(cpr_page):
    from qt_pointer import move_pointer

    window, tab = cpr_page
    viewport = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(viewport, 'cprPathOverlay')
    glyph = named_item(viewport, 'viewportCustomCursor')

    def position(column, row):
        return overlay.mapToScene(overlay.pixel(column, row)).toPoint()

    def assert_cross():
        assert window.cursor().shape() == Qt.CrossCursor
        assert not glyph.isVisible()

    window.requestActivate()
    assert QTest.qWaitForWindowActive(window)
    start = position(8, 29)
    move_pointer(window, start + QPoint(15, 10))
    move_pointer(window, start)
    wait_until(lambda: window.cursor().shape() == Qt.CrossCursor)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, start)
    assert tab.drawing and tab.pointCount == 1
    assert_cross()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position(28, 29))
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: tab.ready)
    original = tab.current_path.control_points
    move_pointer(window, start)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    end = position(10, 25)
    QTest.mouseMove(window, end, 20)
    assert tab.pathEditing
    assert_cross()
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    assert tab.current_path.control_points[0] != original[0]
    assert_cross()
    tab.toolController.activateTool('window')
    move_pointer(window, position(12, 26))
    assert glyph.isVisible() and window.cursor().shape() == Qt.BlankCursor


@pytest.mark.parametrize('gesture', ['from-margin', 'draft-to-margin', 'handle-to-margin'])
def test_cpr_reference_margin_drag_respects_path_tool(cpr_page, gesture):
    window, tab = cpr_page
    ref = tab.viewForRole('reference-a')
    ref.setZoom(.75)
    viewport = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(viewport, 'cprPathOverlay')

    def position(column, row):
        return overlay.mapToScene(overlay.pixel(column, row)).toPoint()

    start, end = position(7, 26), position(-3, 26)
    assert viewport.contains(viewport.mapFromScene(end))
    original = tab.current_path
    windowing = ref.windowWidth, ref.windowCenter
    if gesture == 'from-margin':
        start, end = end, start
    elif gesture == 'draft-to-margin':
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position(8, 29))
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position(29, 29))
        assert tab.drawing and tab.pointCount == 2
    else:
        start = position(5, 10)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, (start + end) / 2, 20)
    QTest.mouseMove(window, end, 20)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    assert (ref.windowWidth, ref.windowCenter) == windowing
    assert tab.current_path == original
    if gesture == 'draft-to-margin':
        assert tab.drawing and tab.pointCount == 2
    elif gesture == 'handle-to-margin':
        assert tab.pathEditing and not tab._edit_transaction_active


def test_cpr_secondary_drag_matches_its_binding(cpr_page):
    window, tab = cpr_page
    ref = tab.viewForRole('reference-a')
    viewport = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(viewport, 'cprPathOverlay')
    layer = named_item(viewport, 'viewportInteractionLayer')

    def drag(button, kind, col, row):
        start = overlay.mapToScene(overlay.pixel(col, row)).toPoint()
        QTest.mousePress(window, button, Qt.NoModifier, start)
        QTest.mouseMove(window, start + QPoint(20, 14), 20)
        QTest.mouseMove(window, start + QPoint(34, 24), 20)
        assert layer.property('effectiveCursorKind') == kind
        QTest.mouseRelease(window, button, Qt.NoModifier, start + QPoint(34, 24))
        assert layer.property('effectiveCursorKind') == 'cpr-path'

    first = tab.current_path
    zoom = ref.zoom
    drag(Qt.RightButton, 'zoom', 5, 10)
    assert tab.current_path == first and ref.zoom != zoom
    # Middle is mapped to the selected tool, including a CPR point drag.
    drag(Qt.MiddleButton, 'cpr-path', 5, 10)
    assert tab.current_path.control_points[0] != first.control_points[0]


@pytest.mark.parametrize('finish_key', [Qt.Key_Return, Qt.Key_Escape])
def test_saved_paths_stay_visible_and_read_only_while_drawing(cpr_page, finish_key):
    window, tab = cpr_page
    first = tab.current_path
    draw(tab, ((5, 22), (25, 22)))
    second = tab.current_path
    ref = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(ref, 'cprPathOverlay')

    def tap(col, row):
        pos = overlay.mapToScene(overlay.pixel(col, row)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)

    tap(32, 32)
    assert tab.drawing and tab.pointCount == 1
    assert len(overlay.property('otherTraces')) == 2
    # Check the painted overlay, including the previously selected path.
    grab = overlay.grabToImage()
    wait_until(lambda: not grab.image().isNull())
    image = grab.image()
    for row in (10, 22):
        pos = overlay.pixel(10, row) * (image.width() / overlay.width())
        assert any(image.pixelColor(round(pos.x()), round(pos.y()) + dy).alpha() > 0
                   for dy in (-1, 0, 1))

    tap(10, 10)  # On a saved segment: this click belongs to the draft.
    assert tab.drawing and tab.pointCount == 2 and tab.current_path == second
    QTest.keyClick(window, finish_key)
    assert not tab.drawing
    assert len(tab.paths) == (3 if finish_key == Qt.Key_Return else 2)
    if finish_key == Qt.Key_Escape:
        assert tab.selectedPathId == second.path_id
    for path in (first, second):
        tab.selectPath(path.path_id)
        assert tab.current_path == path


def test_cpr_lines_use_live_measurement_styles_and_keep_history_subdued(cpr_page):
    window, tab = cpr_page
    view = tab.viewForRole('reference-a')
    overlay = named_item(named_item(window.rootObject(), 'cprViewport-reference-a'), 'cprPathOverlay')
    settings = view.settingsController
    # Sample the actual line pixels from the transparent overlay. Avoid handles,
    # number labels and dashes by sampling a strip along the segment.
    def line_pixels(col, row):
        QTest.qWait(40)
        grab = overlay.grabToImage()
        wait_until(lambda: not grab.image().isNull())
        frame = grab.image()
        point = overlay.pixel(col, row) * (frame.width() / overlay.width())
        x, y = round(point.x()), round(point.y())
        return [frame.pixelColor(i, j) for i in range(x - 10, x + 11) for j in range(y - 2, y + 3)]

    def coverage(col, row, channel):
        colors = line_pixels(col, row)
        return max((c.alpha() for c in colors if channel(c) > 240 and c.blue() < 25), default=0)

    assert settings.setValue('measurement', 'completedColor', '#ff0000')
    assert settings.setValue('measurement', 'editingColor', '#00ff00')
    assert settings.setValue('measurement', 'lineWidth', 3)
    assert coverage(10, 10, lambda c: c.red()) > 200
    assert view.cprTap(10, 10, .4) and tab.pathEditing
    assert coverage(10, 10, lambda c: c.green()) > 200
    tab.finishEditing()
    for col in (5, 25):
        assert view.cprTap(col, 25, .4)
    assert tab.drawing
    assert coverage(15, 25, lambda c: c.green()) > 200
    assert 35 < coverage(10, 10, lambda c: c.red()) < 185
    assert tab.finishPath()
    assert coverage(15, 25, lambda c: c.red()) > 200


@pytest.mark.parametrize('delete_key', [Qt.Key_Delete, Qt.Key_Backspace])
def test_delete_on_control_point_removes_only_its_path(cpr_page, delete_key):
    window, tab = cpr_page
    ref = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(ref, 'cprPathOverlay')
    other = tab.selectedPathId
    draw(tab, ((8, 29), (28, 29)))
    end = overlay.mapToScene(overlay.pixel(8, 29)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.keyClick(window, delete_key)
    assert [p['pathId'] for p in tab.paths] == [other]
    QTest.keyClick(window, delete_key)
    assert len(tab.paths) == 1


def test_reference_drag_places_one_point_at_release(cpr_page):
    window, tab = cpr_page
    ref = named_item(window.rootObject(), 'cprViewport-reference-a')
    overlay = named_item(ref, 'cprPathOverlay')
    for i, (x, y) in enumerate(((8, 29), (25, 29))):
        end = overlay.mapToScene(overlay.pixel(x, y)).toPoint()
        start = end - QPoint(23, 16)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        marker = named_item(ref, 'pathPointPlacementPreview')
        assert marker.isVisible()
        QTest.mouseMove(window, start + QPoint(12, 7), 20)
        QTest.mouseMove(window, end, 20)
        assert len(tab.session_state()['draft']) == i
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
        assert not marker.isVisible()
        assert tab.drawing and tab.pointCount == i + 1
        point = tab.viewForRole('reference-a').cprPoints[-1]
        assert (point['column'], point['row']) == pytest.approx((x, y), abs=.2)


def test_sampling_guides_show_point_line_projection_and_share_color(cpr, tmp_path):
    from qt_dicom_viewer.i18n import message
    from qt_dicom_viewer.model import WindowLevel
    from qt_dicom_viewer.model.interaction import WindowLevelChange
    draw(cpr, ((5, 20), (35, 20)))
    # Keep the synthetic 0..4440 ramp visible when reviewing native screenshots.
    cpr.set_linked_window(WindowLevelChange(WindowLevel(center=2200, width=4400), False))
    cpr.setParameter('width', 20)
    cpr.setParameter('crossWidth', 20)
    cpr.setPositionMm(cpr.totalLength / 2)
    wait_until(lambda: cpr.ready)
    with displayed_cpr_page(cpr) as (window, tab):
        overlays = {role: named_item(named_item(window.rootObject(), 'cprViewport-' + role), 'cprPathOverlay')
                    for role in ('reference-a', 'reference-b', 'curved', 'cross')}
        labels = {role: named_item(overlay, 'cprSamplingGuideLabel')
                  for role, overlay in overlays.items() if role.startswith('reference')}
        color = overlays['reference-a'].property('samplingColor')

        def painted_cyan(role, column, row):
            overlay = overlays[role]
            QTest.qWait(40)
            grab = overlay.grabToImage()
            wait_until(lambda: not grab.image().isNull())
            image = grab.image()
            point = overlay.pixel(column, row) * (image.width()/overlay.width())
            found = any(image.pixelColor(x, y).alpha() > 100
                       and abs(image.pixelColor(x, y).hsvHueF() - color.hsvHueF()) < .02
                       and image.pixelColor(x, y).valueF() > .4
                       for x in range(max(0, round(point.x())-6), min(image.width(), round(point.x())+7))
                       for y in range(max(0, round(point.y())-6), min(image.height(), round(point.y())+7)))
            if not found:
                image.save(str(tmp_path / (role + '-overlay.png')))
            return found

        for angle, caption in [(0, 'cpr.samplingPoint'), (45, 'cpr.samplingProjection'), (90, 'cpr.samplingLine')]:
            tab.setParameter('angle', angle)
            wait_until(lambda: tab.ready)
            QTest.qWait(60)
            assert labels['reference-a'].property('text') == message(caption)
            for role in ('reference-a', 'reference-b'):
                guide = tab.viewForRole(role).cprGuides['samplingLine']
                assert painted_cyan(role, guide['centerColumn'], guide['centerRow'])
            curved = tab.viewForRole('curved')
            assert painted_cyan('curved', curved.cprGuides['positionColumn'], (curved.imageRows-1)/2)
            cross = tab.viewForRole('cross')
            assert painted_cyan('cross', (cross.imageColumns-1)/2, (cross.imageRows-1)/2)
            assert window.grabWindow().save(str(tmp_path / f'cpr-guides-{angle}.png'))
            if angle == 0:
                selector = named_item(window.rootObject(), 'cprPlane-0')
                point = selector.mapToScene(QPointF(selector.width()/2, selector.height()/2)).toPoint()
                for key, plane, label in [(Qt.Key_End, 'sagittal', 'cpr.samplingLine'),
                                          (Qt.Key_Home, 'axial', 'cpr.samplingPoint')]:
                    QTest.mouseClick(window, Qt.LeftButton, pos=point)
                    QTest.keyClick(window, key)
                    QTest.keyClick(window, Qt.Key_Return)
                    wait_until(lambda: tab.ready and tab.referencePlanes[0] == plane)
                    QTest.qWait(60)
                    assert labels['reference-a'].property('text') == message(label)
                    guide = tab.viewForRole('reference-a').cprGuides['samplingLine']
                    assert painted_cyan('reference-a', guide['centerColumn'], guide['centerRow'])
                    assert window.grabWindow().save(str(tmp_path / f'cpr-guides-{plane}.png'))

        geometry = tab.current_path
        ref = tab.viewForRole('reference-a')
        before = ref.cprGuides['samplingLine']
        ref.applyTransformAction('rotate:cw90')
        ref.applyTransformAction('rotate:mirror-h')
        ref.apply_zoom(1.2)
        assert ref.cprGuides['samplingLine'] == before
        assert painted_cyan('reference-a', before['centerColumn'], before['centerRow'])
        assert tab.current_path == geometry
        tab.setShowSamplingGuides(False)
        QTest.qWait(60)
        assert all(not tab.viewForRole(role).cprGuides for role in overlays)
        assert not labels['reference-a'].isVisible() and not labels['reference-b'].isVisible()
        assert not painted_cyan('reference-a', before['centerColumn'], before['centerRow'])
        tab.setShowSamplingGuides(True)
        assert painted_cyan('reference-a', before['centerColumn'], before['centerRow'])


def test_collapsed_oblique_sampling_marker_keeps_projection_dashes(cpr):
    draw(cpr, ((5, 20), (35, 20)))
    cpr.setParameter('width', 20)
    cpr.setPositionMm(cpr.totalLength / 2)
    wait_until(lambda: cpr.ready)
    with displayed_cpr_page(cpr) as (window, tab):
        overlay = named_item(named_item(window.rootObject(), 'cprViewport-reference-a'), 'cprPathOverlay')
        color = overlay.property('samplingColor')
        ring_pixels = []
        for angle in (0, 1):
            tab.setParameter('angle', angle)
            wait_until(lambda: tab.ready)
            QTest.qWait(60)
            guide = tab.viewForRole('reference-a').cprGuides['samplingLine']
            a = overlay.pixel(guide['startColumn'], guide['startRow'])
            b = overlay.pixel(guide['endColumn'], guide['endRow'])
            assert (b-a).manhattanLength() <= 4
            assert guide['projected'] == bool(angle)
            grab = overlay.grabToImage()
            wait_until(lambda: not grab.image().isNull())
            image = grab.image()
            scale = image.width()/overlay.width()
            center = overlay.pixel(guide['centerColumn'], guide['centerRow']) * scale
            ring_pixels.append(sum(
                3.8 <= ((x-center.x())**2 + (y-center.y())**2)**.5/scale <= 6.5
                and image.pixelColor(x, y).alpha() > 100
                and abs(image.pixelColor(x, y).hsvHueF() - color.hsvHueF()) < .02
                for x in range(int(center.x()-7*scale), int(center.x()+7*scale)+1)
                for y in range(int(center.y()-7*scale), int(center.y()+7*scale)+1)))
        assert ring_pixels[0] > 10
        assert ring_pixels[1] < ring_pixels[0] * .9


def test_sampling_projection_label_follows_visible_segment_after_pan(cpr):
    draw(cpr, ((5, 20), (35, 20)))
    cpr.setParameter('width', 20)
    cpr.setParameter('angle', 45)
    cpr.setPositionMm(cpr.totalLength / 2)
    wait_until(lambda: cpr.ready)
    with displayed_cpr_page(cpr) as (window, tab):
        ref = tab.viewForRole('reference-a')
        overlay = named_item(named_item(window.rootObject(), 'cprViewport-reference-a'), 'cprPathOverlay')
        label = named_item(overlay, 'cprSamplingGuideLabel')
        guide = ref.cprGuides['samplingLine']
        assert guide['projected']
        center = overlay.pixel(guide['centerColumn'], guide['centerRow'])
        ref.apply_pan(0, -center.y()-10)
        QTest.qWait(60)
        a = overlay.pixel(guide['startColumn'], guide['startRow'])
        b = overlay.pixel(guide['endColumn'], guide['endRow'])
        assert min(a.y(), b.y()) < 0 < max(a.y(), b.y())
        assert overlay.pixel(guide['centerColumn'], guide['centerRow']).y() < 0
        assert label.isVisible()
        assert 0 <= label.y() <= overlay.height()-label.height()
        ref.apply_pan(0, -overlay.height())
        QTest.qWait(60)
        assert not label.isVisible()


@pytest.mark.parametrize('transform', ['none', 'rotate:cw90', 'rotate:mirror-h'])
def test_cross_section_marks_sampling_line_continuation(cpr, tmp_path, transform):
    from qt_dicom_viewer.model import WindowLevel
    from qt_dicom_viewer.model.interaction import WindowLevelChange
    draw(cpr, ((5, 20), (35, 20)))
    cpr.set_linked_window(WindowLevelChange(WindowLevel(center=2200, width=4400), False))
    cpr.setParameter('crossWidth', 40)
    cpr.setPositionMm(cpr.totalLength / 2)
    wait_until(lambda: cpr.ready)
    with displayed_cpr_page(cpr) as (window, tab):
        cross = tab.viewForRole('cross')
        if transform != 'none':
            cross.applyTransformAction(transform)
        cross.setZoom(.75)
        overlay = named_item(named_item(window.rootObject(), 'cprViewport-cross'), 'cprPathOverlay')
        color = overlay.property('samplingColor')

        def continuation_wings(ends=None):
            QTest.qWait(60)
            grab = overlay.grabToImage()
            wait_until(lambda: not grab.image().isNull())
            image = grab.image()
            scale = image.width()/overlay.width()
            center = overlay.pixel((cross.imageColumns-1)/2, (cross.imageRows-1)/2)
            found = []
            ends = ends or [overlay.pixel(col, (cross.imageRows-1)/2)
                            for col in (0, cross.imageColumns-1)]
            for end in ends:
                delta = end-center
                length = (delta.x()**2 + delta.y()**2)**.5
                direction = delta/length
                perpendicular = QPointF(-direction.y(), direction.x())
                for side in (-1, 1):
                    # A continuation chevron sits just inside the image edge;
                    # a true endpoint cap has no inward diagonal wings.
                    wing = (end - direction*7 + perpendicular*(side*3))*scale
                    found.append(any(
                        image.pixelColor(x, y).alpha() > 100
                        and abs(image.pixelColor(x, y).hsvHueF()-color.hsvHueF()) < .02
                        and image.pixelColor(x, y).valueF() > .4
                        for x in range(round(wing.x()-scale), round(wing.x()+scale)+1)
                        for y in range(round(wing.y()-scale), round(wing.y()+scale)+1)))
            return found

        for width in (20, 40, 50, 40):
            tab.setParameter('width', width)
            wait_until(lambda: tab.ready)
            assert continuation_wings() == [width > 40]*4
            assert window.grabWindow().save(str(tmp_path / f'cross-sampling-{width}.png'))
        tab.setParameter('width', 50)
        wait_until(lambda: tab.ready)
        tab.setShowSamplingGuides(False)
        assert continuation_wings() == [False]*4
        tab.setShowSamplingGuides(True)
        assert continuation_wings() == [True]*4
        if transform == 'none':
            tab.setParameter('width', 20)
            wait_until(lambda: tab.ready)
            row = (cross.imageRows-1)/2
            columns = [(cross.imageColumns-1)*fraction for fraction in (.25, .75)]
            start = overlay.pixel(columns[0], row)
            cross.apply_pan(1-start.x(), 0)
            QTest.qWait(60)
            ends = [overlay.pixel(col, row) for col in columns]
            # A complete line whose endpoint is just inside the viewport still
            # has a real endpoint, not a continuation arrow.
            assert continuation_wings(ends) == [False]*4
            cross.apply_pan(cross.panX-11, 0)
            QTest.qWait(60)
            assert overlay.pixel(columns[0], row).x() == pytest.approx(-10, abs=.01)
            end = overlay.pixel(columns[1], row)
            assert continuation_wings([QPointF(0, end.y()), end]) == [True, True, False, False]


def test_sampling_end_on_label_describes_geometry_not_display_zoom(cpr):
    from qt_dicom_viewer.i18n import message
    draw(cpr, ((5, 20), (35, 20)))
    cpr.setParameter('width', 1)
    cpr.setPositionMm(cpr.totalLength / 2)
    wait_until(lambda: cpr.ready)
    with displayed_cpr_page(cpr) as (window, tab):
        ref = tab.viewForRole('reference-a')
        ref.setZoom(.1)
        overlay = named_item(named_item(window.rootObject(), 'cprViewport-reference-a'), 'cprPathOverlay')
        label = named_item(overlay, 'cprSamplingGuideLabel')
        for angle, caption in [(0, 'cpr.samplingPoint'), (90, 'cpr.samplingLine')]:
            tab.setParameter('angle', angle)
            wait_until(lambda: tab.ready)
            QTest.qWait(60)
            guide = ref.cprGuides['samplingLine']
            a = overlay.pixel(guide['startColumn'], guide['startRow'])
            b = overlay.pixel(guide['endColumn'], guide['endRow'])
            assert (b-a).manhattanLength() < 4
            assert not guide['projected']
            assert label.property('text') == message(caption)
