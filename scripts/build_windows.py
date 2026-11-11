"""在 Windows 上生成包含 Python、Qt 和 QML 资源的便携应用。"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

from packaging_utils import prepare_assets

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pyinstaller_command(root: Path, *, console: bool = False, installer: bool = False,
                        portable_dir: bool = False, icon: Path | None = None) -> list[str]:
    """集中声明打包参数，资源位置不依赖调用者的工作目录。"""
    root = root.resolve()
    qml_directory = root / "src" / "voxplane" / "qml"
    entry = root / "scripts" / "windows_entry.py"
    if not (qml_directory / "Main.qml").is_file() or not entry.is_file():
        raise FileNotFoundError("找不到应用入口或 QML 资源，请使用完整项目目录打包。")

    name = "VoxPlane-debug" if console else "VoxPlane"
    dist = root / "dist"
    if installer:
        dist /= "windows"
    elif portable_dir:
        dist /= "portable"
    return [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if installer or portable_dir else "--onefile",
        "--console" if console else "--windowed",
        # 不使用 UPX 压缩 Qt DLL，避免插件损坏和额外的工具依赖。
        "--noupx",
        # VTK declares matplotlib as a package dependency, but this application
        # renders with VTK/Qt and never uses the optional plotting adapters.
        "--exclude-module", "matplotlib",
        "--exclude-module", "mpl_toolkits",
        "--name", name,
        "--icon", str(icon or root / "build/installer-assets/app.ico"),
        "--distpath", str(dist),
        "--workpath", str(root / "build" / "windows" / name),
        "--specpath", str(root / "build" / "windows"),
        "--paths", str(root / "src"),
        "--additional-hooks-dir", str(root / "packaging" / "hooks"),
        # hook-voxplane.py preserves package-relative QML/SVG/brand assets
        # and omits superseded PNG icon originals (still kept in the repository).
        "--add-data", f"{root / 'licenses'}:licenses",
        # 这些模块也会由 QML 间接使用，显式触发 Qt 的插件收集钩子。
        "--hidden-import", "PySide6.QtQuick",
        "--hidden-import", "PySide6.QtQuickControls2",
        "--hidden-import", "PySide6.QtSvg",
        # Python VTK uses factories and a dynamically selected Qt binding.
        "--hidden-import", "vtkmodules.qt.QVTKRenderWindowInteractor",
        "--hidden-import", "vtkmodules.vtkRenderingOpenGL2",
        "--hidden-import", "vtkmodules.vtkRenderingVolumeOpenGL2",
        "--hidden-import", "vtkmodules.vtkRenderingFreeType",
        "--hidden-import", "vtkmodules.vtkInteractionStyle",
        # Archive readers include native libraries; no external unrar executable.
        "--collect-all", "py7zr",
        "--collect-all", "unrar",
        "--hidden-import", "_cffi_backend",
        "--copy-metadata", "unrar2-cffi",
        # pixel_codecs 的项目钩子保留原生解码库和插件入口元数据。
        str(entry),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--console", action="store_true",
        help="生成带控制台的 VoxPlane-debug.exe，便于排查启动和 QML 错误。",
    )
    parser.add_argument(
        "--portable-dir", action="store_true",
        help="生成目录便携版，避免每次启动解压运行库；分发时需保留整个目录。",
    )
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("请在 Windows 上运行此脚本；PyInstaller 不支持跨平台生成 Windows EXE。", file=sys.stderr)
        return 1
    if platform.machine().lower() not in {"amd64", "x86_64"} or sys.maxsize <= 2**32:
        print("此打包入口要求 Windows x64 和 64 位 Python。", file=sys.stderr)
        return 1
    if sys.version_info[:2] != (3, 13):
        print("请使用 scripts\\build_windows.bat，以 Python 3.13 和锁定依赖打包。", file=sys.stderr)
        return 1

    try:
        prepare_assets(PROJECT_ROOT)
        command = pyinstaller_command(PROJECT_ROOT, console=args.console, portable_dir=args.portable_dir)
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"打包失败：{error}", file=sys.stderr)
        return error.returncode if isinstance(error, subprocess.CalledProcessError) else 1

    name = "VoxPlane-debug" if args.console else "VoxPlane"
    directory = PROJECT_ROOT / "dist"
    if args.portable_dir:
        directory = directory / "portable" / name
    executable = directory / f"{name}.exe"
    if not executable.is_file():
        print(f"打包没有生成预期文件：{executable}", file=sys.stderr)
        return 1
    print(f"打包完成：{executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
