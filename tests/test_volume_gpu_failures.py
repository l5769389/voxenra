"""Exercise failure propagation without depending on a working GPU/driver."""
from unittest.mock import Mock

import pytest
from vtkmodules.vtkCommonCore import vtkOutputWindow

from voxplane.ui.volume_render_backend import VolumeRenderBackend


def backend():
    b = VolumeRenderBackend.__new__(VolumeRenderBackend)
    b.volume = object()
    b._error = False
    b._error_details = []
    b._initialized = False
    b.window = Mock()
    b.window.GetSize.return_value = (2400, 1600)
    b.widget = Mock()
    b.mapper = Mock()
    b.marker = Mock()
    b.apply_display = Mock()
    b.apply_mask = Mock()
    b.apply_state = Mock()
    return b


def test_unsupported_opengl_stops_before_drawing():
    b = backend()
    b.window.SupportsOpenGL.return_value = False
    with pytest.raises(RuntimeError, match='OpenGL'):
        b.render(None)
    b.window.Render.assert_not_called()
    assert not b._initialized


@pytest.mark.parametrize('kind', ['vtkOSOpenGLRenderWindow', 'vtkEGLRenderWindow'])
def test_headless_fallback_is_rejected_before_native_initialization(kind):
    b = backend()
    b.window.GetClassName.return_value = kind
    # OSMesa reports support even when its dynamically loaded DLL is missing.
    b.window.SupportsOpenGL.return_value = True
    with pytest.raises(RuntimeError, match='OpenGL'):
        b.render(None)
    b.window.SupportsOpenGL.assert_not_called()
    b.widget.Initialize.assert_not_called()
    b.window.Render.assert_not_called()
    assert not b._initialized


def test_nested_shader_error_is_not_reported_as_a_successful_frame():
    b = backend()
    output = vtkOutputWindow.GetInstance()
    b.window.Render.side_effect = lambda: output.DisplayErrorText('shader compilation failed')
    with pytest.raises(RuntimeError, match='shader compilation failed'):
        b.render(None)
    b._error = False
    output.DisplayErrorText('unrelated render')
    assert not b._error  # scoped observer was removed even after failure


def test_initialization_error_prevents_first_draw():
    b = backend()
    b.widget.Initialize.side_effect = lambda: b._on_error(None, 'ErrorEvent', 'context creation failed')
    with pytest.raises(RuntimeError, match='context creation failed'):
        b.render(None)
    assert not b._initialized
    b.window.Render.assert_not_called()


@pytest.mark.parametrize('size, expected', [((640, 480), 1), ((2000, 2000), 2), ((8000, 8000), 4)])
def test_screen_ray_budget_is_stable_without_changing_voxel_sampling(size, expected):
    b = backend()
    b.window.GetSize.return_value = size
    for interactive in (False, True, False):
        b.render(None, interactive)
        b.mapper.SetImageSampleDistance.assert_called_with(expected)
    b.mapper.SetSampleDistance.assert_not_called()
    b.mapper.SetInputData.assert_not_called()
