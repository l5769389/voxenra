"""User-visible result navigation, immutable report sources and saved metadata."""
from dataclasses import replace
from threading import Event

from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length
from test_measurement_controller import _position, _drag
from qt_dicom_viewer.core.workspace_state import dumps, loads
from qt_dicom_viewer.model import MeasurementKind
from qt_dicom_viewer.ui.controller.measurement_report_controller import capture_results
from qt_dicom_viewer.ui.report_reference_images import render_references
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot


def test_list_cross_slice_navigation_visibility_lock_and_history(qt_app, tmp_path):
    app, series = populated_app(tmp_path)
    try:
        tab = app.workspaceController.activeTab
        view, listing = tab.activeViewport, tab.measurementResults
        first = draw_length(view)
        tab.historyController.capture()
        key = listing.items[0]['key']
        assert listing.items[0]['location'].endswith('1')
        assert view.measurementController.source(first)['kind'] == 'stack'
        listing.rename(key, 'Reference length')
        listing.setLocked(key, True)
        tab.historyController.capture()
        measure = view.measurementController
        original = measure.committed_measurements
        measure.begin(_position(0, 0), view._measurement_context(3, 2, kind=MeasurementKind.LENGTH))
        measure.update(_drag(_position(0, 0), _position(4, 4)))
        measure.end(_position(4, 4))
        assert measure.committed_measurements == original
        assert not measure.has_active_transaction
        listing.setHidden(key, True)
        assert not measure.measurementItems
        tab.historyController.capture()
        tab.historyController.undo()
        assert measure.measurementItems and measure.presentation(first)['locked']
        view.setSliceIndex(2)
        wait_until(lambda: view._frame_meta.slice_index == 2)
        draw_length(view)
        assert len(listing.items) == 2 and len(measure.measurementItems) == 1
        listing.locate(key)
        wait_until(lambda: view._frame_meta.slice_index == 0 and measure.selectedMeasurementId == first)
        assert listing.message == ''
        saved = loads(dumps(tab_snapshot(tab)))
        listing.remove(key)
        assert len(listing.items) == 1
        apply_tab_snapshot(tab, saved)
        wait_until(lambda: not view.render_pending)
        assert len(listing.items) == 2
        assert measure.presentation(first)['name'] == 'Reference length'
        assert measure.presentation(first)['locked']
    finally:
        app.shutdown()


def test_report_renders_each_source_and_groups_same_slice(qt_app, tmp_path):
    app, series = populated_app(tmp_path)
    try:
        view = app.workspaceController.activeViewport
        mid = draw_length(view)
        view.measurementController.update_presentation(mid, hidden=True, name='Hidden result')
        draw_length(view)
        view.setSliceIndex(2)
        wait_until(lambda: view._frame_meta.slice_index == 2)
        draw_length(view)
        anonymous_rows, _, _ = capture_results(app.workspaceController, app._series_catalog)
        assert all(not row["name"] for row in anonymous_rows)
        rows, pictures, _ = capture_results(app.workspaceController, app._series_catalog, include_images=True, anonymous=False)
        assert len(rows) == 3 and len(pictures) == 2
        assert rows[0]['name'] == 'Hidden result'
        assert len(pictures[0]['measurements']) == 2
        images, warnings = render_references(pictures, app._series_catalog, Event(), lambda _: None)
        assert len(images) == 2 and not warnings
        assert images[0][1] != images[1][1]
        assert view._frame_meta.slice_index == 2
        assert {entry[0] for entry in images[0][2]} == {rows[0]['id'], rows[1]['id']}
        pictures[0]['frame'] = ('wrong-source',)
        images, warnings = render_references(pictures, app._series_catalog, Event(), lambda _: None)
        assert len(images) == 1 and len(warnings) == 1
        assert rows[0]['reference_status']
    finally:
        app.shutdown()


def test_mpr_location_and_reference_leave_other_views_unchanged(qt_app, tmp_path):
    app, series = populated_app(tmp_path)
    try:
        app.workspaceController.createTab(series.series_instance_uid, 'CT', 'mpr')
        tab = app.workspaceController.activeTab
        wait_until(lambda: all(v.loadState == 'ready' for v in tab.viewports_by_id.values()) and not tab._active_mpr_requests)
        view = tab.activeViewport
        first = draw_length(view)
        listing = tab.measurementResults
        key = listing.items[0]['key']
        original_frame = view.measurementController.frame_key
        tab._handle_crosshair_rotation_requested(view.viewport_config.viewport_type, .2)
        wait_until(lambda: not tab._active_mpr_requests)
        peers = {v.viewportId: v.measurementController.frame_key for v in tab.viewports_by_id.values() if v is not view}
        listing.locate(key)
        wait_until(lambda: view.measurementController.selectedMeasurementId == first)
        assert view.measurementController.frame_key == original_frame
        assert peers == {v.viewportId: v.measurementController.frame_key for v in tab.viewports_by_id.values() if v is not view}
        rows, pictures, _ = capture_results(app.workspaceController, app._series_catalog, include_images=True)
        images, errors = render_references(pictures, app._series_catalog, Event(), lambda _: None)
        assert len(images) == 1 and not errors
    finally:
        app.shutdown()


def test_report_cancel_preserves_existing_file_and_frozen_view(qt_app, tmp_path, monkeypatch):
    import qt_dicom_viewer.ui.report_reference_images as references
    entered, release = Event(), Event()
    original = references.render_references
    captured = []
    def blocked(pictures, catalog, cancelled, progress):
        captured.extend(pictures)
        entered.set()
        assert release.wait(5)
        return original(pictures, catalog, cancelled, progress)
    monkeypatch.setattr(references, 'render_references', blocked)
    app, _ = populated_app(tmp_path)
    try:
        view = app.workspaceController.activeViewport
        draw_length(view)
        target = tmp_path/'existing.pdf'
        target.write_bytes(b'previous report')
        report = app.exportController.measurementReport
        assert report.export_to(target, format='pdf', include_images=True)
        wait_until(entered.is_set)
        view.setSliceIndex(2)
        wait_until(lambda: view._frame_meta.slice_index == 2)
        assert captured[0]['source']['parameters']['slice_index'] == 0
        report.cancel()
        release.set()
        wait_until(lambda: not report.busy)
        assert target.read_bytes() == b'previous report'
        assert not report.resultPath
        assert view._frame_meta.slice_index == 2
    finally:
        release.set()
        app.shutdown()


def test_mpr_oblique_slab_references_roundtrip(qt_app, tmp_path):
    from qt_dicom_viewer.model import MprProjectionMode
    app, series = populated_app(tmp_path)
    try:
        app.workspaceController.createTab(series.series_instance_uid, 'CT', 'mpr')
        tab = app.workspaceController.activeTab
        wait_until(lambda: all(v.loadState == 'ready' for v in tab.viewports_by_id.values()) and not tab._active_mpr_requests)
        view = tab.activeViewport
        tab._handle_crosshair_rotation_requested(view.viewport_config.viewport_type, .3)
        wait_until(lambda: not tab._active_mpr_requests)
        view = next(v for v in tab.viewports_by_id.values() if v is not view)
        tab.activateViewport(view.viewportId)
        tab.toolController.setMprProjectionEnabled(True)
        tab.toolController.setMprProjectionMode('mip')
        wait_until(lambda: not tab._active_mpr_requests)
        draw_length(view)
        rows, pictures, _ = capture_results(app.workspaceController, app._series_catalog, include_images=True)
        images, warnings = render_references(pictures, app._series_catalog, Event(), lambda _: None)
        assert len(images) == 1 and not warnings
        saved = loads(dumps(tab_snapshot(tab)))
        assert saved['edits']['views']
        assert view.measurementController.source(view.measurementController.committed_measurements[0].measurement_id)['parameters']['mpr_frame'] is not None
    finally:
        app.shutdown()


def test_four_d_measurement_navigation_and_phase_reference(qt_app, tmp_path):
    from test_four_d import _cross_series_four_d
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    records = _cross_series_four_d(tmp_path)
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws = app.workspaceController
        ws.createTab(records[0].series_instance_uid, '4D', '4d')
        tab = ws.activeTab
        wait_until(lambda: ws._load_states[tab.tab_config.tab_id].status == 'ready' and not tab._active_mpr_requests)
        view = tab.activeViewport
        first = draw_length(view)
        source = view.measurementController.source(first)
        listing = tab.measurementResults
        key = listing.items[0]['key']
        previous_frame = view.measurementController.frame_key
        tab.setPhaseIndex(2)
        wait_until(lambda: tab._current_phase_index == 2 and not tab._active_mpr_requests)
        assert view.measurementController.frame_key != previous_frame, (source, previous_frame, view.measurementController.current_source)
        draw_length(view)
        rows, pictures, _ = capture_results(ws, app._series_catalog, include_images=True)
        assert len(rows) == 2 and len(pictures) == 2
        assert pictures[0]['source']['parameters']['phase_identifier'] != pictures[1]['source']['parameters']['phase_identifier']
        images, errors = render_references(pictures, app._series_catalog, Event(), lambda _: None)
        assert len(images) == 2 and not errors
        peers = {v.viewportId: v.measurementController.frame_key for v in tab.viewports_by_id.values() if v is not view}
        listing.locate(key)
        wait_until(lambda: view.measurementController.selectedMeasurementId == first)
        assert peers == {v.viewportId: v.measurementController.frame_key for v in tab.viewports_by_id.values() if v is not view}
    finally:
        app.shutdown()


def test_enhanced_multiframe_reports_use_distinct_frame_pixels(qt_app, tmp_path):
    from test_enhanced_ct import save_and_scan
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    _, snapshot = save_and_scan(tmp_path)
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws = app.workspaceController
        ws.createTab(snapshot.series[0].series_instance_uid, 'Enhanced CT', '2d')
        wait_until(lambda: ws.activeViewport.loadState == 'ready')
        view = ws.activeViewport
        from qt_dicom_viewer.model import WindowLevel, WindowLevelChange
        view.apply_window_level(WindowLevelChange(WindowLevel(-700, 1000), False))
        wait_until(lambda: not view.render_pending)
        first = draw_length(view)
        frame_index = view._frame_meta.instance_meta.frame_index
        view.setSliceIndex(2)
        wait_until(lambda: view._frame_meta.slice_index == 2)
        assert view._frame_meta.instance_meta.frame_index != frame_index
        draw_length(view)
        rows, pictures, _ = capture_results(ws, app._series_catalog, include_images=True)
        assert len(rows) == 2
        images, errors = render_references(pictures, app._series_catalog, Event(), lambda _: None)
        assert len(images) == 2 and not errors
        assert images[0][1] != images[1][1]
    finally:
        app.shutdown()


def test_independent_2d_plane_location_restores_hidden_mode(qt_app, tmp_path):
    app, _ = populated_app(tmp_path)
    try:
        tab = app.workspaceController.activeTab
        layout = tab.twoDLayout
        layout.setMode(0, 'coronal')
        wait_until(lambda: tab.activeViewport.loadState == 'ready')
        plane = tab.activeViewport
        first = draw_length(plane)
        listing = tab.measurementResults
        key = listing.items[0]['key']
        frame = plane.measurementController.frame_key
        plane.setSliceIndex(plane.sliceIndex + 1)
        wait_until(lambda: not plane.render_pending)
        layout.setMode(0, 'stack')
        stack = tab.activeViewport
        listing.locate(key)
        wait_until(lambda: plane.measurementController.selectedMeasurementId == first)
        assert tab.activeViewport is plane
        assert layout.cells[0]['viewport'] is plane
        assert plane.measurementController.frame_key == frame
        assert not tab._active_mpr_requests
        # A second location while the first one is still queued must win.
        layout.setMode(0, 'stack')
        first_stack = draw_length(stack)
        key0 = next(item['key'] for item in listing.items if item['key'].endswith(first_stack))
        stack.setSliceIndex(2)
        wait_until(lambda: stack._frame_meta.slice_index == 2)
        draw_length(stack)
        last = stack.measurementController.committed_measurements[-1].measurement_id
        key2 = next(item['key'] for item in listing.items if item['key'].endswith(last))
        listing.locate(key0)
        listing.locate(key2)
        wait_until(lambda: not stack.render_pending and stack.measurementController.selectedMeasurementId == last)
        assert stack._frame_meta.slice_index == 2
    finally:
        app.shutdown()


def test_reference_image_preserves_anisotropic_physical_aspect(qt_app):
    from PySide6.QtGui import QImage
    from qt_dicom_viewer.model import PixelSpacing
    from qt_dicom_viewer.ui.controller.measurement_report_controller import report_images
    image = QImage(100, 100, QImage.Format_RGB32)
    image.fill(0)
    result = report_images([('Reference', image, [], PixelSpacing(2, 1))])[0][1]
    assert result.width() / result.height() == .5


def test_locked_copy_has_independent_metadata_and_redo(qt_app, tmp_path):
    from qt_dicom_viewer.model import ImagePoint
    app, _ = populated_app(tmp_path)
    try:
        tab = app.workspaceController.activeTab
        view, listing = tab.activeViewport, tab.measurementResults
        first = draw_length(view)
        tab.historyController.capture()
        key = listing.items[0]['key']
        listing.rename(key, 'Original')
        listing.setLocked(key, True)
        tab.historyController.capture()
        measure = view.measurementController
        copied = measure.paste_points([ImagePoint(3, 3), ImagePoint(13, 3)],
            view._measurement_context(3, 2, kind=MeasurementKind.LENGTH))
        assert copied != first
        assert not measure.presentation(copied)['locked'] and not measure.presentation(copied)['hidden']
        assert measure.presentation(copied)['name'] == ''
        assert measure.source(copied) == measure.current_source
        tab.historyController.capture()
        tab.historyController.undo()
        assert len(listing.items) == 1
        tab.historyController.redo()
        assert len(listing.items) == 2
        assert measure.presentation(first)['locked'] and not measure.presentation(copied)['locked']
    finally:
        app.shutdown()
