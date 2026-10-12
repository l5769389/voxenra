"""Guard the dependency filter against dropping Controls/native support."""
import runpy
from pathlib import Path

import pytest
qt = pytest.importorskip("PyInstaller.utils.hooks.qt")

ROOT = Path(__file__).resolve().parents[1]


def test_qml_hook_filters_before_binary_analysis(monkeypatch):
    modules = ["QtQml/Models", "QtQml/WorkerScript", "QtQuick/Controls/Basic",
               "QtQuick/Controls/macOS", "QtQuick/Controls/Windows",
               "QtQuick/Layouts", "QtQuick/Shapes", "QtQuick/Window",
               "Qt/labs/platform", "Qt5Compat/GraphicalEffects",
               "QtWebEngine", "QtQuick3D", "Qt3D/Render", "QtMultimedia",
               "QtQuick/Scene2D", "QtQuick/Scene3D", "QtGraphs",
               "QtQuick/Pdf", "QtQuick/VirtualKeyboard/Settings"]
    modules += ["QtQuick/Particles", "QtQuick/Dialogs", "QtQuick/NativeStyle",
                "QtQuick/LocalStorage", "QtQuick/Timeline", "QtQuick/VectorImage",
                "QtQuick/Effects", "QtQml/StateMachine", "QtQml/XmlListModel"]
    entries = [(f"source/{m}/plugin", f"PySide6/Qt/qml/{m}") for m in modules]
    monkeypatch.setattr(qt, "add_qt6_dependencies", lambda _: (["PySide6.QtCore"], [], []))
    monkeypatch.setattr(qt.pyside6_library_info, "collect_qtqml_files", lambda: (entries, entries))
    hook = runpy.run_path(str(ROOT / "packaging/hooks/hook-PySide6.QtQml.py"))
    expected = entries[:3] + entries[5:8]
    assert hook["binaries"] == expected and hook["datas"] == expected
    assert hook["hiddenimports"] == ["PySide6.QtCore"]
    for file in (ROOT / "src/qt_dicom_viewer/qml").rglob("*.qml"):
        for line in file.read_text().splitlines():
            if line.startswith("import Qt"):
                module = line.split()[1].replace(".", "/")
                assert hook["used_qml_module"](f"PySide6/qml/{module}"), (file, module)


def test_qml_runtime_keeps_plugin_and_resources_but_omits_development_files(monkeypatch):
    names = ["qmldir", "Button.qml", "helper.js", "shader.qsb", "icon.png", "plugin.dll",
             "plugins.qmltypes", "plugin.a", "plugin.lib", "plugin.prl", "plugin.pdb"]
    entries = [(name, "PySide6/Qt/qml/QtQuick/Controls/Basic") for name in names]
    monkeypatch.setattr(qt, "add_qt6_dependencies", lambda _: ([], [], []))
    monkeypatch.setattr(qt.pyside6_library_info, "collect_qtqml_files", lambda: ([], entries))
    hook = runpy.run_path(str(ROOT / "packaging/hooks/hook-PySide6.QtQml.py"))
    assert hook["datas"] == entries[:6]


def test_runtime_resources_keep_svg_brand_and_all_qml():
    hook = runpy.run_path(str(ROOT / "packaging/hooks/hook-qt_dicom_viewer.py"))
    entries = {Path(source).relative_to(ROOT / "src/qt_dicom_viewer/qml").as_posix(): destination
               for source, destination in hook["datas"] if Path(source).is_relative_to(ROOT / "src/qt_dicom_viewer/qml")}
    assert any(Path(source).name == 'totalsegmentator_bridge.py' and destination == 'qt_dicom_viewer/infrastructure'
               for source, destination in hook['datas'])
    assert "assets/brand/voxenra-mark.png" in entries
    assert not any(name.startswith("assets/icons/") and name.endswith(".png") for name in entries)
    assert "assets/icons/README.md" in entries
    for source in (ROOT / "src/qt_dicom_viewer/qml").rglob("*"):
        if source.suffix in {".qml", ".js", ".svg"} or source.name == "qmldir":
            relative = source.relative_to(ROOT / "src/qt_dicom_viewer/qml")
            assert Path(entries[relative.as_posix()]).as_posix() == (Path("qt_dicom_viewer/qml") / relative.parent).as_posix()


def test_gui_hook_keeps_native_platform_and_image_codecs(monkeypatch):
    names = ["libqpdf.dylib", "qpdf.dll", "libqtvirtualkeyboardplugin.so", "qtvirtualkeyboardplugin.dll",
             "libqcocoa.dylib", "qwindows.dll", "libqoffscreen.so", "qjpeg.dll", "qsvg.dll", "libqgif.dylib"]
    entries = [(name, "plugins") for name in names]
    monkeypatch.setattr(qt, "add_qt6_dependencies", lambda _: (["PySide6.QtCore"], entries, []))
    hook = runpy.run_path(str(ROOT / "packaging/hooks/hook-PySide6.QtGui.py"))
    assert hook["binaries"] == entries[4:]
