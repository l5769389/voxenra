"""Layout changes preserve image state; 3D references use actual patient geometry."""
from dataclasses import replace
from pathlib import Path
import os

import numpy as np
import pytest
from PySide6.QtCore import QObject, QUrl, QPoint, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from vtkmodules.vtkRenderingCore import vtkRenderer
from shiboken6 import delete

from qt_dicom_viewer.core.mpr_layout import MPR_LAYOUTS, plane_box_intersection
from qt_dicom_viewer.core.volume_view import view_basis, rotate_drag, camera_parameters
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.model import MprPlane
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
from qt_dicom_viewer.ui.mpr_reference_overlay import MprReferenceOverlay
from test_pet_fusion import paired_series
from test_measurement_qml import qt_app, _visual_children
from test_volume_view import volume
from test_series_sidebar import sidebar_scene


@pytest.fixture(params=["CT", "PT"])
def loaded(qt_app, paired_series, request):
    catalog, ct, pet = paired_series
    host = QObject()
    host._settings_controller = SettingsController(host, path=False)
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider, host)
    worker = DicomRenderWorker(catalog, VolumeManager())
    failures, requests = [], []
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(failures.append)
    workspace.renderRequested.connect(requests.append)
    workspace.renderRequested.connect(worker.handleRenderRequest)
    series = ct if request.param == "CT" else pet
    workspace.createTab(series.series_instance_uid, "MPR layout", "mpr")
    assert not failures
    tab = workspace.activeTab
    yield workspace, tab, provider, requests, failures
    workspace.shutdown()


def move(tab, center):
    tab.mprLayout.move_center(center)


def rotate(tab, angle=.23):
    if hasattr(tab, "_rotate_plane"):
        tab._rotate_plane(MprPlane.AXIAL, angle)
    else:
        tab._handle_crosshair_rotation_requested(MprPlane.AXIAL, angle)


def test_layout_reuses_volume_and_preserves_mpr_and_view_state(loaded):
    workspace, tab, provider, requests, failures = loaded
    layout = tab.mprLayout
    initial_views = tuple(tab.viewports_by_id.values())
    state, frames = tab._target_mpr_state, [v._frame_meta for v in initial_views]
    before = len(requests)
    assert layout.volumeViewport.volume is None
    for key in (*MPR_LAYOUTS, "not-a-layout", "right", "quad"):
        layout.setLayout(key)
        assert tuple(tab.viewports_by_id.values()) == initial_views
        assert tab._target_mpr_state == state
        assert [v._frame_meta for v in initial_views] == frames
    assert len(requests) == before  # no new decoding or reslicing on layout changes
    assert layout.volumeViewport.volume is layout._pending_volume
    assert layout.volumeViewport.loadState == "ready"
    assert layout.volumeViewport._host is None  # native GPU host remains lazy
    tab.focusSingleViewport(initial_views[0].viewportId)
    layout.setLayout(layout.layout)
    assert tab.focusedViewportId == ""
    assert not failures


def test_layout_language_switch_preserves_geometry_and_render_state(loaded, tmp_path):
    from qt_dicom_viewer.ui.controller.language_controller import LanguageController
    from qt_dicom_viewer.ui.controller.manual_tab_controller import ManualTabController

    _, tab, _, requests, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    language = LanguageController(SettingsController(path=False), root=tmp_path / "languages")
    manual = ManualTabController()
    manual.selectChapter("mpr")
    options = layout.options  # Register the property for live language updates.
    assert options[-1]["label"] == "四宫格 · 含 3D"
    updates = []
    layout._i18n_options.connect(lambda: updates.append(True))
    before, state, camera = len(requests), tab._target_mpr_state, layout.volumeViewport.state
    try:
        for locale, label, title in (("en-US", "Four views with 3D", "Choose a layout"),
                                     ("zh-CN", "四宫格 · 含 3D", "选择布局")):
            language.selectLanguage(locale)
            assert layout.options[-1]["label"] == label
            assert manual.currentChapter["sections"][4]["title"] == title
            toolbar = next(tool for tool in tab.toolController.tools if tool["toolType"] == "mpr-layout")
            assert toolbar["label"] == ("View layout" if locale == "en-US" else "视图布局")
            assert tab._target_mpr_state is state and layout.volumeViewport.state == camera
            assert layout.layout == "quad" and len(requests) == before
        assert updates and not failures
    finally:
        language.shutdown()


def test_reference_selection_routes_tools_and_restores_last_slice(loaded):
    _, tab, _, _, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    original = tab.activeViewport
    tab.toolController.activateTool("pan")
    tab.activateViewport(layout.volumeViewport.viewportId)
    assert tab.activeViewport is layout.volumeViewport
    assert tab.activeToolController is layout.volumeTools
    tools = [item["toolType"] for item in tab.activeToolController.tools]
    assert {"volume-rotate", "volume-preset", "volume-direction", "mpr-layout", "viewport-settings", "export"} <= set(tools)
    assert not {"measure", "segmentation", "volume-crop", "volume-bed"} & set(tools)
    assert tools[-1] == "reset"
    assert isinstance(layout.volumeTools.activeToolLabel, str)
    assert isinstance(layout.volumeTools.activeToolIcon, str)
    layout.volumeTools.activateTool("zoom")
    layout.volumeViewport.setZoom(3)
    layout.volumeTools.resetActiveTool()
    assert layout.volumeViewport.zoom == 1
    layout.volumeTools.activateTool("mpr-layout")
    assert layout.volumeTools.activePanel == "mpr-layout"
    record = tab_snapshot(tab)
    tab.activateViewport(original.viewportId)
    assert not layout.active and tab.activeToolController is tab.toolController
    assert tab.toolController.activeTool == "pan"
    apply_tab_snapshot(tab, record)
    assert layout.active and tab.activeViewport is layout.volumeViewport
    assert layout.volumeTools.activePanel == "mpr-layout"
    layout.setLayout("columns")
    assert not layout.active and tab.activeViewport is original
    assert tab.activeToolController is tab.toolController
    assert not failures



def test_rotation_link_restore_preserves_explicit_choice_and_defaults_missing_field(loaded):
    _, tab, _, _, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    assert layout.linkRotation
    rotate(tab)
    layout.setLinkRotation(False)
    record = layout.snapshot()
    frame = tab._target_mpr_state.frame
    layout.setLinkRotation(True)
    layout.restore(record)
    assert not layout.linkRotation
    assert tab._target_mpr_state.frame == frame
    assert layout.volumeViewport.state == record["camera"]
    del record["linked"]
    layout.restore(record)
    assert layout.linkRotation
    assert tab._target_mpr_state.frame == frame
    assert layout.volumeViewport.state == record["camera"]
    assert not failures


def test_viewport_settings_reset_from_slice_and_volume_tools(loaded):
    _, tab, _, _, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    for viewport_id in (next(iter(tab.viewports_by_id)), layout.volumeViewport.viewportId):
        tab.activateViewport(viewport_id)
        layout.setLinkRotation(False)
        layout.setReferenceMode("hidden")
        camera, frame = layout.volumeViewport.state, tab._target_mpr_state.frame
        tab.activeToolController.activateTool("viewport-settings")
        tab.activeToolController.resetActiveTool()
        assert layout.linkRotation and layout.referenceMode == "planes"
        assert layout.volumeViewport.state == camera
        assert tab._target_mpr_state.frame == frame
    assert not failures

def test_reference_pet_units_use_shared_mpr_loading(loaded):
    _, tab, _, requests, failures = loaded
    if not hasattr(tab, "pet_display"):
        return
    from qt_dicom_viewer.model.render_models import VolumeLoadRequest
    layout = tab.mprLayout
    layout.setLayout("quad")
    layout.activate()
    view = layout.volumeViewport
    unit = next(o["unitId"] for o in view.petUnitOptions if o["unitId"] != view.petUnitId)
    before = len(requests)
    camera = view.state
    view.setPetUnit(unit)
    assert view.petUnitId == unit == tab.pet_display.target.meta.unit_id
    assert view.volume is layout._pending_volume
    assert view.state == camera
    assert not any(isinstance(req, VolumeLoadRequest) for req in requests[before:])
    assert not failures


def test_marker_move_and_bidirectional_optional_rotation(loaded):
    _, tab, _, _, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    view = layout.volumeViewport
    assert layout.linkRotation
    frame = tab._target_mpr_state.frame
    camera = view_basis(view.state)
    rotate(tab)
    delta = tab._target_mpr_state.frame.mpr_to_patient[:3, :3] @ frame.mpr_to_patient[:3, :3].T
    np.testing.assert_allclose(view_basis(view.state), delta @ camera, atol=1e-10)
    frame = tab._target_mpr_state.frame
    before = view.state
    view._set_state(rotate_drag(before, (25, 20), (95, 72), (200, 180)))
    delta = view_basis(view.state) @ view_basis(before).T
    np.testing.assert_allclose(tab._target_mpr_state.frame.mpr_to_patient[:3, :3],
                               delta @ frame.mpr_to_patient[:3, :3], atol=1e-10)
    # Zoom and pan never rotate or displace MPR.
    frame = tab._target_mpr_state.frame
    view._set_state(replace(view.state, zoom=1.5, pan=(.1, .2)))
    assert tab._target_mpr_state.frame == frame
    layout.setLinkRotation(False)
    camera = view.state
    rotate(tab)
    assert view.state == camera
    frame = tab._target_mpr_state.frame
    view._set_state(rotate_drag(view.state, (15, 40), (65, 75), (200, 180)))
    assert tab._target_mpr_state.frame == frame
    center = view.volume.geometry.center_patient
    move(tab, center)
    np.testing.assert_allclose(layout._last_frame.center_patient, center)
    # Hit and drag the actual projected point, even with oblique camera/pan/zoom.
    size = (500, 450)
    params = camera_parameters(view.volume.geometry, view.state, size)
    basis = view_basis(view.state)
    delta = np.asarray(center) - params["focal"]
    factor = size[1]/(2*params["scale"])
    screen = (size[0]/2+np.dot(delta, basis[:, 0])*factor,
              size[1]/2-np.dot(delta, basis[:, 1])*factor)
    # The marker retains its left binding; right-drag zooms without moving MPR.
    frame, before_zoom = tab._target_mpr_state.frame, view.state.zoom
    view.begin_drag(screen, size, 2)
    assert view._marker_drag is None
    view.update_drag((screen[0]+2, screen[1]-20))
    view.end_drag()
    assert view.state.zoom != before_zoom
    assert tab._target_mpr_state.frame == frame
    view._set_state(replace(view.state, zoom=before_zoom))
    view.begin_drag(screen, size)
    assert view._marker_drag is not None
    view.update_drag((screen[0]+2, screen[1]+1))
    view.end_drag()
    assert tab._target_mpr_state.frame.center_patient != center
    assert view._marker_drag is None
    assert not failures


def test_reference_planes_clip_to_oblique_anisotropic_volume(volume):
    g = volume.geometry
    center = np.asarray(g.center_patient)
    for normal in ((0., 0., 1.), (0., 1., 0.), (1., 0., 0.), tuple(np.ones(3)/np.sqrt(3))):
        polygon = plane_box_intersection(g, center, normal)
        assert 3 <= len(polygon) <= 6
        for p in polygon:
            assert np.dot(np.array(p)-center, normal) == pytest.approx(0, abs=1e-6)
            voxel = (g.patient_to_voxel @ [*p, 1])[:3]
            assert np.all(voxel >= -1e-6)
            assert np.all(voxel <= np.array((g.slice_count-1, g.rows-1, g.columns-1))+1e-6)
    assert plane_box_intersection(g, center + 1000, (0, 0, 1)) == ()


def test_four_d_reference_tracks_phase_and_ignores_closed_updates(qt_app, tmp_path):
    from test_four_d import _cross_series_four_d
    from qt_dicom_viewer.application.series_catalog import SeriesCatalog
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    series = _cross_series_four_d(tmp_path)
    catalog = SeriesCatalog()
    catalog.update(DicomFolderScanSnapshot(folder=tmp_path, series=series,
        total_file_count=6, dicom_file_count=6, skipped_file_count=0))
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    worker = DicomRenderWorker(catalog, VolumeManager())
    failures = []
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(failures.append)
    workspace.renderRequested.connect(worker.handleRenderRequest)
    workspace.createTab(series[0].series_instance_uid, "4D layout", "4d")
    tab = workspace.activeTab
    layout = tab.mprLayout
    try:
        layout.setLayout("quad")
        volume = layout.volumeViewport.volume
        state = tab._target_mpr_state
        for index in (1, 2, 0):
            tab.setPhaseIndex(index)
            assert layout.volumeViewport.volume.modality_pixels.mean() == pytest.approx((index+1)*10)
            assert tab._target_mpr_state == state
        workspace.closeTab(tab.tab_config.tab_id)
        layout.accept_volume(volume)
        assert layout._disposed and layout._pending_volume is None
        assert not failures
    finally:
        workspace.shutdown()


def test_reference_mode_colors_and_snapshot_restore(loaded):
    _, tab, _, _, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    rotate(tab)
    layout.setReferenceMode("point")
    layout.setLinkRotation(True)
    view = layout.volumeViewport
    view._set_state(replace(view.state, zoom=2))
    record = tab_snapshot(tab)
    layout.setLayout("columns")
    layout.setLinkRotation(False)
    layout.setReferenceMode("hidden")
    view._set_state(replace(view.state, zoom=1))
    apply_tab_snapshot(tab, record)
    assert layout.layout == "quad" and layout.referenceMode == "point" and layout.linkRotation
    assert view.state.zoom == 2
    renderer = vtkRenderer()
    overlay = MprReferenceOverlay(renderer)
    colors = ("#ff0000", "#00ff00", "#0000ff")
    for mode in ("planes", "point", "hidden"):
        overlay.update(view.volume.geometry, tab._target_mpr_state, mode, colors)
        assert (overlay.center is None) == (mode == "hidden")
        assert all(bool(a.GetVisibility()) == (mode == "planes") for _, a in overlay.planes)
    assert not failures


def test_pet_reference_restore_before_first_volume_and_reset_uses_shared_unit(loaded):
    _, tab, _, requests, failures = loaded
    if not hasattr(tab, "pet_display"):
        return
    from qt_dicom_viewer.ui.controller.tab.mpr_layout_controller import MprLayoutController
    layout = tab.mprLayout
    layout.setLayout("quad")
    view = layout.volumeViewport
    view.setPetUpper(.25)
    view.setPetOpacity(.4)
    state = layout.snapshot()
    restored = MprLayoutController(tab)
    try:
        restored.restore(state)
        assert restored.volumeViewport.volume is None
        restored.accept_volume(view.volume)
        assert restored.volumeViewport.petUpper == pytest.approx(.25)
        assert restored.volumeViewport.petOpacity == pytest.approx(.4)
        before = len(requests)
        restored.volumeViewport.reset_all_view_state()
        assert restored.volumeViewport.loadState == "ready"
        assert restored.volumeViewport._request_id is None
        assert len(requests) == before
        assert not failures
    finally:
        restored.dispose()


@pytest.mark.parametrize("size", [(1100, 760), (780, 550)])
def test_real_qml_layout_choices_bounds_and_state(loaded, monkeypatch, size):
    workspace, tab, provider, _, failures = loaded
    # Native VTK embedding is tested separately on Cocoa; this test exercises real QML.
    monkeypatch.setattr(type(tab.mprLayout.volumeViewport), "ensureNativeView", lambda self: None)
    view = QQuickView()
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.engine().addImageProvider("dicom", provider)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(*size)
    view.setInitialProperties(dict(workspace=workspace, tabController=tab, rightPanelWidth=220))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/MprVoiWorkspace.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(80)
    try:
        # Exercise the real toolbar entry rather than opening its panel directly.
        items = list(_visual_children(view.rootObject()))
        entry = next(i for i in items if i.objectName() == "primaryTool-mpr-layout")
        assert entry.isVisible() and entry.isEnabled()
        assert entry.width() > 0 and entry.height() > 0
        point = entry.mapToScene(entry.boundingRect().center()).toPoint()
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(35)
        assert tab.toolController.activePanel == "mpr-layout"
        assert any(i.objectName() == "mprLayoutPanel" and i.isVisible()
                   for i in _visual_children(view.rootObject()))
        for key in MPR_LAYOUTS:
            items = list(_visual_children(view.rootObject()))
            button = next(i for i in items if i.objectName() == "mprLayout-"+key)
            p = button.mapToScene(button.boundingRect().center()).toPoint()
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, p)
            QTest.qWait(35)
            assert tab.mprLayout.layout == key
            items = list(_visual_children(view.rootObject()))
            cells = [i for i in items if i.objectName().startswith("viewportCell-") and i.isVisible()]
            reference = next(i for i in items if i.objectName() == "mprReferenceViewport")
            assert reference.isVisible() == (key == "quad")
            if reference.isVisible(): cells.append(reference)
            for i, a in enumerate(cells):
                assert a.width() > 0 and a.height() > 0
                assert a.x() >= 0 and a.y() >= 0
                assert a.x()+a.width() <= a.parentItem().width()+1
                assert a.y()+a.height() <= a.parentItem().height()+1
                for b in cells[i+1:]:
                    assert min(a.x()+a.width(), b.x()+b.width()) <= max(a.x(), b.x())+1 \
                        or min(a.y()+a.height(), b.y()+b.height()) <= max(a.y(), b.y())+1
        reference = next(i for i in items if i.objectName() == "mprReferenceViewport")
        # The header selects 3D even in software QML tests without a native host.
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                         reference.mapToScene(reference.boundingRect().topLeft()).toPoint() + QPoint(20, 16))
        QTest.qWait(50)
        assert tab.activeViewport is tab.mprLayout.volumeViewport
        buttons = {i.objectName(): i for i in _visual_children(view.rootObject()) if i.isVisible()}
        assert "primaryTool-volume-rotate" in buttons and "primaryTool-mpr-layout" in buttons
        assert "primaryTool-measure" not in buttons
        zoom = buttons["primaryTool-zoom"]
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                         zoom.mapToScene(zoom.boundingRect().center()).toPoint())
        QTest.qWait(30)
        assert tab.activeToolController.activeTool == "zoom"
        frame = next(i for i in _visual_children(view.rootObject()) if i.objectName() == "volumeViewportFrame")
        assert frame.property("active")
        slice_view = next(iter(tab.viewports_by_id.values()))
        canvas = next(i for i in _visual_children(view.rootObject())
                      if i.objectName() == "imageViewport-" + slice_view.viewportId)
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                         canvas.mapToScene(canvas.boundingRect().center()).toPoint())
        QTest.qWait(30)
        assert tab.activeViewport is slice_view and not frame.property("active")
        assert not warnings, warnings
        assert not failures
    finally:
        view.close()
        delete(view)
        QTest.qWait(20)


@pytest.mark.skipif(os.environ.get("VOXENRA_NATIVE_QA") != "1", reason="requires native desktop window")
def test_native_four_up_reference_view(loaded, tmp_path):
    workspace, tab, provider, _, failures = loaded
    layout = tab.mprLayout
    layout.setLayout("quad")
    view = QQuickView()
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.engine().addImageProvider("dicom", provider)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1200, 820)
    view.setInitialProperties(dict(workspace=workspace, tabController=tab, rightPanelWidth=250))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/MprVoiWorkspace.qml")))
    view.show()
    tab.toolController.activateTool("mpr-layout")
    try:
        QTest.qWait(600)
        v = layout.volumeViewport
        host = v._host
        assert host and host._active and host.backend._initialized
        assert v.loadState == "ready", v.errorMessage
        assert host.backend.mpr_reference.center == tab._target_mpr_state.frame.center_patient
        widget = host.vtk_widget
        original_size = widget.size()
        frame_before, camera_before, display_before = tab._target_mpr_state, v.state, v.display_state
        QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
        QTest.qWait(150)
        assert tab.focusedViewportId == v.viewportId and tab.activeViewport is v
        assert widget.width() > original_size.width() * 1.8
        assert widget.height() > original_size.height() * 1.8
        visible_cells = [i for i in _visual_children(view.rootObject())
                         if i.objectName().startswith('viewportCell-') and i.isVisible()]
        assert not visible_cells
        assert (tab._target_mpr_state, v.state, v.display_state) == (frame_before, camera_before, display_before)
        assert tab_snapshot(tab)['focusedView']
        QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
        QTest.qWait(150)
        assert tab.focusedViewportId == '' and widget.size() == original_size
        assert len([i for i in _visual_children(view.rootObject())
                    if i.objectName().startswith('viewportCell-') and i.isVisible()]) == 3
        layout.setLinkRotation(True)
        frame, camera = tab._target_mpr_state.frame, v.state
        QTest.mousePress(widget, Qt.RightButton, Qt.NoModifier, QPoint(90, 130))
        QTest.mouseMove(widget, QPoint(120, 80), 25)
        QTest.mouseRelease(widget, Qt.RightButton, Qt.NoModifier, QPoint(120, 80))
        QTest.qWait(100)
        assert v.state.zoom != camera.zoom and v.state.rotation == camera.rotation
        assert tab._target_mpr_state.frame == frame
        assert v.activeInteraction == "volume:rotate"
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(30, 30))
        QTest.mouseMove(widget, QPoint(95, 75), 25)
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(95, 75))
        QTest.qWait(250)
        assert tab._target_mpr_state.frame != frame
        assert tab.activeViewport is v and tab.activeToolController is layout.volumeTools
        buttons = {i.objectName(): i for i in _visual_children(view.rootObject()) if i.isVisible()}
        pan = buttons["primaryTool-pan"]
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, pan.mapToScene(pan.boundingRect().center()).toPoint())
        QTest.qWait(40)
        assert v.activeInteraction == "pan"
        assert view.grabWindow().save(str(tmp_path / "mpr-shared-toolbar.png"))
        image = v.snapshot_image()
        assert not image.isNull()
        assert image.save(str(tmp_path / "mpr-reference.png"))
        layout.setLayout("rows")
        QTest.qWait(100)
        assert not host._active
        layout.setLayout("quad")
        view.resize(960, 680)
        QTest.qWait(250)
        assert host._active and v.loadState == "ready"
        # Close while the native child is attached, as in the real tab strip.
        workspace.closeTab(tab.tab_config.tab_id)
        QTest.qWait(50)
        assert host._disposed and not host._active
        assert not warnings
        assert not failures
    finally:
        view.close()
        delete(view)
        QTest.qWait(30)


def test_main_toolbar_tracks_reference_across_tabs_and_windows(sidebar_scene, monkeypatch):
    from test_dicom_tags import wait_until
    from test_tag_qml import find, click, descendants
    from test_tab_windows import detached
    window, app, records, warnings = sidebar_scene
    registry = app.workspaceController
    registry.createTab(records[0].series_instance_uid, "MPR", "mpr")
    wait_until(lambda: registry.activeLoadState.status == "ready")
    tab = registry.activeTab
    reference = tab.mprLayout.volumeViewport
    monkeypatch.setattr(type(reference), "ensureNativeView", lambda self: None)
    tab.mprLayout.setLayout("quad")
    tab.mprLayout.activate()
    find(window, "primaryTool-volume-rotate")
    QTest.qWait(50)  # Wait for the replacement toolbar to finish layout.
    click(window, find(window, "primaryTool-pan"))
    assert tab.activeViewport is reference and tab.activeToolController.activeTool == "pan"
    assert find(window, "mprReferenceViewport").isVisible()
    registry.openSettings()
    registry.activateTabId(tab.tab_config.tab_id)
    assert find(window, "primaryTool-volume-rotate").isVisible()
    assert tab.activeViewport is reference and tab.activeToolController.activeTool == "pan"
    session, other = detached(app, tab)
    assert find(other, "mprReferenceViewport").isVisible()
    click(other, find(other, "primaryTool-mpr-layout"))
    click(other, find(other, "mprLayout-columns"))
    assert not tab.mprLayout.active
    assert find(other, "primaryTool-measure").isVisible()
    app.windowManager.moveToMain(tab.tab_config.tab_id)
    wait_until(lambda: len(app.windowManager.sessions) == 1)
    assert find(window, "primaryTool-measure").isVisible()
    assert not any(i.isVisible() and i.objectName() == "mprReferenceViewport"
                   for i in descendants(window.contentItem()))
    assert not warnings, warnings


def test_four_d_playback_waits_for_visible_reference_frame(qt_app, tmp_path):
    from types import SimpleNamespace
    from test_four_d import _cross_series_four_d
    from qt_dicom_viewer.application.series_catalog import SeriesCatalog
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    records = _cross_series_four_d(tmp_path)
    catalog = SeriesCatalog()
    catalog.update(DicomFolderScanSnapshot(folder=tmp_path, series=records,
                   total_file_count=6, dicom_file_count=6, skipped_file_count=0))
    workspace = WorkspaceController(catalog, DicomImageProvider())
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(workspace.handleRenderResult)
    workspace.renderRequested.connect(worker.handleRenderRequest)
    workspace.createTab(records[0].series_instance_uid, '4D', '4d')
    tab = workspace.activeTab
    layout = tab.mprLayout
    layout.setLayout('quad')
    view = layout.volumeViewport
    # GPU completion is independent from successful decoding and VTK upload.
    native = SimpleNamespace(_active=True, frame_ready=False)
    view._host = native
    view.loadStateChanged.connect(lambda: setattr(native, 'frame_ready', False))
    try:
        tab.setPlaying(True)
        tab._phase_timer.stop()
        tab._handle_playback_timeout()
        assert tab.currentPhaseIndex == 0
        native.frame_ready = True
        tab._handle_playback_timeout()
        assert tab.currentPhaseIndex == 1
        tab._handle_playback_timeout()
        assert tab.currentPhaseIndex == 1
        # A hidden native view cannot hold up slice-only playback.
        native._active = False
        tab._handle_playback_timeout()
        assert tab.currentPhaseIndex == 2
        native._active = True
        native.frame_ready = True
        tab._handle_playback_timeout()
        assert tab.currentPhaseIndex == 0
        view.render_failed('GPU failure')
        assert not tab.playing
        assert tab.toolController._locked_tool is None
        assert layout.volumeTools._locked_tool is None
    finally:
        view._host = None
        workspace.shutdown()


def test_four_d_reference_selection_keeps_temporal_playback_tools(qt_app):
    from test_four_d import _ready_four_d_tab
    tab, _, _ = _ready_four_d_tab()
    layout = tab.mprLayout
    try:
        layout.setLayout('quad')
        layout.activate()
        tools = tab.activeToolController
        assert tools is layout.volumeTools
        play = next(t for t in tools.tools if t['toolType'] == 'play')
        assert play['iconName'] == 'cine-4d-play'
        tab.setPlaying(True)
        assert tools.activePanel == 'play'
        assert tools.activeToolIcon == 'cine-4d-play'
        assert '4D' in tools.activeToolLabel
        tools.activateTool('mpr-layout')
        assert tools.activePanel == 'play'
        tab.pausePlayback()
        tools.activateTool('volume-rotate')
        assert tools.activeTool == 'volume-rotate'
    finally:
        tab.dispose()


def test_reference_corner_title_tracks_size_dpi_and_corner_preferences():
    from vtkmodules.vtkRenderingCore import vtkRenderWindow
    renderer = vtkRenderer()
    window = vtkRenderWindow()
    window.AddRenderer(renderer)
    window.SetSize(800, 600)
    window.SetDPI(72)
    overlay = MprReferenceOverlay(renderer)
    # The title stays visible even when the spatial reference is hidden.
    overlay.configure_title({'fontSize': 20, 'colorMode': 'custom', 'color': '#ff8000'})
    overlay.project_marker(2)
    assert overlay.title.GetInput() == '3D'
    assert overlay.title.GetVisibility()
    assert not overlay.marker.GetVisibility()
    assert overlay.title.GetPosition() == (20, 580)
    assert overlay.title.GetTextProperty().GetFontSize() == 34
    np.testing.assert_allclose(overlay.title.GetTextProperty().GetColor(), (1, 128/255, 0))
    window.SetSize(400, 300)
    overlay.project_marker(1)
    assert overlay.title.GetPosition() == (10, 290)
    assert overlay.title.GetTextProperty().GetFontSize() == 17
    overlay.configure_title({'enabled': False})
    overlay.project_marker()
    assert not overlay.title.GetVisibility()
    window.Finalize()


def test_reference_maximize_restores_layout_and_workspace_state(loaded):
    _, tab, _, _, _ = loaded
    layout = tab.mprLayout
    layout.setLayout('quad')
    volume = layout.volumeViewport
    volume.setZoom(1.7)
    camera, display, state = volume.state, volume.display_state, tab._target_mpr_state
    layout.toggleMaximized()
    assert tab.focusedViewportId == volume.viewportId and tab.activeViewport is volume
    assert layout.layout == 'quad'
    saved = tab_snapshot(tab)
    layout.toggleMaximized()
    assert tab.focusedViewportId == '' and tab.activeViewport is volume
    assert (volume.state, volume.display_state, tab._target_mpr_state) == (camera, display, state)
    apply_tab_snapshot(tab, saved)
    assert tab.focusedViewportId == volume.viewportId and tab.activeViewport is volume
    tab.activateViewport(next(iter(tab.viewports_by_id)))
    assert tab.focusedViewportId == ''
    layout.toggleMaximized()
    layout.setLayout('rows')
    assert tab.focusedViewportId == '' and not layout.active


def test_workspace_restores_slice_and_reference_tool_selections(loaded):
    _, tab, _, _, failures = loaded
    tab.toolController.activateTool('measure')
    tab.toolController.selectInteraction('measure:curve')
    tab.mprLayout.volumeTools.activateTool('viewport-settings')
    record = tab_snapshot(tab)
    tab.toolController.activateTool('window')
    tab.mprLayout.volumeTools.activateTool('pan')
    apply_tab_snapshot(tab, record)
    assert tab.toolController.activeTool == 'measure'
    assert tab.toolController.activeInteraction == 'measure:curve'
    assert tab.mprLayout.volumeTools.activeTool == 'viewport-settings'
    assert not tab.playing and not failures
