"""Detached installers. They wait for the app to exit before touching its files.

Only local, generated scripts run; release notes and downloaded scripts never run.
The package is checked again in the helper to cover the exit/install interval.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

from qt_dicom_viewer.core.app_updates import Installation, Release


def prepare_installer(installation: Installation, release: Release, package: Path,
                      digest: str, *, pid: int | None = None) -> list[str]:
    target = installation.target
    if target is None or not target.exists() or target.is_symlink():
        raise OSError("Application installation is unavailable")
    # Do not prompt for administrator credentials or install elsewhere silently.
    if not os.access(target.parent, os.W_OK):
        raise PermissionError("Application folder is not writable")
    stage = package.parent
    token = uuid.uuid4().hex
    suffix = {"macos": ".app", "windows_portable": ".exe"}.get(installation.kind, "")
    backup = target.with_name(f".voxenra-backup-{token}{suffix}")
    fresh = target.with_name(f".voxenra-update-{token}" + (".app" if installation.kind == "macos" else ".exe"))
    executable = (target / "Contents/MacOS/Voxenra" if installation.kind == "macos" else
                  target / "Voxenra.exe" if installation.kind == "windows_installer" else target)
    (stage / "health.json").write_text(json.dumps(dict(token=token, version=release.version,
        executable=str(executable))), encoding="utf-8")
    values = dict(target=str(target), package=str(package), digest=digest, token=token,
                  executable=str(executable), health_timeout=60,
                  version=release.version, pid=pid if pid is not None else os.getpid(),
                  stage=str(stage), backup=str(backup), fresh=str(fresh), kind=installation.kind)
    if installation.kind == "macos":
        script = stage / "install.sh"
        assignments = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())
        script.write_text("#!/bin/sh\n" + assignments + "\n" + MAC_SCRIPT, encoding="utf-8")
        script.chmod(0o700)
        return ["/bin/sh", str(script)]
    if installation.kind in {"windows_installer", "windows_portable"}:
        script = stage / "install.ps1"
        encoded = base64.b64encode(json.dumps(values, ensure_ascii=False).encode("utf-8")).decode("ascii")
        preamble = "$c = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "')) | ConvertFrom-Json\n"
        script.write_text(preamble + WINDOWS_SCRIPT, encoding="utf-8-sig")
        shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        return [str(shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    raise ValueError("Unsupported installation")


def launch_installer(command: list[str], log: Path):
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        environment["PATH"] = os.pathsep.join(entry for entry in environment.get("PATH", "").split(os.pathsep)
                                              if entry and not Path(entry).is_relative_to(bundle))
    kwargs = {"stdin": subprocess.DEVNULL, "close_fds": True, "cwd": str(log.parent), "env": environment}
    restore_dll = None
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # System PowerShell must not inherit PyInstaller's private DLL directory.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        previous = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(previous), previous)
        kernel.SetDllDirectoryW(None)
        restore_dll = lambda: kernel.SetDllDirectoryW(previous.value or None)
    else:
        kwargs["start_new_session"] = True
    # Explicitly close our copy of the log descriptor after the child inherits it.
    try:
        with log.open("ab") as output:
            return subprocess.Popen(command, stdout=output, stderr=output, **kwargs)
    finally:
        if restore_dll:
            restore_dll()


def restart_current_application():
    """Last-resort recovery when the helper itself could not be launched."""
    import logging
    try:
        executable = Path(sys.executable).resolve()
        if sys.platform == "darwin":
            subprocess.Popen(["/usr/bin/open", "-n", str(executable.parent.parent.parent)],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            subprocess.Popen([str(executable)], env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"),
                             close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    except OSError:
        logging.getLogger(__name__).exception("Could not reopen original application")


MAC_SCRIPT = r'''
set -eu
mount="$stage/mount"
moved=0
installed=0
exited=0
newpid=""
finish() {
    code=$?
    trap - EXIT
    if [ -d "$mount" ]; then /usr/bin/hdiutil detach "$mount" -quiet || true; fi
    if [ "$code" -ne 0 ]; then
        if [ -n "$newpid" ] && kill -0 "$newpid" 2>/dev/null; then
            kill "$newpid" 2>/dev/null || true
            sleep 1
            kill -9 "$newpid" 2>/dev/null || true
            wait "$newpid" 2>/dev/null || true
        fi
        relaunch="$target"
        if [ "$moved" -eq 1 ] && [ -d "$backup" ]; then
            if [ "$installed" -eq 1 ]; then /bin/rm -rf "$target" || true; fi
            if ! /bin/mv "$backup" "$target"; then relaunch="$backup"; fi
        fi
        /bin/rm -rf "$fresh" || true
        /bin/rm -f "$package" || true
        printf 'failed' > "$stage/result"
        if [ "$exited" -eq 1 ]; then /usr/bin/open -n "$relaunch" || true; fi
    fi
    exit "$code"
}
trap finish EXIT
# A timeout must leave the still-running application untouched.
attempt=0
while kill -0 "$pid" 2>/dev/null; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 120 ] || exit 1
    sleep 1
done
exited=1
actual=$(/usr/bin/shasum -a 256 "$package")
[ "${actual%% *}" = "$digest" ]
/bin/mkdir "$mount"
/usr/bin/hdiutil attach "$package" -readonly -nobrowse -noautoopen -mountpoint "$mount" -quiet
source="$mount/Voxenra.app"
[ -d "$source" ] && [ ! -L "$source" ]
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$source/Contents/Info.plist")" = 'com.junliu.voxenra' ]
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$source/Contents/Info.plist")" = "$version" ]
/usr/bin/codesign --verify --deep --strict "$source"
# Copy and verify on the destination filesystem before the two renames.
/usr/bin/ditto "$source" "$fresh"
/usr/bin/codesign --verify --deep --strict "$fresh"
/bin/mv "$target" "$backup"
moved=1
/bin/mv "$fresh" "$target"
installed=1
/usr/bin/hdiutil detach "$mount" -quiet
/bin/rm -f "$package"
"$executable" --voxenra-update-check "$stage/health.json" >> "$stage/startup.log" 2>&1 &
newpid=$!
attempt=0
while :; do
    kill -0 "$newpid" 2>/dev/null || exit 1
    if [ -f "$stage/ready" ] && [ "$(cat "$stage/ready")" = "$token" ]; then break; fi
    attempt=$((attempt + 1))
    [ "$attempt" -lt "$health_timeout" ] || exit 1
    sleep 1
done
printf 'success' > "$stage/result"
trap - EXIT
/bin/rm -rf "$backup" || true
'''


WINDOWS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$backedUp = $false
$changed = $false
$exited = $false
$newProcess = $null
$result = Join-Path $c.stage 'result'
try {
    $owner = Get-Process -Id $c.pid -ErrorAction SilentlyContinue
    if ($owner -and -not $owner.WaitForExit(120000)) { throw 'Application did not exit.' }
    $exited = $true
    if ((Get-FileHash -LiteralPath $c.package -Algorithm SHA256).Hash.ToLowerInvariant() -ne $c.digest) {
        throw 'Package checksum mismatch.'
    }
    if ($c.kind -eq 'windows_installer') {
        # Keep a full application backup before Inno updates its managed runtime.
        Copy-Item -LiteralPath $c.target -Destination $c.backup -Recurse
        $backedUp = $true
        $args = @('/SILENT', '/SP-', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS',
            ('/DIR="' + $c.target + '"'), ('/LOG="' + (Join-Path $c.stage 'setup.log') + '"'))
        $changed = $true
        $setup = Start-Process -FilePath $c.package -ArgumentList $args -PassThru -Wait
        if ($setup.ExitCode -ne 0) { throw ('Installer failed: ' + $setup.ExitCode) }
        $executable = Join-Path $c.target 'Voxenra.exe'
    } else {
        Copy-Item -LiteralPath $c.package -Destination $c.fresh
        # A one-file bootloader may outlive its Python child briefly.
        for ($retry = 0; ; $retry++) {
            try { Move-Item -LiteralPath $c.target -Destination $c.backup; break }
            catch { if ($retry -ge 30) { throw }; Start-Sleep -Seconds 1 }
        }
        $backedUp = $true
        $changed = $true
        Move-Item -LiteralPath $c.fresh -Destination $c.target
        $executable = $c.target
    }
    Remove-Item -LiteralPath $c.package -Force
    $health = Join-Path $c.stage 'health.json'
    $newProcess = Start-Process -FilePath $executable -WorkingDirectory (Split-Path -Parent $executable) `
        -ArgumentList @('--voxenra-update-check', ('"' + $health + '"')) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($c.health_timeout)
    $ready = Join-Path $c.stage 'ready'
    while ($true) {
        $newProcess.Refresh()
        if ($newProcess.HasExited) { throw 'New application exited before confirming startup.' }
        if ((Test-Path -LiteralPath $ready) -and (Get-Content -LiteralPath $ready -Raw) -eq $c.token) { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'New application did not confirm startup.' }
        Start-Sleep -Milliseconds 250
    }
    Set-Content -LiteralPath $result -Value 'success' -Encoding ASCII
    Remove-Item -LiteralPath $c.backup -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    $_ | Out-String | Write-Output
    if ($newProcess -and -not $newProcess.HasExited) {
        & "$env:SystemRoot/System32/taskkill.exe" /PID $newProcess.Id /T /F 2>&1 | Out-Null
        $null = $newProcess.WaitForExit(10000)
    }
    $restored = $true
    if ($backedUp -and $changed) {
        try {
            if (Test-Path -LiteralPath $c.target) { Remove-Item -LiteralPath $c.target -Recurse -Force }
            Move-Item -LiteralPath $c.backup -Destination $c.target
        } catch { $restored = $false; $_ | Out-String | Write-Output }
    }
    Remove-Item -LiteralPath $c.fresh -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $c.package -Force -ErrorAction SilentlyContinue
    Set-Content -LiteralPath $result -Value 'failed' -Encoding ASCII
    $old = if ($c.kind -eq 'windows_installer') { Join-Path $c.target 'Voxenra.exe' } else { $c.target }
    if (-not $restored) {
        $old = if ($c.kind -eq 'windows_installer') { Join-Path $c.backup 'Voxenra.exe' } else { $c.backup }
    }
    if ($exited) { Start-Process -FilePath $old -ErrorAction SilentlyContinue }
    exit 1
}
'''
