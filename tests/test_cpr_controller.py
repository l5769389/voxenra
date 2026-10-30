from dataclasses import replace

import numpy as np
import pytest

from test_dicom_tags import qt_app, wait_until
from test_mpr_reslicer import _volume
from test_viewport_controller_hierarchy import _series_meta
from qt_dicom_viewer.model import TabConfig, TabType, WindowLevel
from qt_dicom_viewer.model.interaction import WindowLevelChange
from qt_dicom_viewer.model.render_models import VolumeLoadResult


@pytest.fixture
def cpr(qt_app):
    from qt_dicom_viewer.ui.controller.tab.cpr_tab_controller import CprTabController
    tab = CprTabController(TabConfig("cpr", "CPR", TabType.CPR, (_series_meta(),)))
    requests = []
    tab.renderRequested.connect(requests.append)
    tab.init_render()
    req = requests[-1]
    z, y, x = np.indices((41, 41, 41))
    tab.handleRenderResult(VolumeLoadResult(response_id=req.request_id, viewport_id=req.viewport_id,
        series_uid=req.series_uid, volume=_volume(100*z+10*y+x)))
    wait_until(lambda: tab.referencesReady)
    yield tab
    tab.dispose()
    wait_until(lambda: not tab.busy)


def draw(tab, points=((5, 10), (15, 10), (25, 20))):
    view = tab.viewForRole("reference-a")
    tab.startPath()
    for col, row in points:
        assert view.cprTap(col, row, .4)
    assert tab.finishPath()
    wait_until(lambda: tab.ready)
    return view


def test_confirmed_path_requires_explicit_editing(cpr):
    view = draw(cpr)
    original = cpr.current_path
    assert not cpr.pathEditing
    assert not view.cprTap(10, 10, .4)
    assert not view.cprBeginDrag(15, 10, .4)
    assert cpr.current_path == original
    cpr.setPathEditing(True)
    assert view.cprTap(10, 10, .4)
    assert len(cpr.current_path.control_points) == 4
    cpr.setPathEditing(False)
    modified = cpr.current_path
    assert not view.cprTap(12, 10, .4)
    assert cpr.current_path == modified


def test_double_click_has_one_owner_for_drawing_editing_and_curve_measurements(cpr):
    ref = cpr.viewForRole("reference-a")
    cpr.startPath()
    ref.cprTap(5, 10, .4)
    assert ref.cprDoubleClick()  # An incomplete draft still owns the gesture.
    assert cpr.drawing and not cpr.focusedViewportId
    ref.cprTap(15, 10, .4)
    assert ref.cprDoubleClick()
    wait_until(lambda: cpr.ready)
    assert not cpr.drawing and not cpr.focusedViewportId
    cpr.setPathEditing(True)
    assert ref.cprDoubleClick()
    assert cpr.pathEditing and not cpr.focusedViewportId
    cpr.setPathEditing(False)
    for kind in ("curve", "freehand"):
        cpr.toolController.selectInteraction("measure:" + kind)
        assert not ref.cprDoubleClick()  # Allow the shared measurement finisher.
        assert not cpr.focusedViewportId


def test_finish_and_delete_belong_to_reference_path_input(cpr):
    ref, cross = cpr.viewForRole('reference-a'), cpr.viewForRole('cross')
    cpr.startPath()
    assert not cpr.canFinishPath
    ref.cprTap(5, 10, .4)
    assert not cpr.canFinishPath
    assert cpr.canDeletePoint
    ref.cprTap(15, 10, .4)
    assert cpr.canFinishPath
    assert not cross.cprFinish()
    assert not cross.cprDelete()
    assert len(cpr.controlPoints) == 2
    assert ref.cprFinish()
    assert not cpr.canFinishPath
    cpr.setPathEditing(True)
    cpr.locatePoint(1)
    assert not cpr.canDeletePoint  # A committed path must retain two points.


def test_leaving_edit_mode_cancels_an_uncommitted_drag(cpr):
    view = draw(cpr)
    original = cpr.current_path
    cpr.setPathEditing(True)
    view.cprBeginDrag(15, 10, .4)
    view.cprMoveDrag(17, 12)
    cpr.setPathEditing(False)
    assert cpr.current_path == original
    assert not cpr._edit_transaction_active
    cpr.setPathEditing(True)
    cpr._tool_controller.activateTool('window')
    cpr._tool_controller.activateTool('cpr-path')
    assert not cpr.pathEditing


def test_other_tools_cannot_confirm_or_delete_a_suspended_draft(cpr):
    ref = cpr.viewForRole('reference-a')
    cpr.startPath()
    ref.cprTap(5, 10, .4)
    ref.cprTap(15, 10, .4)
    cpr._tool_controller.activateTool('measure')
    assert not ref.cprFinish()
    assert not ref.cprDelete()
    assert cpr.drawing and len(cpr.controlPoints) == 2
    cpr._tool_controller.activateTool('cpr-path')
    assert ref.cprFinish()
    assert not cpr.drawing


def test_clicking_near_last_draft_point_ignores_jitter_but_allows_a_new_slice(cpr):
    ref = cpr.viewForRole('reference-a')
    cpr.startPath()
    ref.cprTap(5, 10, .4)
    ref.cprTap(5.1, 10.1, .4)
    assert len(cpr.controlPoints) == 1
    ref.setSliceIndex(24)
    wait_until(lambda: ref._frame_meta.slice_index == 24)
    ref.cprTap(5.1, 10.1, .4)
    assert len(cpr.controlPoints) == 2
    assert cpr.finishPath()


def test_create_multiplane_path_and_curve_position_sync(cpr):
    view = cpr.viewForRole("reference-a")
    cpr.startPath()
    view.cprTap(5, 10, .4)
    view.setSliceIndex(24)
    wait_until(lambda: view._frame_meta.slice_index == 24)
    view.cprTap(15, 10, .4)
    view.cprTap(25, 20, .4)
    assert cpr.finishPath()
    wait_until(lambda: cpr.ready)
    points = cpr.current_path.control_points
    assert points[0][2] == 20 and points[1][2] == 24
    cpr.setPositionMm(8)
    wait_until(lambda: cpr.ready)
    assert abs(cpr._result.section.distance_mm-8) <= .5
    section_center = cpr._result.section.geometry.frame.center_patient
    assert cpr.viewForRole("reference-a").plane_geometry.frame.center_patient[2] == pytest.approx(section_center[2])


def test_overlay_distinguishes_source_thickness_from_displayed_cpr_slab(cpr):
    cpr._volume.representative_instance_meta = replace(cpr._volume.representative_instance_meta, slice_thickness=1.)
    draw(cpr)
    curved = cpr.viewForRole('curved')
    assert curved.overlayInfo['cprReconstruction'] == 'CPR · Thin'
    cpr.setParameter('thickness', 12.)
    cpr.setParameter('projection', 'mean')
    # Keep the metadata tied to the image still on screen during reconstruction.
    assert curved.overlayInfo['cprReconstruction'] == 'CPR · Thin'
    wait_until(lambda: cpr.ready)
    assert curved.overlayInfo['cprReconstruction'] == 'CPR · Mean 12 mm'
    assert curved.overlayInfo['sliceThickness'] == '1'
    assert curved.overlayInfo['cprRole'] == 'curved'
    cross = cpr.viewForRole('cross').overlayInfo
    assert cross['cprRole'] == 'cross'
    assert cross['cprReconstruction'] == ''  # Cross section stays a thin plane.
    cpr.setParameter('projection', 'mip')
    wait_until(lambda: cpr.ready)
    assert curved.overlayInfo['cprReconstruction'] == 'CPR · MIP 12 mm'
    cpr.setParameter('thickness', 0.)
    wait_until(lambda: cpr.ready)
    assert curved.overlayInfo['cprReconstruction'] == 'CPR · Thin'


def test_reference_drag_preserves_original_depth_and_cancel_restores(cpr):
    view = draw(cpr)
    cpr.setPathEditing(True)
    old = cpr.current_path
    view.setSliceIndex(24)
    wait_until(lambda: view._frame_meta.slice_index == 24)
    assert view.cprBeginDrag(15, 10, .4)
    assert view.cprMoveDrag(17, 12)
    assert cpr.current_path.control_points[1] == pytest.approx((17, 12, 20))
    view.cprCancel()
    wait_until(lambda: cpr.ready)
    assert cpr.current_path == old
    assert not cpr._edit_transaction_active


def test_insert_delete_and_multiple_paths_preserve_identity(cpr):
    view = draw(cpr)
    cpr.setPathEditing(True)
    first = cpr.selectedPathId
    assert view.cprTap(10, 10, .4)
    assert len(cpr.current_path.control_points) == 4
    cpr.deleteSelectedPoint()
    assert len(cpr.current_path.control_points) == 3
    draw(cpr, ((5, 25), (15, 25), (25, 30)))
    second = cpr.selectedPathId
    assert second != first and len(cpr.paths) == 2
    cpr.renamePath("Second artery")
    cpr.selectPath(first)
    assert cpr.current_path.control_points[0][:2] == (5, 10)
    cpr.deletePath()
    assert cpr.selectedPathId == second
    assert cpr.current_path.name == "Second artery"


def test_invalid_draft_stays_editable_and_escape_cancels(cpr):
    view = cpr.viewForRole("reference-a")
    cpr.startPath()
    view.cprTap(5, 10, .4)
    assert not cpr.finishPath()
    assert cpr.drawing and cpr.message
    view.cprCancel()
    assert not cpr.drawing and not cpr.paths


def test_window_updates_all_cached_views_without_reconstruction_and_curve_rejects_measurement(cpr):
    view = draw(cpr)
    generation = cpr._generation
    curve = cpr.viewForRole("curved")
    view.apply_window_level(WindowLevelChange(WindowLevel(120, 200), False))
    assert all(v.windowCenter == 120 for v in cpr.viewports_by_id.values())
    assert cpr._generation == generation
    assert curve._measurement_context(1, 1) is None
    assert curve._frame_meta.geometry.image_position_patient is None
    assert cpr.viewForRole("cross").plane_geometry is not None


def test_completed_drag_is_one_undo_transaction_and_whole_path_deletion_is_undoable(cpr):
    from qt_dicom_viewer.ui.controller.edit_history_controller import EditHistoryController
    cpr._edit_history = history = EditHistoryController(cpr)
    view = draw(cpr)
    cpr.setPathEditing(True)
    history.capture()
    original = cpr.current_path
    before = len(history._undo)
    view.cprBeginDrag(15, 10, .4)
    for col in (16, 17, 18):
        view.cprMoveDrag(col, 12)
        history.capture()
    assert len(history._undo) == before
    view.cprEndDrag(18, 12)
    history.capture()
    assert len(history._undo) == before + 1
    changed = cpr.current_path
    history.undo()
    assert cpr.current_path == original
    history.redo()
    assert cpr.current_path == changed
    cpr.deletePath()
    history.capture()
    assert not cpr.paths
    history.undo()
    assert cpr.current_path == changed


def test_plane_switch_keeps_draft_and_parameter_validation_is_atomic(cpr):
    cpr.startPath()
    cpr.viewForRole("reference-a").cprTap(5, 10, .4)
    cpr.setReferencePlane(0, "sagittal")
    wait_until(lambda: not cpr.busy)
    assert cpr.drawing and len(cpr.controlPoints) == 1
    cpr.cancel_operation()
    draw(cpr)
    before = cpr.current_settings
    cpr.setParameter("step", 0)
    assert cpr.current_settings == before
    cpr.setParameter("angle", 30)
    wait_until(lambda: cpr.ready)
    assert cpr.parameters["angle"] == pytest.approx(30)


def test_mpr_command_opens_one_cpr_tab_using_shared_volume_owner(qt_app, tmp_path):
    from test_workspace_persistence import populated_app
    app, series = populated_app(tmp_path)
    app.workspaceDocumentController._autosave.stop()
    workspace = app.workspaceController
    try:
        workspace.createTab(series.series_instance_uid, "MPR", "mpr")
        mpr = workspace.activeTab
        wait_until(lambda: workspace.activeLoadState.status == "ready")
        mpr.toolController.activateTool("open-cpr")
        tab = workspace.activeTab
        assert tab.tab_config.tab_type == TabType.CPR
        wait_until(lambda: tab.referencesReady)
        assert workspace.activeLoadState.status == "ready"
        workspace.activateTabId(mpr.tab_config.tab_id)
        mpr.toolController.activateTool("open-cpr")
        assert workspace.activeTab is tab
        assert len(tab.viewports_by_id) == 4
    finally:
        app.shutdown()


def test_cpr_toolbar_preferences_target_the_cpr_profile(qt_app, tmp_path):
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    settings = SettingsController(path=tmp_path / "settings.json")
    editor = settings.createToolbarEditor(settings)
    editor.selectProfile("cpr:ct")
    assert editor.selectedProfile == "cpr:ct"
    assert editor.moveTool("common", 0, 1)
    assert editor.save()
    assert list(settings.section("toolbar")["rightProfiles"]) == ["cpr:ct"]
