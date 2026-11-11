"""Rendered color/inversion, linked state and actual montage detail controls."""
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from voxplane.core.color_maps import apply_color_map
from voxplane.core.pet_reconstruction import PetReconstructor
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import ToolType, WindowLevel, RenderFailure
from voxplane.model.interaction import WindowLevelChange
from voxplane.model.render_models import PetBatchRenderRequest
from voxplane.ui.workers.dicom_render_worker import DicomRenderWorker
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from test_montage_controller import _controller, _accept, _result
from test_montage_rendering import _catalog, _dataset, _request
from test_dicom_tags import qt_app, wait_until
from test_pet_fusion import paired_series
from test_linked_ct_window import linked_tab, finish, assert_window
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_display_tools_qml import display_panel, _find, _click


def test_montage_color_and_inversion_use_decoded_cache(tmp_path, monkeypatch):
    from voxplane.core.dicom_loader import DicomLoader
    from pydicom.uid import CTImageStorage
    dataset = _dataset()
    dataset.SOPClassUID = CTImageStorage
    dataset.Modality = "CT"
    dataset.save_as(tmp_path / "slice.dcm", enforce_file_format=True)
    reads = []
    decode = DicomLoader.to_modality_pixels
    monkeypatch.setattr(DicomLoader, "to_modality_pixels", staticmethod(
        lambda source: reads.append(source.SOPInstanceUID) or decode(source)))
    worker = DicomRenderWorker(_catalog(tmp_path), VolumeManager())
    results = []
    worker.render_finished.connect(results.append)
    worker.handleRenderRequest(_request("gray"))
    worker.handleRenderRequest(replace(_request("inverse"), inverted=True))
    worker.handleRenderRequest(replace(_request("color"), color_map="hotIron"))
    worker.handleRenderRequest(replace(_request("both"), color_map="hotIron", inverted=True))
    assert len(reads) == 1
    gray, inverse, color, both = [r.image for r in results]
    np.testing.assert_allclose(inverse, 255 - gray, atol=1)  # existing float windowing quantization
    np.testing.assert_array_equal(color, apply_color_map(gray, "hotIron"))
    np.testing.assert_array_equal(both, apply_color_map(inverse, "hotIron"))
    assert color.shape == (2, 2, 3) and not np.array_equal(color[..., 0], color[..., 2])


def test_montage_rejects_old_palette_and_retains_inversion_on_window(qt_app):
    c = _controller(320)
    requests = []
    c.renderRequested.connect(requests.append)
    c.setVisibleRange(0, 3)
    _accept(c, requests[0])
    old = requests[-1]
    c.applyColorMap("hotIron")
    c.toggleInverted()
    c.applyWindowPreset(100, 800)
    assert not c.accepts_result(_result(old))
    assert requests[-1].color_map == "hotIron" and requests[-1].inverted
    assert requests[-1].window == WindowLevel(100, 800)
    c.reset_tool_state(ToolType.WINDOW)
    assert not c.inverted and c.activeColorMap == "hotIron"
    c.toggleInverted()
    c.reset_all_view_state()
    assert not c.inverted and c.activeColorMap == "grayscale"
    assert c.windowWidth == 400
    c.dispose()


def test_ct_inversion_button_toggles_and_window_reset_restores(display_panel):
    view, c, warnings = display_panel
    window = c.current_window
    button = _find(view.rootObject(), "invertWindowButton")
    assert button.isVisible()
    _click(view, button)
    assert c.inverted and button.property("checked") and c.current_window == window
    c.applyWindowPreset(70, 800)
    assert c.inverted
    _click(view, button)
    assert not c.inverted and c.windowWidth == 800
    _click(view, button)
    c.reset_tool_state(ToolType.WINDOW)
    assert not c.inverted
    assert not warnings, warnings


def test_inversion_button_uses_linked_mpr_four_d_state(linked_tab):
    tab, requests, frame = linked_tab
    c = list(tab.viewports_by_id.values())[1]
    window = c.current_window
    c.toggleInverted()
    assert_window(tab, WindowLevelChange(window, True))
    finish(tab, requests, frame)
    if tab.phaseCount:
        tab.setPhaseIndex(2)
        finish(tab, requests, frame)
        assert_window(tab, WindowLevelChange(window, True))
    c.toggleInverted()
    assert_window(tab, WindowLevelChange(window, False))


def test_fusion_ct_inversion_changes_only_ct_layer_and_cache_identity(qt_app, paired_series):
    catalog, ct, pet = paired_series
    ws = WorkspaceController(catalog, DicomImageProvider())
    requests = []
    ws.renderRequested.connect(requests.append)
    ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = ws.activeTab
    renderer = PetReconstructor(catalog, VolumeManager())
    first = renderer.render(requests[-1])
    tab.handleRenderResult(first)
    tab.toggleCtInverted()
    inverted = renderer.render(requests[-1])
    tab.handleRenderResult(inverted)
    a = {v: f for (v, _), f in zip(first.request.viewports, first.frames)}
    b = {v: f for (v, _), f in zip(inverted.request.viewports, inverted.frames)}
    valid = np.isfinite(a["ct"].modality_pixel)
    np.testing.assert_array_equal(b["ct"].image[valid], 255-a["ct"].image[valid])
    np.testing.assert_array_equal(b["pet"].image, a["pet"].image)
    np.testing.assert_array_equal(b["mip"].image, a["mip"].image)
    assert b["ct"].content_key != a["ct"].content_key
    assert b["fusion"].content_key != a["fusion"].content_key
    tab.setCtWindow(30, 600)
    assert requests[-1].ct_inverted
    tab.toggleCtInverted()
    tab.handleRenderFailure(RenderFailure(request_id=requests[-1].request_id,
        viewport_id=tab._tab_config.tab_id, error=ValueError("synthetic failure")))
    assert tab.ctInverted  # return to the last successfully presented frame
    tab._handle_tool_reset_requested("ct-window")
    assert not tab.ctInverted and not requests[-1].ct_inverted
    ws.closeTab(tab._tab_config.tab_id)


def test_montage_real_palette_inversion_and_collapsible_details(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, "显示优化", "montage")
    wait_until(lambda: ws.activeViewport.hasWindow)
    c = ws.activeViewport
    header = find(window, "montageHeader")
    grid = find(window, "montageGrid")
    # Image readiness precedes Qt Quick's first layout pass on Windows.
    assert not window.grabWindow().isNull()
    expanded_height, grid_height = header.height(), grid.height()
    button = find(window, "montageDetailsToggle")
    click(window, button)
    wait_until(lambda: header.height() < expanded_height)
    assert not c.detailsExpanded and grid.height() > grid_height
    assert not next(i for i in descendants(window.contentItem()) if i.objectName() == "montageDetails").isVisible()
    assert button.isVisible()
    click(window, find(window, "primaryTool-pseudocolor"))
    click(window, find(window, "colorMap-hotIron"))
    assert c.activeColorMap == "hotIron"
    click(window, find(window, "primaryTool-window"))
    click(window, find(window, "invertWindowButton"))
    assert c.inverted
    wait_until(lambda: c._active_request is None)
    assert window.grabWindow().save(str(tmp_path / "montage-collapsed-inverted.png"))
    click(window, button)
    wait_until(lambda: c.detailsExpanded)
    assert not window.grabWindow().isNull()
    assert header.height() == pytest.approx(expanded_height, abs=1), (
        header.height(), expanded_height, header.width())
    assert c.detailsExpanded and c.activeColorMap == "hotIron" and c.inverted
    assert window.grabWindow().save(str(tmp_path / "montage-expanded.png"))
    assert not warnings, warnings
