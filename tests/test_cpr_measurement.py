import numpy as np
import pytest

from test_cpr_persistence import cpr_app, qt_app
from test_dicom_tags import wait_until
from test_workspace_persistence import draw_length


def test_curved_annotation_click_is_not_consumed_by_position_link(cpr_app):
    _, tab, _ = cpr_app
    view = tab.viewForRole('curved')
    tab.activateViewport(view.viewportId)
    tab.toolController.selectInteraction('annotate:text')
    text = view.textAnnotationController
    text.addAnnotation(2., 2., 8., 8.)
    original = text.selectedAnnotationId
    text.clearSelection()
    assert not view.cprTap(5., 5., 3.)
    view.selectMeasurementAt(True, 5., 5., 3., 3.)
    assert text.selectedAnnotationId == original


def test_curved_annotations_follow_path_geometry_and_settings_not_position(cpr_app):
    from test_cpr_controller import draw
    _, tab, _ = cpr_app
    view = tab.viewForRole('curved')
    text = view.textAnnotationController
    text.addAnnotation(2., 2., 8., 8.)
    original = text.selectedAnnotationId
    first = tab.selectedPathId
    tab.setPositionMm(8)
    wait_until(lambda: tab.ready)
    assert [a['annotationId'] for a in text.annotationItems] == [original]
    draw(tab, ((20, 65), (45, 70), (65, 85)))
    assert not text.annotationItems
    tab.selectPath(first)
    wait_until(lambda: tab.ready)
    assert [a['annotationId'] for a in text.annotationItems] == [original]
    tab.setParameter('angle', 35)
    wait_until(lambda: tab.ready)
    assert not text.annotationItems


def test_old_cross_section_measurement_returns_to_exact_plane_after_path_edit(cpr_app):
    app, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    original = cross.plane_geometry
    measurement = draw_length(cross)
    source = cross._measure_controller._sources[measurement]
    assert source['cpr']['pathRevision'] == 1
    reference = tab.viewForRole('reference-a')
    tab.setPathEditing(True)
    reference.cprBeginDrag(20, 35, 1)
    reference.cprEndDrag(25, 30)
    wait_until(lambda: tab.ready)
    assert cross.plane_geometry != original
    tab.navigate_measurement(cross, source)
    wait_until(lambda: not cross.render_pending)
    np.testing.assert_allclose(cross.plane_geometry.image_origin_patient, original.image_origin_patient)
    np.testing.assert_allclose(cross.plane_geometry.image_orientation_patient, original.image_orientation_patient)
    assert cross.historicalPlane
    assert cross.overlayInfo['cprDistance'] == f"s: {source['cpr']['distanceMm']:.1f} mm"
    assert any(item['measurementId'] == measurement for item in cross.measurementController.measurementItems)
    assert cross._measure_controller.current_source['cpr']['pathRevision'] == 1
    historical_distance = cross.overlayInfo['cprDistance']
    tab.setPositionMm(5)
    assert cross.historicalPlane
    assert cross.overlayInfo['cprDistance'] == historical_distance
    wait_until(lambda: tab.ready)
    assert not cross.historicalPlane
    assert '/' in cross.overlayInfo['cprDistance']


def test_position_link_uses_current_path_during_pending_path_switch(cpr_app):
    _, tab, _ = cpr_app
    from test_cpr_controller import draw
    first = tab.selectedPathId
    draw(tab, ((20, 65), (45, 70), (65, 75)))
    tab.selectPath(first)
    tab.setPositionMm(5)
    wait_until(lambda: tab.ready)
    expected = tab._result.section.geometry.frame.center_patient
    reference = tab.viewForRole('reference-b').plane_geometry
    np.testing.assert_allclose(reference.frame.center_patient[1], expected[1])


def test_cpr_measurement_reference_renders_with_its_captured_plane(cpr_app):
    from threading import Event
    from qt_dicom_viewer.ui.report_reference_images import render_references
    from qt_dicom_viewer.ui.measurement_source import display_parameters
    app, tab, _ = cpr_app
    view = tab.viewForRole('cross')
    mid = draw_length(view)
    measure = view.measurementController
    picture = dict(source=measure._sources[mid], frame=measure.frame_for(mid),
                   display=display_parameters(view), caption='CPR section', measurements=[])
    images, warnings = render_references([picture], app._series_catalog, Event(), lambda *args: None)
    assert len(images) == 1 and not warnings


def test_historical_plane_survives_workspace_restore(cpr_app, tmp_path):
    from test_cpr_persistence import save
    app, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    mid = draw_length(cross)
    source = cross._measure_controller._sources[mid]
    expected = cross.plane_geometry.image_origin_patient
    reference = tab.viewForRole('reference-a')
    tab.setPathEditing(True)
    reference.cprBeginDrag(20,35,1)
    reference.cprEndDrag(25,30)
    wait_until(lambda: tab.ready)
    tab.navigate_measurement(cross, source)
    wait_until(lambda: cross.historicalPlane)
    path = tmp_path/'historical.voxworkspace'
    save(app, path)
    doc = app.workspaceDocumentController
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy, timeout=10000)
    assert not doc.isError, doc.message
    restored = app.workspaceController.activeTab.viewForRole('cross')
    wait_until(lambda: restored.historicalPlane)
    np.testing.assert_allclose(restored.plane_geometry.image_origin_patient, expected)
    assert restored.measurementController.frame_for(mid) == restored.measurementController.frame_key


def test_deleting_last_path_hides_annotations_and_undo_restores_them(cpr_app):
    _, tab, _ = cpr_app
    view = tab.viewForRole('curved')
    text = view.textAnnotationController
    text.addAnnotation(2., 2., 8., 8.)
    original = text.selectedAnnotationId
    tab._edit_history.capture()
    assert text.annotationItems
    tab.deletePath()
    wait_until(lambda: not tab.busy)
    assert not text.annotationItems
    assert not text.selectedAnnotationId
    tab._edit_history.undo()
    wait_until(lambda: tab.ready)
    assert [a['annotationId'] for a in text.annotationItems] == [original]


@pytest.mark.parametrize('count', [4097, 4098])
def test_large_reference_navigation_count_can_be_saved(qt_app, count):
    from qt_dicom_viewer.ui.controller.tab.cpr_tab_controller import CprTabController
    from qt_dicom_viewer.model import TabConfig, TabType
    from qt_dicom_viewer.model.render_models import VolumeLoadResult
    from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot
    from qt_dicom_viewer.core.workspace_document import _validate_tab
    from test_viewport_controller_hierarchy import _series_meta
    from test_mpr_reslicer import _volume
    tab = CprTabController(TabConfig('cpr', 'CPR', TabType.CPR, (_series_meta(),)))
    requests = []
    tab.renderRequested.connect(requests.append)
    try:
        tab.init_render()
        req = requests[-1]
        tab.handleRenderResult(VolumeLoadResult(response_id=req.request_id, viewport_id=req.viewport_id,
            series_uid=req.series_uid, volume=_volume(np.zeros((count, 3, 11), np.float32), slice_spacing=.25)))
        wait_until(lambda: tab.referencesReady)
        view = tab.viewForRole('reference-a')
        mid = draw_length(view)
        assert view.measurementController._sources[mid]['cpr']['frameCount'] == count
        assert view.measurementController._measurements[mid].length_mm == 10
        _validate_tab(tab_snapshot(tab))
    finally:
        tab.dispose()
        wait_until(lambda: not tab.busy)


@pytest.mark.parametrize('target', ['plane', 'measurement'])
def test_corrupted_historical_fingerprint_rejected_before_workspace_replacement(cpr_app, tmp_path, target):
    from copy import deepcopy
    from test_cpr_persistence import save
    from qt_dicom_viewer.core.workspace_document import validate_document
    from qt_dicom_viewer.core.workspace_state import dumps
    app, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    mid = draw_length(cross)
    source = cross.measurementController._sources[mid]
    tab.setPositionMm(8)
    wait_until(lambda: tab.ready)
    tab.navigate_measurement(cross, source)
    wait_until(lambda: cross.historicalPlane)
    path = tmp_path/'historical.voxworkspace'
    document = save(app, path)
    corrupted = deepcopy(document)
    record = next(t for t in corrupted['tabs'] if t['type'] == 'cpr')
    if target == 'plane':
        source = next(v['independentSource'] for v in record['views'].values() if v.get('independentSource'))
    else:
        source = next(v['sources'][mid] for v in record['edits']['views'].values() if mid in v.get('sources', {}))
    source['cpr']['fingerprint'] = '0'*64
    with pytest.raises(ValueError):
        validate_document(corrupted)
    path.write_bytes(dumps(corrupted))
    doc = app.workspaceDocumentController
    doc.restore_from(path)
    wait_until(lambda: not doc.busy)
    assert doc.isError
    assert app.workspaceController.activeTab is tab
    assert cross.historicalPlane
    assert mid in cross.measurementController._measurements


def test_historical_restore_identity_failure_marks_loading_error(cpr_app):
    from copy import deepcopy
    app, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    mid = draw_length(cross)
    source = deepcopy(cross.measurementController._sources[mid])
    source['cpr']['fingerprint'] = '0'*64
    tab._pending_restore_planes = {cross.viewportId: source}
    loading = app.workspaceController._load_states[tab.tab_config.tab_id]
    loading.restart()
    tab._accept_cpr(tab._result)
    assert tab.hasError
    assert loading.status == 'error'
    assert mid in cross.measurementController._measurements


@pytest.mark.parametrize('role, count, index', [('cross', 4098, 0), ('reference-a', 0, 0),
                                              ('reference-b', 4098, 4098)])
def test_cpr_source_rejects_invalid_navigation_provenance(cpr_app, role, count, index):
    from copy import deepcopy
    from qt_dicom_viewer.ui.measurement_source import validate_cpr_source
    _, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    mid = draw_length(cross)
    source = deepcopy(cross.measurementController._sources[mid])
    source['cpr'].update(role=role, frameCount=count, frameIndex=index)
    with pytest.raises(ValueError):
        validate_cpr_source(source)
