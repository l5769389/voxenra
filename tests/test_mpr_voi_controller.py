from types import SimpleNamespace
from threading import Event
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtTest import QTest

from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.tab.mpr_voi_controller import MprVoiController
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.model import TabType, MprPlane, MprFrame
from test_measurement_qml import qt_app
from test_mpr_reslicer import _volume
from test_mpr_voi_qml import settle


@pytest.fixture
def setup_voi(qt_app):
    tools = ToolController(tab_type=TabType.MPR)
    controller = MprVoiController(tools)
    volume = _volume(np.full((9, 10, 11), 500.))
    g = MprReslicer().reslice(volume, MprPlane.AXIAL, MprFrame(volume.geometry.center_patient)).geometry
    viewport = SimpleNamespace(_plane_geometry=g, _voi_volume=volume, viewportId="a",
        viewport_config=SimpleNamespace(series_meta=SimpleNamespace(modality="CT")))
    controller.set_source(volume)
    tools.activateTool("segmentation")
    yield controller, viewport, tools
    controller.dispose()


def draw(controller, viewport):
    controller.begin(viewport, 2, 2, .1)
    controller.finish(viewport, 7, 7)


def test_stale_async_result_cannot_replace_new_threshold_or_deleted_voi(setup_voi, monkeypatch):
    controller, viewport, _ = setup_voi
    import qt_dicom_viewer.ui.controller.tab.mpr_voi_controller as module
    actual = module.evaluate_voi
    entered, release = Event(), Event()
    calls = []
    def delayed(*args, **kwargs):
        calls.append(kwargs["threshold"])
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return actual(*args, **kwargs)
    monkeypatch.setattr(module, "evaluate_voi", delayed)
    try:
        draw(controller, viewport)
        controller._launch()
        assert entered.wait(2)
        controller.setThreshold(501)
        release.set()
        settle(controller)
        assert calls == [300., 501.]
        assert controller.evaluations[controller.selectedId].metrics["count"] == 0
        controller.clear("")
        QTest.qWait(150)
        assert controller.evaluations == {} and controller.items == []
    finally:
        release.set()


def test_resize_cancel_visibility_independence_and_clear_kind(setup_voi):
    controller, viewport, tools = setup_voi
    draw(controller, viewport)
    settle(controller)
    record = controller.records[0]
    before = record["region"]
    controller.begin(viewport, 2, 2, .1)
    controller.update(viewport, 1, 1)
    controller.cancel()
    assert record["region"] == before
    controller.begin(viewport, 2, 2, .1)
    controller.finish(viewport, 1, 1)
    settle(controller)
    assert record["region"].size[:2] == (6, 6)
    tools.activateTool("voi")
    draw(controller, viewport)
    settle(controller)
    assert len(controller.records) == 2
    controller.select(record["id"])
    assert tools.activePanel == "segmentation"
    controller.toggleVisible(record["id"])
    assert len(controller.overlays(viewport)) == 1
    controller.setThreshold(float("nan"))
    controller.setDepth(-1)
    assert record["threshold"] == 300 and record["region"].size[2] > 0
    controller.clear("segmentation")
    assert [r["kind"] for r in controller.records] == ["voi"]


def test_failures_are_reported_and_new_settings_retry(setup_voi, monkeypatch):
    controller, viewport, _ = setup_voi
    import qt_dicom_viewer.ui.controller.tab.mpr_voi_controller as module
    original = module.evaluate_voi
    def fail(*args, **kwargs):
        raise RuntimeError("test failure")
    monkeypatch.setattr(module, "evaluate_voi", fail)
    draw(controller, viewport)
    QTest.qWait(250)
    assert controller.error == "test failure" and not controller.busy
    monkeypatch.setattr(module, "evaluate_voi", original)
    controller.setThreshold(400)
    settle(controller)
    assert not controller.error


def test_sources_and_masks_stay_in_physical_coordinates_after_render_change(setup_voi):
    controller, viewport, _ = setup_voi
    draw(controller, viewport)
    settle(controller)
    key = controller.selectedId
    assert controller.evaluations[key].metrics["count"] > 0
    # A translated source (e.g. registered PET) no longer overlaps the fixed VOI.
    source = viewport._voi_volume
    moved = replace(source, geometry=replace(source.geometry, origin_patient=(100., 100., 100.)))
    controller.set_source(moved)
    settle(controller)
    assert controller.evaluations[key].metrics["count"] == 0


def test_auto_depth_tracks_resize_until_manually_overridden(setup_voi):
    controller, viewport, _ = setup_voi
    draw(controller, viewport)
    record = controller.records[0]
    assert record["depthAuto"] and record["region"].size == (5, 5, 5)
    controller.begin(viewport, 2, 2, .1)
    controller.finish(viewport, 1, 1)
    assert record["region"].size == (6, 6, 6)
    controller.setDepth(3)
    controller.begin(viewport, 1, 1, .1)
    controller.finish(viewport, 0, 0)
    assert not record["depthAuto"] and record["region"].size == (7, 7, 3)
    controller.setAutoDepth(True)
    assert record["depthAuto"] and record["region"].size == (7, 7, 7)
    settle(controller)


def test_circle_horizontal_draw_radius_edit_and_manual_ellipsoid(setup_voi):
    controller, viewport, tools = setup_voi
    tools.activateTool("voi")
    controller.begin(viewport, 5, 5, .1)
    controller.finish(viewport, 8, 5)
    record = controller.records[0]
    original_center = record["region"].center
    assert record["region"].shape == "ellipsoid" and record["region"].size == (6, 6, 6)
    controller.setDepth(2)
    controller.begin(viewport, 8, 5, .1)
    controller.finish(viewport, 9, 5)
    assert record["region"].size == (8, 8, 2)
    assert record["region"].center == original_center
    controller.setAutoDepth(True)
    controller.setDiameter(5)
    assert record["region"].size == (5, 5, 5)
    controller.begin(viewport, 5, 5, .1)
    controller.finish(viewport, 6, 6)
    assert len(controller.records) == 1
    np.testing.assert_allclose(np.array(record["region"].center) - original_center, [1, 1, 0])
    settle(controller)
    assert len(controller.overlays(viewport)[0]["handles"]) == 4
    assert len(controller.selected["metrics"]) == 6


def test_tiny_cancelled_circle_does_not_commit_last_large_draft(setup_voi):
    controller, viewport, tools = setup_voi
    tools.activateTool("voi")
    controller.begin(viewport, 5, 5, .1)
    controller.update(viewport, 8, 5)
    controller.finish(viewport, 5, 5)
    assert controller.records == []


def test_drag_reuses_static_masks_and_contours_without_refreshing_statistics(setup_voi, monkeypatch):
    controller, viewport, tools = setup_voi
    import qt_dicom_viewer.ui.controller.tab.mpr_voi_controller as module
    draw(controller, viewport)
    settle(controller)
    segmentation = controller.selectedId
    tools.activateTool("voi")
    controller.begin(viewport, 5, 5, .1)
    controller.finish(viewport, 7, 5)
    settle(controller)
    masks = controller.masks(viewport)
    controller.overlays(viewport)
    old_result = controller.evaluations[controller.selectedId]
    mask_calls, polygons, details, list_changes = [], [], [], []
    actual_polygon = module.plane_polygon
    import qt_dicom_viewer.ui.segmentation_overlay_renderer as renderer
    monkeypatch.setattr(renderer, "plane_mask", lambda *args: mask_calls.append(args))
    def polygon(region, g):
        polygons.append(region.shape)
        return actual_polygon(region, g)
    monkeypatch.setattr(module, "plane_polygon", polygon)
    controller.changed.connect(lambda: details.append(True))
    controller.itemsChanged.connect(lambda: list_changes.append(True))
    controller.begin(viewport, 5, 5, .1)
    for i in range(60):
        controller.update(viewport, 5 + i / 100, 5)
        controller.overlays(viewport)
        assert controller.masks(viewport) == masks
    assert not mask_calls and not details and not list_changes
    assert polygons and set(polygons) == {"ellipsoid"}
    assert controller.evaluations[controller.selectedId] is old_result
    controller.cancel()
    assert controller.masks(viewport)[0]["id"] == segmentation


def test_edit_hit_test_matches_region_drag_and_ignores_hidden_or_other_slices(setup_voi):
    controller, viewport, tools = setup_voi
    tools.activateTool("voi")
    controller.begin(viewport, 5, 5, .1)
    controller.finish(viewport, 8, 5)
    for point, mode in [((5, 5), "move"), ((8, 5), "radius")]:
        assert controller.edit_target(viewport, *point, .1)["mode"] == mode
        controller.begin(viewport, *point, .1)
        assert controller._draft["mode"] == mode
        controller.cancel()
    assert controller.edit_target(viewport, 9, 9, .1) is None
    controller.setEnabled(False)
    assert controller.edit_target(viewport, 5, 5, .1) is None
    controller.setEnabled(True)
    controller.toggleVisible(controller.selectedId)
    assert controller.edit_target(viewport, 5, 5, .1) is None
    controller.toggleVisible(controller.selectedId)
    viewport._plane_geometry = replace(viewport._plane_geometry, image_origin_mpr=(0., 0., 100.))
    assert controller.edit_target(viewport, 5, 5, .1) is None
