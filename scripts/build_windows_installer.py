"""在 Windows x64 上生成原生安装向导 EXE（需要 Inno Setup 6.6+）。"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from build_windows import pyinstaller_command
from packaging_utils import APP_NAME, PROJECT_ROOT, app_version, prepare_assets


def find_iscc(explicit: str | None = None) -> Path:
    candidates = [explicit] if explicit else [
        os.getenv("INNO_SETUP_COMPILER"), shutil.which("ISCC"),
        str(Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6/ISCC.exe"),
        str(Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6/ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError("请先安装 Inno Setup 6.6+，或通过 --iscc 指定 ISCC.exe。")


def installer_command(root: Path, compiler: Path, assets: Path) -> list[str]:
    return [str(compiler), f"/DSourceDir={root / 'dist/windows' / APP_NAME}",
            f"/DAssetsDir={assets}", f"/DOutputDir={root / 'dist/installers'}",
            f"/DAppVersion={app_version(root)}", str(root / "packaging/windows/VoxPlane.iss")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", help="Inno Setup 编译器 ISCC.exe 的完整路径。")
    args = parser.parse_args(argv)
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"} or sys.maxsize <= 2**32:
        print("请在 Windows x64 上构建安装包。", file=sys.stderr)
        return 1
    if sys.version_info[:2] != (3, 13):
        print("请通过 scripts\\build_windows.ps1 使用 Python 3.13 构建。", file=sys.stderr)
        return 1
    try:
        compiler = find_iscc(args.iscc)  # 先检查，避免冻结结束后才发现编译器缺失。
        assets = prepare_assets(PROJECT_ROOT)
        command = pyinstaller_command(PROJECT_ROOT, installer=True, icon=assets / "app.ico")
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
        executable = PROJECT_ROOT / "dist/windows" / APP_NAME / f"{APP_NAME}.exe"
        if not executable.is_file():
            raise FileNotFoundError(f"没有生成预期应用：{executable}")
        subprocess.run(installer_command(PROJECT_ROOT, compiler, assets), cwd=PROJECT_ROOT, check=True)
        output = PROJECT_ROOT / "dist/installers" / f"{APP_NAME}-{app_version(PROJECT_ROOT)}-windows-x64-setup.exe"
        if not output.is_file():
            raise FileNotFoundError(f"没有生成预期安装包：{output}")
        print(f"安装包：{output}")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Windows 安装包构建失败：{error}", file=sys.stderr)
        return error.returncode if isinstance(error, subprocess.CalledProcessError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
