"""Tab-wide CT window state, coalescing, phase changes and stale pixel rejection."""
from dataclasses import replace

import numpy as np
import pytest

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.model import MprFrame, TabConfig, TabType, ToolType, WindowLevel
from voxplane.model.interaction import WindowLevelChange
from voxplane.ui.controller.tab.tab_controller import TabController
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app
from test_four_d import _four_d_meta
from test_viewport_controller_hierarchy import _mpr_result


def result_for(tab, request, frame):
    result = _mpr_result(tab.viewports_by_id[request.viewport_id], frame, request.request_id)
    return replace(result, phase_identifier=request.phase_identifier,
                   frame_meta=replace(result.frame_meta, window=request.window or result.frame_meta.window,
                                      inverted=request.inverted))


def finish(tab, requests, frame, deliver=None):
    count = 0
    while requests:
        request = requests.pop(0)
        (deliver or tab.handleRenderResult)(result_for(tab, request, frame))
        count += 1
        assert count < 30, "render loop did not settle"


@pytest.fixture(params=[TabType.MPR, TabType.FOUR_D])
def linked_tab(qt_app, request):
    tab = TabController(TabConfig("linked-tab", "CT", request.param, (_four_d_meta(),)))
    requests = []
    tab.renderRequested.connect(requests.append)
    frame = MprFrame.standard_lps((0., 0., 0.))
    tab.init_render()
    finish(tab, requests, frame)
    yield tab, requests, frame
    tab.pausePlayback()


def assert_window(tab, change):
    assert all(view.current_window == change.window and view.inverted == change.inverted
               and view.windowCenter == change.window.center and view.windowWidth == change.window.width
               for view in tab.viewports_by_id.values())


@pytest.mark.parametrize("source_index", [0, 1, 2])
def test_presets_input_drag_and_reset_link_all_planes(linked_tab, source_index):
    tab, requests, frame = linked_tab
    source = list(tab.viewports_by_id.values())[source_index]
    source.applyWindowPreset(-135.5, 1234.25)
    expected = WindowLevelChange(WindowLevel(-135.5, 1234.25), False)
    assert_window(tab, expected)
    assert len(requests) == 3
    assert all(r.window == expected.window for r in requests)
    finish(tab, requests, frame)
    # Drag updates carry both window and signed-width inversion.
    expected = WindowLevelChange(WindowLevel(25, 72), True)
    source.apply_window_level(expected)
    assert_window(tab, expected)
    finish(tab, requests, frame)
    if tab.phaseCount:
        tab.setPhaseIndex(2)
        assert all(r.window == expected.window and r.inverted for r in requests)
        finish(tab, requests, frame)
        assert tab.currentPhaseIndex == 2
        assert_window(tab, expected)
    tab._handle_tool_reset_requested(ToolType.WINDOW.value)
    assert_window(tab, tab._initial_mpr_window)
    finish(tab, requests, frame)
    source.applyWindowPreset(10, 80)
    finish(tab, requests, frame)
    tab._handle_tool_command("viewport:reset")
    finish(tab, requests, frame)
    assert_window(tab, tab._initial_mpr_window)


def test_stale_window_results_cannot_publish_pixels_or_overwrite_latest_values(linked_tab):
    tab, requests, frame = linked_tab
    provider = DicomImageProvider()
    workspace = WorkspaceController(SeriesCatalog(), provider)
    workspace._tab_dict[tab.tab_config.tab_id] = tab
    source = tab.activeViewport
    source.applyWindowPreset(10, 80)
    old_requests = requests[:]
    requests.clear()
    source.apply_window_level(WindowLevelChange(WindowLevel(-250, 650), True))
    source.applyWindowPreset(12.5, 1250)
    expected = WindowLevelChange(WindowLevel(12.5, 1250), True)
    for request in old_requests:
        result = replace(result_for(tab, request, frame), image=np.full((3, 4), 255, dtype=np.uint8))
        workspace.handleRenderResult(result)
        assert request.viewport_id not in provider._images
        assert_window(tab, expected)
    assert len(requests) == 3
    finish(tab, requests, frame, workspace.handleRenderResult)
    assert_window(tab, expected)
    assert not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids
    assert len(provider._images) == 3


def test_rapid_phase_and_window_updates_keep_latest_target(linked_tab):
    tab, requests, frame = linked_tab
    if not tab.phaseCount:
        return
    tab.setPhaseIndex(1)
    tab.setPhaseIndex(2)
    tab.activeViewport.applyWindowPreset(75, 250)
    finish(tab, requests, frame)
    assert tab.currentPhaseIndex == 2
    assert_window(tab, WindowLevelChange(WindowLevel(75, 250), False))


def test_linked_window_does_not_change_other_tabs(linked_tab):
    tab, requests, frame = linked_tab
    other = TabController(TabConfig("other-tab", "CT", TabType.MPR, (_four_d_meta(),)))
    other_requests = []
    other.renderRequested.connect(other_requests.append)
    other.init_render()
    finish(other, other_requests, frame)
    previous = other.activeViewport.current_window
    tab.activeViewport.applyWindowPreset(90, 950)
    finish(tab, requests, frame)
    assert all(v.current_window == previous for v in other.viewports_by_id.values())
    assert not other_requests
