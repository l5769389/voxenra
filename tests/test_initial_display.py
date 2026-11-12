from dataclasses import replace

import pytest
from PySide6.QtCore import QObject

from voxplane.model import MprPlane, PixelSpacing, WindowLevel
from voxplane.settings.display_defaults import DEFAULTS, validate_options
from voxplane.ui.controller.settings_controller import SettingsController
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.controller.viewport.image_2d.stack_viewport_controller import StackViewportController
from voxplane.ui.controller.viewport.image_2d.mpr_viewport_controller import MprViewportController
from test_viewport_transform import _controller, _render_result
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app


def make_view(options, *, modality='CT', mpr=False):
    owner = QObject()
    owner._settings_controller = SettingsController(path=False)
    owner._settings_controller._data['initialDisplay'] = validate_options(options)
    config = _controller().viewport_config
    config = replace(config, series_meta=replace(config.series_meta, modality=modality),
                     viewport_type=MprPlane.AXIAL if mpr else config.viewport_type)
    tools = ToolController(parent=owner)
    cls = MprViewportController if mpr else StackViewportController
    view = cls(config, tools, parent=owner)
    return owner, view


def test_validation_partial_defaults_and_invalid_values():
    assert validate_options({}) == DEFAULTS
    assert DEFAULTS['windowMode'] == 'dicom'
    assert DEFAULTS['ctPreset'] == DEFAULTS['mrPreset'] == ''
    assert validate_options({'zoom': 'pixel'})['windowMode'] == 'dicom'
    for bad in [None, [], {'zoom': 'x'}, {'windowMode': True}, {'ctPreset': '../x'}, {'mrPreset': 3}, {'unknown': 1}]:
        with pytest.raises(ValueError):
            validate_options(bad)


@pytest.mark.parametrize('mpr', [False, True])
def test_new_view_uses_custom_template_and_snapshot_defaults(mpr):
    owner, view = make_view({'zoom': 'pixel', 'windowMode': 'preset', 'ctPreset': 'custom-one'}, mpr=mpr)
    # Construction captures defaults, including templates; this second view sees the new template.
    settings = owner._settings_controller
    settings._window_entries.append(dict(presetId='custom-one', label='Custom', center=21., width=72., enabled=True))
    new = type(view)(view.viewport_config, view._tool_controller, owner)
    assert new.viewport_state.window == WindowLevel(21., 72.)
    assert not new.fitToWindow
    settings._data['initialDisplay'] = dict(DEFAULTS)
    settings.sectionChanged.emit('initialDisplay')
    assert new.viewport_state.window == WindowLevel(21., 72.)
    assert not new.fitToWindow
    request = new.build_mpr_render_request(initial=True) if mpr else new._build_render_request(initial=True)
    assert request.window == WindowLevel(21., 72.)
    new._state = replace(new._state, window=WindowLevel(90., 120.))
    request = new.build_mpr_render_request(initial=False) if mpr else new._build_render_request(initial=False)
    assert request.window == WindowLevel(90., 120.)


@pytest.mark.parametrize('modality,preset', [('CT', 'missing'), ('MR', ''), ('PT', 'ct-bone')])
def test_missing_template_and_other_modalities_keep_dicom_fallback(modality, preset):
    owner, view = make_view({'windowMode': 'preset', 'ctPreset': preset, 'mrPreset': preset}, modality=modality)
    assert view._build_render_request(initial=True).window is None


def test_pixel_zoom_initialized_once_and_saved_state_wins():
    owner, view = make_view({'zoom': 'pixel'})
    view.setViewportSize(800., 600.)
    result = _render_result(view)
    result = replace(result, frame_meta=replace(result.frame_meta,
        geometry=replace(result.frame_meta.geometry, pixel_spacing=PixelSpacing(row=.7, column=.5))))
    view._latest_request_id = result.response_id
    view.handleRenderResult(result)
    assert view.zoom == 2.0
    view._state = replace(view._state, zoom=3.0)
    view.handleRenderResult(result)
    assert view.zoom == 3.0
    restored = StackViewportController(view.viewport_config, view._tool_controller, owner)
    restored._state = replace(restored._state, zoom=7.0)
    restored._latest_request_id = result.response_id
    restored.handleRenderResult(result)
    assert restored.zoom == 7.0


@pytest.mark.parametrize('mpr', [False, True])
def test_mr_custom_template_and_disabled_template(mpr):
    owner, view = make_view({'windowMode': 'preset', 'mrPreset': 'mr-custom'}, modality='MR', mpr=mpr)
    settings = owner._settings_controller
    settings._window_entries.append(dict(presetId='mr-custom', label='MR', center=120., width=350., enabled=True))
    new = type(view)(view.viewport_config, view._tool_controller, owner)
    assert new.viewport_state.window == WindowLevel(120., 350.)
    settings._window_entries[-1]['enabled'] = False
    newer = type(view)(view.viewport_config, view._tool_controller, owner)
    assert newer.viewport_state.window is None
    assert new.viewport_state.window == WindowLevel(120., 350.)


@pytest.mark.parametrize('restore_mode', ['workspace', 'undo-close'])
def test_actual_restoration_retains_saved_display_after_defaults_change(qt_app, tmp_path, restore_mode):
    app, record = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        view = workspace.activeViewport
        view._state = replace(view._state, zoom=2.3, window=WindowLevel(29., 312.))
        workspace.activeTab.historyController.capture()
        manager = app.workspaceDocumentController
        path = tmp_path / 'initial-display.voxworkspace'
        if restore_mode == 'workspace':
            assert manager.save_to(path)
            wait_until(lambda: not manager.busy)
            assert not manager.isError, manager.message
        else:
            assert workspace.closeTab(workspace.activeTabId)
        settings = app.settingsController
        for key, value in dict(zoom='pixel', windowMode='preset', ctPreset='ct-bone').items():
            assert settings.setValue('initialDisplay', key, value)
        if restore_mode == 'workspace':
            assert manager.restore_from(path)
            wait_until(lambda: not manager.busy, timeout=20000)
            assert not manager.isError, manager.message
        else:
            assert manager.reopenLastClosed()
            wait_until(lambda: not manager.busy, timeout=20000)
            assert not manager.isError, manager.message
        wait_until(lambda: workspace.activeViewport is not None and workspace.activeViewport.loadState == 'ready')
        restored = workspace.activeViewport
        assert restored is not view
        assert restored.zoom == 2.3
        assert restored.fitToWindow
        assert restored.viewport_state.window == WindowLevel(29., 312.)
    finally:
        app.shutdown()


def test_new_mpr_slices_receive_defaults_without_changing_open_stack(qt_app, tmp_path):
    from voxplane.ui.controller.viewport.image_2d.image_2d_viewport_controller import Image2DViewportController
    app, record = populated_app(tmp_path)
    try:
        workspace = app.workspaceController
        original = workspace.activeViewport
        original_state = original.viewport_state
        settings = app.settingsController
        for key, value in dict(zoom='pixel', windowMode='preset', ctPreset='ct-bone').items():
            assert settings.setValue('initialDisplay', key, value)
        template = next(p for p in settings.windowTemplates if p['presetId'] == 'ct-bone')
        workspace.createTab(record.series_instance_uid, 'MPR', 'mpr')
        wait_until(lambda: workspace.activeLoadState and workspace.activeLoadState.status == 'ready')
        slices = [v for v in workspace.activeTab.viewports_by_id.values() if isinstance(v, Image2DViewportController)]
        assert len(slices) == 3
        for view in slices:
            assert not view.fitToWindow
            assert view.zoom * view.imageColumnSpacing == pytest.approx(1.)
            assert view.viewport_state.window == WindowLevel(template['center'], template['width'])
        assert original.viewport_state == original_state
    finally:
        app.shutdown()
