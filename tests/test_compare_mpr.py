"""Independent MPR pairs, explicit gesture linking, UI and portable recovery."""
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_compare_2d import comparison
from test_series_sidebar import sidebar_scene, right_click
from test_tag_qml import find, click, descendants
from test_workspace_persistence import draw_length
from qt_dicom_viewer.core.compare import supports_mpr_compare
from qt_dicom_viewer.core.workspace_document import read_document
from qt_dicom_viewer.model import MprPlane, WindowLevel, WindowLevelChange


def open_pair(app, records):
    ws = app.workspaceController
    ws.createMprCompareTab(*(r.series_instance_uid for r in records[:2]))
    wait_until(lambda: ws.activeLoadState.status in ('ready', 'error'))
    assert ws.activeLoadState.status == 'ready', ws.activeLoadState.message
    tab = ws.activeTab
    wait_until(lambda: not tab._active_mpr_requests)
    return tab


def test_six_views_eligibility_and_default_independence(comparison):
    app, records = comparison
    assert supports_mpr_compare(records[0])
    assert not supports_mpr_compare(records[2])
    assert not supports_mpr_compare(replace(records[0], instances=tuple(
        replace(i, photometric_interpretation='RGB') for i in records[0].instances)))
    assert not supports_mpr_compare(replace(records[0], instances=tuple(
        replace(i, image_orientation_patient=None) for i in records[0].instances)))
    tab = open_pair(app, records)
    assert len(tab.viewports_by_id) == 6
    assert len({id(v._measure_controller) for v in tab.viewports_by_id.values()}) == 6
    assert all(v.workspaceTab is tab for v in tab.viewports_by_id.values())
    assert not tab.positionLinked and not tab.rotationLinked
    a, b = tab.groups
    original_b = b._target_mpr_state
    center = np.asarray(a._target_mpr_state.frame.center_patient) + [1, 2, 0]
    a._handle_crosshair_center_change_requested(tuple(center))
    a._handle_crosshair_rotation_requested(MprPlane.AXIAL, .2)
    wait_until(lambda: not tab._active_mpr_requests)
    assert b._target_mpr_state == original_b
    av, bv = a.activeViewport, b.activeViewport
    assert {v.viewportRole for v in a.viewports_by_id.values()} == {'a'}
    assert {v.viewportRole for v in b.viewports_by_id.values()} == {'b'}
    before = bv._state.window
    av.apply_window_level(WindowLevelChange(WindowLevel(800, 50), False))
    wait_until(lambda: not tab._active_mpr_requests)
    assert all(v._state.window == WindowLevel(800, 50) for v in a.viewports_by_id.values())
    assert bv._state.window == before
    app.workspaceController.createMprCompareTab(*(r.series_instance_uid for r in reversed(records[:2])))
    assert app.workspaceController.activeTab is tab and len(app.workspaceController.tabs) == 1


def test_explicit_position_rotation_links_keep_initial_offsets_and_can_disable(comparison):
    app, records = comparison
    tab = open_pair(app, records)
    a, b = tab.groups
    b._handle_crosshair_center_change_requested(tuple(np.asarray(b._target_mpr_state.frame.center_patient) + [2, 0, 0]))
    original = [g._target_mpr_state for g in tab.groups]
    av, bv = a.activeViewport, b.activeViewport
    av.applyTransformAction('rotate:cw90')
    assert av.rotationDegrees == 90 and bv.rotationDegrees == 0
    tab.setLink('position', True)
    tab.setLink('rotation', True)
    assert av.rotationDegrees == 90 and bv.rotationDegrees == 0
    av.applyTransformAction('rotate:cw90')
    assert av.rotationDegrees == 180 and bv.rotationDegrees == 90
    bv.applyTransformAction('rotate:ccw90')
    assert av.rotationDegrees == 90 and bv.rotationDegrees == 0
    assert [g._target_mpr_state for g in tab.groups] == original
    a._handle_crosshair_center_change_requested(tuple(np.asarray(original[0].frame.center_patient) + [0, 1, 0]))
    np.testing.assert_allclose(b._target_mpr_state.frame.center_patient,
                               np.asarray(original[1].frame.center_patient) + [0, 1, 0])
    for _ in range(12):
        a._handle_crosshair_rotation_requested(MprPlane.AXIAL, .02)
    a._handle_mpr_3d_rotation_requested((1., 0., 0.), .15)
    wait_until(lambda: not tab._active_mpr_requests)
    np.testing.assert_allclose(a._target_mpr_state.frame.mpr_to_patient[:3,:3], b._target_mpr_state.frame.mpr_to_patient[:3,:3])
    assert a._target_mpr_state.view_rolls.axial_radians == pytest.approx(b._target_mpr_state.view_rolls.axial_radians)
    # Each volume keeps its own sampling grid and mm spacing.
    assert a._target_mpr_state.view_grids == original[0].view_grids
    assert b._target_mpr_state.view_grids == original[1].view_grids
    tab.setLink('position', False)
    tab.setLink('rotation', False)
    untouched = a._target_mpr_state
    b._handle_mpr_3d_rotation_requested((0., 1., 0.), .1)
    assert a._target_mpr_state == untouched
    bv.applyTransformAction('rotate:cw90')
    assert av.rotationDegrees == 90 and bv.rotationDegrees == 90
    tab.activateViewport(b.activeViewport.viewportId)
    tab.resetActiveOrientation()
    wait_until(lambda: not tab._active_mpr_requests)
    np.testing.assert_allclose(b._target_mpr_state.frame.mpr_to_patient[:3,:3], np.eye(3))
    assert a._target_mpr_state == untouched


def test_independent_measurements_history_and_workspace_roundtrip(comparison, tmp_path):
    app, records = comparison
    tab = open_pair(app, records)
    a, b = tab.groups
    av, bv = a.activeViewport, b.activeViewport
    first = draw_length(av); tab.historyController.capture()
    second = draw_length(bv); tab.historyController.capture()
    tab.historyController.undo()
    assert first in av._measure_controller._measurements and not bv._measure_controller._measurements
    tab.historyController.redo()
    assert second in bv._measure_controller._measurements
    from qt_dicom_viewer.ui.controller.measurement_report_controller import capture_results
    rows, _, _ = capture_results(app.workspaceController, app._series_catalog, anonymous=False)
    assert len(rows) == 2
    assert {row['series'] for row in rows} == {r.series_description for r in records[:2]}
    a._handle_crosshair_rotation_requested(MprPlane.AXIAL, .17)
    wait_until(lambda: not tab._active_mpr_requests)
    tab.activateViewport(bv.viewportId)
    tab.setPairPlane('coronal')
    a.toolController.activateTool('pan'); b.toolController.activateTool('zoom')
    tab.setLink('position', True)
    original = [g._target_mpr_state for g in tab.groups]
    manager = app.workspaceDocumentController
    target = tmp_path / 'mpr-compare.voxworkspace'
    assert manager.save_to(target)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    saved = read_document(target)
    assert saved['tabs'][0]['type'] == 'comparempr'
    assert manager.restore_from(target)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    restored = app.workspaceController.activeTab
    assert restored is not tab
    assert restored.pairPlane == 'coronal' and restored.activeViewport.viewportRole == 'b'
    assert restored.positionLinked and not restored.rotationLinked
    assert [g._target_mpr_state for g in restored.groups] == original
    assert [g.toolController.activeTool for g in restored.groups] == ['pan', 'zoom']
    counts = [len(v._measure_controller._measurements) for v in restored.viewports_by_id.values()]
    assert sum(counts) == 2 and sorted(counts) == [0,0,0,0,1,1]
    assert restored.activeToolController is restored.groups[1].toolController


@pytest.mark.parametrize('theme, locale', [('dark', 'zh-CN'), ('light', 'en-US')])
def test_picker_six_cells_pair_zoom_and_active_tools(sidebar_scene, tmp_path, theme, locale):
    window, app, records, warnings = sidebar_scene
    window.resize(1400, 900)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    panel = app.panelController
    panel.selectSeries(records[0].series_instance_uid)
    right_click(window, find(window, 'series-' + records[0].series_instance_uid))
    action = find(window, 'seriesContextAction-comparempr')
    assert action.isEnabled()
    click(window, action)
    assert panel.compareController.mode == 'mpr'
    click(window, find(window, 'compareCandidate-' + records[1].series_instance_uid))
    click(window, find(window, 'confirmCompare'))
    ws = app.workspaceController
    wait_until(lambda: ws.activeLoadState.status in ('ready','error'))
    assert ws.activeLoadState.status == 'ready', ws.activeLoadState.message
    tab = ws.activeTab
    assert find(window, 'tabType-' + tab.tab_config.tab_id).property('text') == 'MPR Compare'
    def cells():
        return [i for i in descendants(window.contentItem()) if i.objectName().startswith('compareMprCell-') and i.isVisible()]
    wait_until(lambda: len(cells()) == 6)
    wait_until(lambda: len({round(i.mapToScene(QPointF()).y()) for i in cells()}) == 2)
    wait_until(lambda: len({round(i.mapToScene(QPointF()).x()) for i in cells()}) == 3)
    headings = [find(window, 'compareMprHeading-' + role) for role in ('a', 'b')]
    assert all(h.width() > cells()[0].width() * 2 for h in headings)
    assert len({round(c.height()) for c in cells()}) == 1
    assert not any(i.objectName() == 'sliceControl' for c in cells() for i in descendants(c))
    a, b = tab.groups
    click(window, find(window, 'imageViewport-' + b.activeViewport.viewportId))
    assert tab.activeToolController is b.toolController
    click(window, find(window, 'primaryTool-pan'))
    assert b.toolController.activeTool == 'pan' and a.toolController.activeTool != 'pan'
    click(window, find(window, 'primaryTool-mpr-layout'))
    assert not find(window, 'compareMprLink-position').property('checked')
    click(window, find(window, 'compareMprLink-position'))
    assert tab.positionLinked
    click(window, find(window, 'compareMprLayout-coronal'))
    assert len(cells()) == 2 and tab.pairPlane == 'coronal'
    assert all(i.property('modelData').viewportType == 'coronal' for i in cells())
    assert all(abs(h.width() + 6 - c.width()) < 1 for h, c in zip(headings, cells()))
    assert round(headings[0].mapToScene(QPointF()).y()) == round(headings[1].mapToScene(QPointF()).y())
    assert window.grabWindow().save(str(tmp_path / ('mpr-compare-pair-' + theme + '.png')))
    tab.setPairPlane('')
    QTest.qWait(60)
    canvas = find(window, 'imageViewport-' + b.activeViewport.viewportId)
    point = canvas.mapToScene(QPointF(canvas.width()*.7, canvas.height()*.7)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
    wait_until(lambda: len(cells()) == 2)
    click(window, find(window, 'compareMprLayout-six'))
    assert len(cells()) == 6
    assert window.grabWindow().save(str(tmp_path / ('mpr-compare-' + theme + '.png')))
    assert not warnings, warnings


def test_detach_rejoin_and_close_during_linked_render(sidebar_scene):
    from test_tab_windows import detached
    window, app, records, warnings = sidebar_scene
    tab = open_pair(app, records)
    a, b = tab.groups
    tab.setPairPlane('sagittal')
    tab.activateViewport(next(v.viewportId for v in b.viewports_by_id.values() if v.viewportType == 'sagittal'))
    tab.setLink('rotation', True)
    history = tab.historyController
    session, other = detached(app, tab)
    wait_until(lambda: find(other, 'imageViewport-' + tab.activeViewport.viewportId).isVisible())
    assert session.activeTab is tab and tab.activeToolController is b.toolController
    click(other, find(other, 'primaryTool-pan'))
    assert b.toolController.activeTool == 'pan' and a.toolController.activeTool != 'pan'
    app.windowManager.moveToMain(tab.tab_config.tab_id)
    wait_until(lambda: session.windowId not in app.windowManager.sessions)
    assert app.windowManager.mainWorkspace.activeTab is tab
    assert tab.historyController is history and tab.pairPlane == 'sagittal' and tab.rotationLinked
    a._handle_crosshair_rotation_requested(MprPlane.SAGITTAL, .12)
    app.windowManager.mainWorkspace.closeTab(tab.tab_config.tab_id)
    QTest.qWait(100)
    assert tab.tab_config.tab_id not in app.workspaceController._tab_dict
    assert not tab._active_mpr_requests
    assert all(not g._active_mpr_requests for g in tab.groups)
    assert not warnings, warnings


def test_workspace_rejects_malformed_mpr_groups(comparison):
    from copy import deepcopy
    from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot
    from qt_dicom_viewer.core.workspace_document import _validate_tab
    app, records = comparison
    saved = tab_snapshot(open_pair(app, records))
    _validate_tab(saved)
    for field, value in [('pairPlane', '3d'), ('rotationLinked', 'true'), ('groups', [])]:
        malformed = deepcopy(saved)
        malformed['mprCompare'][field] = value
        with pytest.raises(ValueError):
            _validate_tab(malformed)
    for key, value in [('type', 'comparempr'), ('series', saved['series']), ('mprCompare', {})]:
        malformed = deepcopy(saved)
        malformed['mprCompare']['groups'][0][key] = value
        with pytest.raises(ValueError):
            _validate_tab(malformed)


def test_ct_window_and_physical_zoom_links_preserve_independent_content(comparison, tmp_path):
    app, records = comparison
    tab = open_pair(app, records)
    a, b = tab.groups
    av, bv = a.activeViewport, b.activeViewport
    assert tab.windowLinkAvailable and not tab.linkStates['window'] and not tab.linkStates['zoom']
    bv.apply_window_level(WindowLevelChange(WindowLevel(1200, 300), True))
    wait_until(lambda: not tab._active_mpr_requests)
    original = a._linked_mpr_window.window
    tab.setLink('window', True)
    wait_until(lambda: not tab._active_mpr_requests)
    assert b._linked_mpr_window.window == original and all(v.inverted for v in b.viewports_by_id.values())
    for width in (450, 650, 800):
        bv.apply_window_level(WindowLevelChange(WindowLevel(width, 80), True))
    wait_until(lambda: not tab._active_mpr_requests)
    assert all(v._state.window == WindowLevel(800, 80) for v in tab.viewports_by_id.values())
    assert all(not v.inverted for v in a.viewports_by_id.values())
    tab.setLink('window', False)
    bv.apply_window_level(WindowLevelChange(WindowLevel(700, 60), True))
    wait_until(lambda: not tab._active_mpr_requests)
    assert av._state.window == WindowLevel(800, 80)
    tab.updateViewportFitScale(av.viewportId, .5)
    tab.updateViewportFitScale(bv.viewportId, 1.)
    av.setZoom(2.); bv.setZoom(5.)
    measure_id = draw_length(av)
    tab.setLink('zoom', True)
    assert av.zoom == 2. and bv.zoom == 1.
    bv.setZoom(3.)
    assert av.zoom == 6. and bv.zoom == 3.
    # A layout/resize changes the fitted scale; physical scale stays matched.
    tab.updateViewportFitScale(bv.viewportId, 2.)
    wait_until(lambda: bv.zoom == 1.5)
    assert av.zoom * .5 == bv.zoom * 2.
    assert measure_id in av._measure_controller._measurements and not bv._measure_controller._measurements
    tab.setLink('window', True)
    target = tmp_path / 'display-links.voxworkspace'
    manager = app.workspaceDocumentController
    assert manager.save_to(target)
    wait_until(lambda: not manager.busy)
    assert manager.restore_from(target)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    restored = app.workspaceController.activeTab
    assert restored.linkStates['zoom'] and restored.linkStates['window']
    assert restored._zoom_scales == tab._zoom_scales
    restored.setLink('zoom', False)
    a2, b2 = (g.activeViewport for g in restored.groups)
    before = b2.zoom
    a2.setZoom(4.)
    assert b2.zoom == before


def test_out_of_range_and_recenter_only_affect_the_requested_series(comparison):
    app, records = comparison
    tab = open_pair(app, records)
    a, b = tab.groups
    assert not any(tab.outOfRangeViewports.values())
    tab.setLink('position', True)
    a._handle_crosshair_center_change_requested(tuple(np.asarray(a._target_mpr_state.frame.center_patient) + [2000, 0, 0]))
    wait_until(lambda: not tab._active_mpr_requests)
    assert any(tab.outOfRangeViewports.get(v.viewportId) for v in b.viewports_by_id.values())
    preserved = a._target_mpr_state
    tab.recenterSeries(b.activeViewport.viewportId)
    wait_until(lambda: not tab._active_mpr_requests)
    assert not any(tab.outOfRangeViewports.get(v.viewportId) for v in b.viewports_by_id.values())
    assert a._target_mpr_state == preserved and tab.positionLinked


def test_window_link_is_unavailable_for_mixed_modalities_and_old_workspaces(comparison):
    from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
    from qt_dicom_viewer.core.workspace_document import _validate_tab
    app, records = comparison
    tab = open_pair(app, records)
    original = tab.tab_config
    tab._tab_config = replace(original, series_metas=(original.series_metas[0], replace(original.series_metas[1], modality='PT')))
    assert not tab.windowLinkAvailable
    tab.setLink('window', True)
    assert not tab.linkStates['window']
    tab._tab_config = original
    saved = tab_snapshot(tab)
    for key in ('windowLinked', 'zoomLinked', 'zoomScales'):
        saved['mprCompare'].pop(key)
    _validate_tab(saved)
    apply_tab_snapshot(tab, saved)
    assert not tab.linkStates['window'] and not tab.linkStates['zoom']
    for key, value in [('windowLinked', 'true'), ('zoomLinked', 1), ('zoomScales', {'axial': float('nan')})]:
        saved['mprCompare'][key] = value
        with pytest.raises(ValueError):
            _validate_tab(saved)
        saved['mprCompare'].pop(key)


def test_geometric_coverage_handles_dark_pixels_oblique_planes_and_slabs():
    from qt_dicom_viewer.core.compare_mpr import plane_intersects_volume, matched_zooms
    from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
    from test_mpr_reslicer import _volume
    volume = _volume(np.zeros((5, 10, 12)), origin=(120., -40., 3.))
    reslicer = MprReslicer()
    # Pixel intensity does not enter the coverage calculation.
    plane, _, _ = reslicer.prepare_plane(volume, MprPlane.AXIAL)
    assert plane_intersects_volume(volume.geometry, plane)
    origin = np.asarray(plane.image_origin_mpr)
    normal = np.asarray(plane.navigation_direction_mpr)
    far = replace(plane, image_origin_mpr=tuple(origin + normal * 20))
    assert not plane_intersects_volume(volume.geometry, far)
    assert plane_intersects_volume(volume.geometry, far, slab_thickness_mm=50.)
    # A finite grid can miss the volume even when its infinite plane intersects.
    lateral = replace(plane, image_origin_mpr=tuple(origin + np.asarray(plane.column_direction_mpr) * 100))
    assert not plane_intersects_volume(volume.geometry, lateral)
    from qt_dicom_viewer.core.mpr_rotation import rotate_mpr_state_3d
    from qt_dicom_viewer.model import MprState, MprFrame
    state = MprState(MprFrame.standard_lps(volume.geometry.center_patient))
    state = rotate_mpr_state_3d(state, (1., 1., 0.), .6)
    oblique, _, _ = reslicer.prepare_plane(volume, MprPlane.AXIAL, frame=state.frame)
    assert plane_intersects_volume(volume.geometry, oblique)
    assert matched_zooms(.5, 2., 3.) == (6., 1.5)
    assert matched_zooms(.5, 2., 100.) == (20., 5.)
    assert matched_zooms(.001, 100., 1.) is None


def test_always_visible_link_controls_physical_scale_and_range_recovery(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1400, 900)
    tab = open_pair(app, records)
    a, b = tab.groups
    click(window, find(window, 'toggleRightPanel'))
    assert find(window, 'rightPanel').property('collapsed')
    for key in ('position', 'rotation', 'window', 'zoom'):
        button = find(window, 'compareMprStatus-' + key)
        from qt_dicom_viewer.ui.svg_icon_provider import NAMES
        assert button.property('iconName') in NAMES
        assert not button.property('checked')
        click(window, button)
        assert tab.linkStates[key] and button.property('checked')
    click(window, find(window, 'toggleRightPanel'))
    click(window, find(window, 'primaryTool-mpr-layout'))
    for key in tab.linkStates:
        assert find(window, 'compareMprLink-' + key).property('checked')
    window.resize(1200, 900)
    def scales_match():
        for plane in ('axial', 'coronal', 'sagittal'):
            first, second = [v for v in tab.comparisonViews if v.viewportType == plane]
            af = find(window, 'imageViewport-' + first.viewportId).property('imageFitScale')
            bf = find(window, 'imageViewport-' + second.viewportId).property('imageFitScale')
            if abs(af * first.zoom - bf * second.zoom) > 1e-4:
                return False
        return True
    wait_until(scales_match)
    assert window.grabWindow().save(str(tmp_path/'mpr-compare-link-status.png'))
    a._handle_crosshair_center_change_requested(tuple(np.asarray(a._target_mpr_state.frame.center_patient) + [2000, 0, 0]))
    wait_until(lambda: not tab._active_mpr_requests)
    tab.setPairPlane('sagittal')
    view = next(v for v in b.viewports_by_id.values() if v.viewportType == 'sagittal')
    cell = find(window, 'compareMprCell-' + view.viewportId)
    warning = next(i for i in descendants(cell) if i.objectName() == 'mprOutsideImageRange')
    wait_until(warning.isVisible)
    assert warning.width() <= cell.width() and warning.height() < cell.height()
    assert window.grabWindow().save(str(tmp_path/'mpr-compare-outside.png'))
    original_a = a._target_mpr_state
    button = next(i for i in descendants(cell) if i.objectName() == 'mprReturnToVolume')
    click(window, button)
    wait_until(lambda: not warning.isVisible())
    assert a._target_mpr_state == original_a and tab.positionLinked
    assert not warnings, warnings


def test_comparison_secondary_tools_restore_and_mark_workspace_dirty(comparison, tmp_path):
    app, records = comparison
    tab = open_pair(app, records)
    a, b = tab.groups
    for group, action in ((a, 'measure:curve'), (b, 'measure:ellipse')):
        group.toolController.activateTool('measure')
        group.toolController.selectInteraction(action)
    manager = app.workspaceDocumentController
    path = tmp_path / 'tools.voxworkspace'
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    assert not manager.isError and not manager.dirty
    a.toolController.selectInteraction('measure:angle')
    assert manager.dirty
    assert manager.restore_from(path)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    restored = app.workspaceController.activeTab
    assert [g.toolController.activeInteraction for g in restored.groups] == ['measure:curve', 'measure:ellipse']
    assert not restored.playing and not manager.dirty
