"""Opt-in native 3D diagnostics; preserve the real renderer and shortcut test."""
import logging
import os
import sys
from pathlib import Path

if sys.platform == 'win32' and os.environ.get('VOXPLANE_TEST_OPENGL_DIR'):
    import ctypes
    runtime = Path(os.environ['VOXPLANE_TEST_OPENGL_DIR'])
    search = os.add_dll_directory(str(runtime))
    mesa = ctypes.WinDLL(str(runtime / 'opengl32.dll'))

from voxplane.ui.volume_render_backend import VolumeRenderBackend

logging.basicConfig(level=logging.INFO)
original = VolumeRenderBackend._render_frame


def render_frame(self, *args):
    if not self._initialized:
        print('INITIALIZING', self.window.GetClassName(),
              'vtk_window=', self.window.GetGenericWindowId(),
              'qt_window=', int(self.widget.winId()),
              'size=', self.window.GetSize(), flush=True)
        print('OPENGL_SUPPORT', self.window.SupportsOpenGL(),
              self.window.GetOpenGLSupportMessage(), flush=True)
        if self.window.GetClassName() not in {'vtkOSOpenGLRenderWindow', 'vtkEGLRenderWindow'}:
            print('CAPABILITIES', self.window.ReportCapabilities(), flush=True)
    return original(self, *args)


VolumeRenderBackend._render_frame = render_frame
import pytest
raise SystemExit(pytest.main([
    'tests/test_reading_menu_shortcuts.py::test_native_volume_canvas_keeps_active_menu_shortcut',
    'tests/test_windows_volume_fallback.py::test_native_volume_headless_fallback_reports_error',
    '-vv', '-s', '--log-cli-level=INFO',
    '--junitxml=build/volume-diagnostics/result.xml',
]))
