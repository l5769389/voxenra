"""Regressions at the boundaries between the merged feature branches."""
from dataclasses import replace

import numpy as np

from voxplane.core.color_maps import color_lut
from voxplane.core.pet_reconstruction import PetReconstructor
from voxplane.core.volume_manager import VolumeManager
from voxplane.ui.controller.settings_controller import SettingsController
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from test_measurement_qml import qt_app
from test_pet_fusion import paired_series
from test_viewport_transform import _controller, _render_result
from test_series_sidebar import sidebar_scene


def test_ct_rejects_stale_frame_after_latest_frame_is_committed(qt_app):
    view = _controller()
    try:
        view.handleRenderResult(_render_result(view))
        view.request_render()
        old_id = view._latest_request_id
        view.request_render()
        current = replace(_render_result(view), response_id=view._latest_request_id)
        view.handleRenderResult(current)
        revision = view._image_revision
        stale = replace(current, response_id=old_id,
                        modality_pixel=np.full_like(current.modality_pixel, 999))
        view.handleRenderResult(stale)
        assert view._image_revision == revision
        assert view._modality_pixel is current.modality_pixel
    finally:
        view.shutdown()


def test_settings_and_viewport_palettes_share_pet_fusion_transaction(qt_app, paired_series):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    workspace._settings_controller = SettingsController(workspace, path=False)
    renderer = PetReconstructor(catalog, VolumeManager())
    requests, results = [], []

    def render(request):
        requests.append(request)
        result = renderer.render(request)
        results.append(result)
        workspace.handleRenderResult(result)

    workspace.renderRequested.connect(render)
    try:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        tab = workspace.activeTab
        viewport = tab.petController
        previous = viewport._modality_pixel.copy()
        request_count = len(requests)
        workspace._settings_controller.setValue("colormap", "pet", "pet")
        assert len(requests) == request_count + 1
        assert requests[-1].pet_color_map == "pet"
        np.testing.assert_equal(viewport._modality_pixel, previous)
        assert viewport.activeColorMap == "pet"
        pet_frame = next(frame for frame in results[-1].frames if frame.viewport_id == viewport.viewportId)
        assert pet_frame.image.ndim == 3

        # The earlier viewport branch uses this legacy palette identifier.
        viewport.applyColorMap("cardiac")
        assert requests[-1].pet_color_map == "cardiac"
        assert viewport.activeColorMap == "cardiac"
        np.testing.assert_equal(viewport._modality_pixel, previous)
        fusion = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "fusion")
        fusion.applyColorMap("hotMetal")
        assert requests[-1].fusion_color_map == "hotMetal"
        assert fusion.activeColorMap == "hotMetal"
        mip = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "mip")
        assert mip.activeColorMap == "cardiac"
        assert color_lut("cardiac").shape == (256, 3)
    finally:
        workspace.shutdown()


def test_window_template_updates_notify_open_ct_but_leave_pet_presets_empty(qt_app, paired_series):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    workspace._settings_controller = SettingsController(workspace, path=False)
    try:
        workspace.createTab(ct.series_instance_uid, "CT", "2d")
        ct_view = workspace.activeViewport
        workspace.createTab(pet.series_instance_uid, "PET", "2d")
        pet_view = workspace.activeViewport
        updates = []
        ct_view.windowPresetsChanged.connect(lambda: updates.append(True))
        workspace._settings_controller.saveWindowTemplate("", "Integration window", 321, 12)
        assert updates
        assert ct_view.windowPresets[-1]["width"] == 321
        assert pet_view.windowPresets == []
    finally:
        workspace.shutdown()


def test_image_and_volume_tab_transitions_keep_controller_types_separate(sidebar_scene, monkeypatch):
    from PySide6.QtTest import QTest
    from voxplane.model import TabType
    from voxplane.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    from test_dicom_tags import wait_until

    # Rendering itself is covered by the native smoke test. Here the real QML
    # Loader must never feed a volume controller to an outgoing image layout.
    monkeypatch.setattr(VolumeViewportController, 'ensureNativeView', lambda self: None)
    monkeypatch.setattr(VolumeViewportController, 'setNativeVisible', lambda self, visible: None)
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'Image', TabType.TWO_D)
    image_id, image_view = workspace.activeTabId, workspace.activeViewport
    wait_until(lambda: image_view.loadState == 'ready')
    workspace.createTab(records[0].series_instance_uid, 'Volume', TabType.THREE_D)
    volume_id, volume_view = workspace.activeTabId, workspace.activeViewport
    wait_until(lambda: volume_view.loadState == 'ready')
    for _ in range(3):
        for tab_id, expected in ((image_id, image_view), (volume_id, volume_view)):
            workspace.activateTabId(tab_id)
            QTest.qWait(40)
            assert workspace.activeViewport is expected
    workspace.closeTab(volume_id)
    QTest.qWait(40)
    assert workspace.activeViewport is image_view
    workspace.createTab(records[0].series_instance_uid, 'Volume reopened', TabType.THREE_D)
    QTest.qWait(60)
    assert not warnings, warnings


def test_closing_active_volume_detaches_qml_before_disposing_controller(sidebar_scene, monkeypatch):
    from voxplane.model import TabType
    from voxplane.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    from test_dicom_tags import wait_until

    monkeypatch.setattr(VolumeViewportController, "ensureNativeView", lambda self: None)
    monkeypatch.setattr(VolumeViewportController, "setNativeVisible", lambda self, visible: None)
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    uid = records[0].series_instance_uid
    workspace.createTab(uid, "Image", TabType.TWO_D)
    image_view = workspace.activeViewport
    wait_until(lambda: image_view.loadState == "ready")
    workspace.createTab(uid, "Volume", TabType.THREE_D)
    volume_id, volume_view = workspace.activeTabId, workspace.activeViewport
    wait_until(lambda: volume_view.loadState == "ready")
    disposed = []
    original_dispose = volume_view.dispose

    def dispose_after_detaching():
        # QML must receive the next controller while the outgoing QObject is alive.
        assert workspace.activeViewport is image_view
        assert window.property("viewportController") is image_view
        disposed.append(True)
        original_dispose()

    monkeypatch.setattr(volume_view, "dispose", dispose_after_detaching)
    workspace.closeTab(volume_id)
    assert disposed == [True]
    workspace.createTab(uid, "Volume reopened", TabType.THREE_D)
    wait_until(lambda: workspace.activeViewport.loadState == "ready")
    assert workspace.activeViewport is not volume_view
    assert not warnings, warnings
