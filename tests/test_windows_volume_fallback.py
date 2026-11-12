"""Native Windows failure presentation when VTK selects a headless fallback."""
import os
import sys
import pytest
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene


@pytest.mark.skipif(sys.platform != 'win32' or os.environ.get('VOXPLANE_NATIVE_QA') != '1', reason='Requires a native desktop OpenGL window')
def test_native_volume_headless_fallback_reports_error(sidebar_scene, monkeypatch):
    # Simulate VTK's fallback when no native OpenGL driver is available.
    monkeypatch.setenv('VTK_DEFAULT_OPENGL_WINDOW', 'vtkOSOpenGLRenderWindow')
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Unsupported graphics', '3d')
    vp = ws.activeViewport
    wait_until(lambda: vp._host is not None and vp.loadState == 'error', timeout=15000)
    host = vp._host
    assert host.backend.window.GetClassName() == 'vtkOSOpenGLRenderWindow'
    assert not host.backend._initialized and not host.frame_ready
    assert 'OpenGL' in vp.errorMessage
    assert host.stack.currentWidget() == host.status_page
    assert host.close_button.isVisible()
    assert not warnings, warnings


