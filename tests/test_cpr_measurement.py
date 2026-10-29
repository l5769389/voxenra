import numpy as np

from test_cpr_persistence import cpr_app, qt_app
from test_dicom_tags import wait_until
from test_workspace_persistence import draw_length


def test_old_cross_section_measurement_returns_to_exact_plane_after_path_edit(cpr_app):
    app, tab, _ = cpr_app
    cross = tab.viewForRole('cross')
    original = cross.plane_geometry
    measurement = draw_length(cross)
    source = cross._measure_controller._sources[measurement]
    assert source['cpr']['pathRevision'] == 1
    reference = tab.viewForRole('reference-a')
    reference.cprBeginDrag(20, 35, 1)
    reference.cprEndDrag(25, 30)
    wait_until(lambda: tab.ready)
    assert cross.plane_geometry != original
    tab.navigate_measurement(cross, source)
    wait_until(lambda: not cross.render_pending)
    np.testing.assert_allclose(cross.plane_geometry.image_origin_patient, original.image_origin_patient)
    np.testing.assert_allclose(cross.plane_geometry.image_orientation_patient, original.image_orientation_patient)
    assert cross.historicalPlane
    assert any(item['measurementId'] == measurement for item in cross.measurementController.measurementItems)
    assert cross._measure_controller.current_source['cpr']['pathRevision'] == 1
    tab.setPositionMm(5)
    wait_until(lambda: tab.ready)
    assert not cross.historicalPlane


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
