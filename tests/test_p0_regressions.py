from dataclasses import replace
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length
from test_water_qa_controller import qa_view, wait_qa
from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot, apply_tab_snapshot
from qt_dicom_viewer.model import WindowLevel, WindowLevelChange


def test_located_projection_survives_windowing(qt_app, tmp_path):
    app, series = populated_app(tmp_path)
    try:
        app.workspaceController.createTab(series.series_instance_uid, 'CT', 'mpr')
        tab = app.workspaceController.activeTab
        wait_until(lambda: all(v.loadState == 'ready' for v in tab.viewports_by_id.values()) and not tab._active_mpr_requests)
        view = tab.activeViewport
        tab.toolController.setMprProjectionEnabled(True)
        tab.toolController.setMprProjectionMode('mip')
        wait_until(lambda: not tab._active_mpr_requests)
        mid = draw_length(view)
        listing = tab.measurementResults
        key = listing.items[0]['key']
        expected = view.measurementController.frame_key
        tab.toolController.setMprProjectionEnabled(False)
        wait_until(lambda: not tab._active_mpr_requests)
        listing.locate(key)
        wait_until(lambda: not view.render_pending and view.measurementController.selectedMeasurementId == mid)
        assert view.measurementController.frame_key == expected
        view.apply_window_level(WindowLevelChange(WindowLevel(42, 420), False))
        wait_until(lambda: not tab._active_mpr_requests and not view.render_pending)
        assert view.measurementController.frame_key == expected
    finally:
        app.shutdown()


def test_qa_restore_warns_if_already_loaded_source_changed(qa_view, qt_app):
    view, frame = qa_view
    qa = view.qaController
    view._tool_controller.selectService('service:qa')
    wait_qa(qt_app, qa)
    saved = qa.persistent_state()
    qa.reset()
    qa.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel + 1)
    qa.restore_state(saved)
    qa.set_frame(frame.series_uid, frame.frame_meta, frame.modality_pixel + 1)
    assert qa.status == 'error', (qa.status, qa.error)


def test_4d_locate_save_restore_preserves_peer_phases(qt_app, tmp_path):
    from test_four_d import _cross_series_four_d
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    records = _cross_series_four_d(tmp_path)
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path,6,6,0,records)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws = app.workspaceController
        ws.createTab(records[0].series_instance_uid,'4D','4d')
        tab = ws.activeTab
        wait_until(lambda: ws._load_states[tab.tab_config.tab_id].status=='ready' and not tab._active_mpr_requests)
        view = tab.activeViewport
        mid = draw_length(view)
        key = tab.measurementResults.items[0]['key']
        tab.setPhaseIndex(2)
        wait_until(lambda: tab._current_phase_index==2 and not tab._active_mpr_requests)
        tab.measurementResults.locate(key)
        wait_until(lambda: view.measurementController.selectedMeasurementId==mid)
        expected={v.viewportId: v.measurementController.frame_key for v in tab.viewports_by_id.values()}
        saved=tab_snapshot(tab)
        apply_tab_snapshot(tab,saved)
        wait_until(lambda: not tab._active_mpr_requests)
        assert expected=={v.viewportId:v.measurementController.frame_key for v in tab.viewports_by_id.values()}
        # Exercise the file codec and a fresh tab, not only an in-memory snapshot.
        expected_roles = {v.viewportRole or v.viewportType: v.measurementController.frame_key
                          for v in tab.viewports_by_id.values()}
        manager = app.workspaceDocumentController
        path = tmp_path/'independent-phase.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        restored = ws.activeTab
        wait_until(lambda: not restored._active_mpr_requests)
        assert expected_roles == {v.viewportRole or v.viewportType: v.measurementController.frame_key
                                  for v in restored.viewports_by_id.values()}
        # Explicit phase navigation resumes normal linked behavior.
        restored.setPhaseIndex(2)
        wait_until(lambda: not restored._active_mpr_requests)
        assert all(not getattr(v, '_independent_measurement_source', None)
                   for v in restored.viewports_by_id.values())
    finally:
        app.shutdown()


def test_measurement_list_watches_views_created_after_panel_open(qt_app,tmp_path):
    from PySide6.QtTest import QSignalSpy
    app,_=populated_app(tmp_path)
    try:
        tab=app.workspaceController.activeTab
        listing=tab.measurementResults
        draw_length(tab.activeViewport)
        tab.twoDLayout.setMode(0,'coronal')
        wait_until(lambda:tab.activeViewport.loadState=='ready')
        spy=QSignalSpy(listing.changed)
        draw_length(tab.activeViewport)
        assert len(listing.items)==2
        assert spy.count()>0, 'No notify signal for QML after creating a measurement in the new view'
    finally:
        app.shutdown()
