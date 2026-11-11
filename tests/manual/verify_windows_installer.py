"""Exercise actual installs on a disposable GitHub Windows runner only."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
import winreg


def main():
    if (sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Windows"):
        raise SystemExit("Installer smoke is restricted to disposable GitHub Windows runners")
    setup = Path(sys.argv[1]).resolve()
    output = Path("build/test-results/installer")
    output.mkdir(parents=True, exist_ok=True)
    programs = Path(os.environ["LOCALAPPDATA"]) / "Programs"
    legacy, current = programs / "Voxenra", programs / "VoxPlane"
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{EA2DF9C6-5DC1-4CC3-913B-DB87DB5D0B5E}_is1"
    if legacy.exists() or current.exists():
        raise SystemExit("Refusing to alter a pre-existing installation")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise SystemExit("Refusing to alter pre-existing installer registration")
    except FileNotFoundError:
        pass

    def install(name, *options):
        subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                        f"/LOG={output.resolve() / (name + '.log')}", *options], check=True, timeout=240)

    try:
        # An actual first install records the former brand path in Inno's registry.
        install("legacy-location", f"/DIR={legacy}")
        assert (legacy / "VoxPlane.exe").is_file()
        legacy_user = legacy / "user-image.dcm"
        legacy_user.write_bytes(b"synthetic user file")
        install("upgrade-default")
        assert (legacy / "VoxPlane.exe").is_file(), "Upgrade lost the registered install directory"
        assert not current.exists(), "Upgrade created a duplicate application"
        install("explicit-current-location", f"/DIR={current}")
        assert (current / "VoxPlane.exe").is_file()
        assert legacy_user.read_bytes() == b"synthetic user file"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as registration:
            location = winreg.QueryValueEx(registration, "InstallLocation")[0]
        assert Path(location).resolve() == current.resolve(), location

        stale = current / "_internal/PySide6/obsolete-runtime-test.txt"
        stale.write_text("installer-owned obsolete runtime")
        user = current / "user-image.dcm"
        user.write_bytes(b"synthetic user file")
        install("in-place-upgrade")
        assert not stale.exists(), "Obsolete Qt files survived upgrade"
        assert user.read_bytes() == b"synthetic user file"
        assert not list((current / "_internal").rglob("*WebEngine*"))
        assert not list((current / "_internal").rglob("Qt6Pdf*.dll"))
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
        app = subprocess.Popen([str(current / "VoxPlane.exe")], env=env)
        try:
            time.sleep(8)
            assert app.poll() is None, f"Installed app exited during startup: {app.returncode}"
        finally:
            if app.poll() is None:
                app.terminate()
            app.wait(timeout=30)
        report = {"default_directory": str(current), "old_user_file_preserved": True,
                  "upgrade_user_file_preserved": True, "obsolete_qt_removed": True,
                  "installed_app_started": True,
                  "installed_bytes": sum(p.stat().st_size for p in current.rglob("*") if p.is_file())}
        (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    finally:
        for folder in (current, legacy):
            uninstaller = folder / "unins000.exe"
            if uninstaller.is_file():
                subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
