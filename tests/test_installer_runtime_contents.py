"""Keep installer acceptance aligned with the report preview dependencies."""
import runpy
from pathlib import Path

import pytest

verify = runpy.run_path(str(Path(__file__).parent / "manual/verify_windows_installer.py"))["verify_runtime_contents"]


def test_pdf_preview_core_is_required(tmp_path):
    with pytest.raises(AssertionError, match="PDF preview runtime is missing"):
        verify(tmp_path)
    core = tmp_path / "PySide6/Qt6Pdf.dll"
    core.parent.mkdir()
    core.touch()
    verify(tmp_path)


@pytest.mark.parametrize("name", ["Qt6WebEngineCore.dll", "Qt6PdfWidgets.dll", "Qt6PdfQuick.dll"])
def test_unused_browser_and_pdf_ui_remain_excluded(tmp_path, name):
    core = tmp_path / "PySide6/Qt6Pdf.dll"
    core.parent.mkdir()
    core.touch()
    (core.parent / name).touch()
    with pytest.raises(AssertionError, match="Unused"):
        verify(tmp_path)
