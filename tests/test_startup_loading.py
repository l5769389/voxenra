"""Empty-workspace startup must not load optional native analysis stacks."""
import os
from pathlib import Path
import subprocess
import sys


def test_empty_workspace_does_not_initialize_vtk_or_dicom_report_stack():
    root = Path(__file__).resolve().parents[1]
    code = '''
import sys
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
app = QApplication([])
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    controller = AppController(DicomImageProvider(), pacs_config_path=root / "pacs.json",
                               pacs_import_root=root / "imports")
    try:
        assert not any(m.startswith("vtkmodules.vtk") for m in sys.modules)
        assert "highdicom" not in sys.modules
        assert controller.workspaceController.tabs == []
        assert controller.exportController.dicomResults is not None
    finally:
        controller.shutdown()
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=root,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
