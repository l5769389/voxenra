"""Collect VoxPlane's Qt Quick runtime without unrelated browser/3D QML engines.

Filter before PyInstaller analyzes binary dependencies; deleting libraries after
freezing could leave plugins with missing dependencies. The app explicitly uses
Basic controls; native QWidget platform plugins remain managed by the Gui hook.
"""
from pathlib import Path, PurePosixPath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info


def used_qml_module(destination):
    parts = PurePosixPath(str(destination).replace("\\", "/")).parts
    if "qml" not in parts:
        raise ValueError(f"Unexpected Qt QML destination: {destination}")
    module = parts[parts.index("qml") + 1:]
    if not module:
        return True
    if module[0] not in {"QtQml", "QtQuick", "QtCore"}:
        return False
    # The runtime uses Basic controls and QWidget file dialogs. Do not collect
    # unrelated QML plugins: each can pull in another native Qt library.
    if module[0] == "QtQml" and len(module) >= 2:
        return module[1] in {"Models", "WorkerScript"}
    if module[0] == "QtQuick" and len(module) >= 2 and module[1] not in {
        "Controls", "Templates", "Layouts", "Shapes", "Window",
    }:
        return False
    if module[:2] == ("QtQuick", "Controls") and len(module) >= 3:
        if module[2] not in {"Basic", "impl"}:
            return False
    return True


def runtime_qml_file(entry):
    # Type descriptions and static linking/build metadata are development-only.
    # Keep qmldir, QML/JS, shaders, images and shared runtime plugins unchanged.
    return (used_qml_module(entry[1])
            and Path(entry[0]).suffix.lower() not in {".qmltypes", ".a", ".lib", ".prl", ".pdb"})


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
binaries += [entry for entry in qml_binaries if runtime_qml_file(entry)]
datas += [entry for entry in qml_datas if runtime_qml_file(entry)]
