"""Cross-platform setup for the real Qt rendering tests."""
import os
import sys
from pathlib import Path

import pytest

# Hosted Windows runners have no native OpenGL 3.2 driver. Preload the pinned
# test-only Mesa DLL before Qt/VTK imports, without changing installed apps or
# the dependencies seen by PyInstaller. Missing/incompatible DLLs fail loudly.
if sys.platform == "win32" and os.environ.get("VOXPLANE_TEST_OPENGL_DIR"):
    import ctypes
    _mesa_directory = Path(os.environ["VOXPLANE_TEST_OPENGL_DIR"])
    _mesa_search = os.add_dll_directory(str(_mesa_directory))
    _mesa_gl = ctypes.WinDLL(str(_mesa_directory / "opengl32.dll"))


@pytest.fixture(scope="session", autouse=True)
def offscreen_desktop():
    # Use a desktop-sized test surface without changing platform-based skip rules.
    # Explicit caller-supplied screen configurations remain available for QA.
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        yield
        return
    from PySide6.QtWidgets import QApplication
    # Qt splits platform arguments on ':', including a Windows drive letter.
    # Keep this path relative so configfile is not truncated to e.g. 'D'.
    configuration = Path(os.path.relpath(Path(__file__).with_name("qt-offscreen-desktop.json"))).as_posix()
    app = QApplication.instance() or QApplication([
        "pytest", "-platform", "offscreen:configfile=" + configuration])
    yield app


# Windows' offscreen plugin uses FreeType rather than the native font database.
# Point it at installed fonts so PDF and QML tests actually render text.
if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM", "").split(":")[0] == "offscreen":
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))
