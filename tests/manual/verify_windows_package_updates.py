"""Upgrade the latest stable packages to the local build on a disposable Windows runner."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import uuid

from qt_dicom_viewer import __version__
from qt_dicom_viewer.core.app_updates import Installation, REPOSITORY, Release, parse_release, version_tuple
from qt_dicom_viewer.infrastructure.update_installer import prepare_installer, launch_installer


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def temporary_upgrade_directory(parent):
    directory = TemporaryDirectory(prefix='Voxenra upgrade ', dir=parent)
    try:
        yield Path(directory.name).resolve()
    finally:
        # Inno's uninstall process can return before its temporary cleanup child
        # releases _unins-done.tmp. Wait for the lock without hiding cleanup errors.
        deadline = time.monotonic() + 30
        while True:
            try:
                directory.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.25)


def require_clean_runner():
    if (sys.platform != 'win32' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('VOXENRA_RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise SystemExit('Real-package smoke is restricted to GitHub-hosted Windows runners')
    import winreg
    programs = Path(os.environ['LOCALAPPDATA']) / 'Programs'
    if any((programs / name).exists() for name in ('Voxenra', 'DICOMVision')):
        raise SystemExit('Refusing to change a pre-existing installation')
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{EA2DF9C6-5DC1-4CC3-913B-DB87DB5D0B5E}_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise SystemExit('Refusing to change a pre-existing installer registration')
    except FileNotFoundError:
        pass


@contextmanager
def settings_sentinel():
    from PySide6.QtCore import QCoreApplication, QStandardPaths
    app = QCoreApplication([])
    app.setOrganizationName('Voxenra')
    app.setApplicationName('Voxenra')
    path = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / 'display-settings.json'
    original = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = {'schemaVersion': 3, 'appearance': {'theme': 'graphite'}, 'updates': {'enabled': False}}
        path.write_text(json.dumps(data), encoding='utf-8')
        yield path
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)


def stop_tree(process):
    if process.poll() is None:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], timeout=30, check=False)
        process.wait(timeout=30)


def run_installer(executable, *options):
    with subprocess.Popen([executable, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', *options]) as process:
        try:
            if process.wait(timeout=300):
                raise RuntimeError(f'Installer exited with {process.returncode}')
        finally:
            stop_tree(process)


def verify_upgrade(root, kind, old, new_package, settings, reports):
    folder = root / kind
    folder.mkdir()
    exe = folder / 'Voxenra.exe'
    portable = kind == 'windows_portable'
    stage = root / (kind + '-update')
    stage.mkdir()
    log = reports / (kind + '.log')
    try:
        if portable:
            shutil.copyfile(root / old.name, exe)
        else:
            run_installer(root / old.name, '/SP-', '/NOCLOSEAPPLICATIONS', f'/DIR={folder}')

        workspace = folder / '升级 test.voxworkspace'
        workspace_data = json.dumps({'format': 'VoxenraWorkspace', 'version': 2, 'applicationVersion': old.version,
                                     'series': [], 'tabs': [], 'search': 'previous release'}).encode()
        workspace.write_bytes(workspace_data)
        health = root / kind / 'old-startup' / 'health.json'
        health.parent.mkdir()
        token = uuid.uuid4().hex
        health.write_text(json.dumps(dict(version=old.version, executable=str(exe), token=token)), encoding='utf-8')
        with subprocess.Popen([exe, '--voxenra-update-check', health], cwd=folder) as previous:
            try:
                deadline = time.monotonic() + 90
                while not health.with_name('ready').exists():
                    if previous.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(f'{old.name} failed to confirm startup')
                    time.sleep(.25)
                assert health.with_name('ready').read_text() == token
                candidate = stage / new_package.name
                shutil.copyfile(new_package, candidate)
                digest = sha256(candidate)
                release = Release(__version__, '', candidate.name, '', '', candidate.stat().st_size, digest)
                command = prepare_installer(Installation(kind, exe if portable else folder), release,
                                            candidate, digest, pid=previous.pid)
                with launch_installer(command, log) as helper:
                    try:
                        stop_tree(previous)
                        if helper.wait(timeout=420):
                            raise RuntimeError(f'{kind} upgrade failed: {log.read_text(errors="replace")}')
                    finally:
                        stop_tree(helper)
            finally:
                stop_tree(previous)
        assert (stage / 'result').read_text().strip() == 'success'
        assert (stage / 'ready').read_text() == json.loads((stage / 'health.json').read_text())['token']
        assert workspace.read_bytes() == workspace_data
        prefs = json.loads(settings.read_text(encoding='utf-8'))
        assert prefs['appearance']['theme'] == 'graphite' and prefs['updates']['enabled'] is False
        print(f'{kind} {old.version} → {__version__}: both versions acknowledged startup, '
              'workspace and preferences preserved', flush=True)
    finally:
        # The helper deliberately leaves the new app (or restored old app) running.
        cleanup = """
        $prefix = $env:VOXENRA_SMOKE_ROOT + [IO.Path]::DirectorySeparatorChar
        $ErrorActionPreference = 'Stop'
        for ($i = 0; $i -lt 5; $i++) {
            $running = Get-CimInstance Win32_Process | Where-Object {
                $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
            }
            if (!$running) { exit 0 }
            foreach ($p in $running) {
                if (Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue) {
                    & taskkill /PID $p.ProcessId /T /F | Out-Null
                }
            }
            Start-Sleep -Milliseconds 300
        }
        throw 'A smoke-test process survived cleanup'
        """
        subprocess.run(['powershell', '-NoProfile', '-Command', cleanup], check=True, timeout=60,
                       env=dict(os.environ, VOXENRA_SMOKE_ROOT=str(root)))
        setup_log = stage / 'setup.log'
        if setup_log.exists():
            shutil.copyfile(setup_log, reports / 'upgrade-setup.log')
        uninstall = folder / 'unins000.exe'
        if uninstall.is_file():
            run_installer(uninstall)


def main():
    require_clean_runner()
    metadata = json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}/releases/latest']))
    if version_tuple(metadata['tag_name']) >= version_tuple(__version__):
        print(f"Skipping package upgrade: latest stable is {metadata['tag_name']}, build is {__version__}.")
        return
    packages = {'windows_portable': Path('dist/Voxenra.exe'),
                'windows_installer': Path(f'dist/installers/Voxenra-{__version__}-windows-x64-setup.exe')}
    reports = Path('build/test-results/installer').resolve()
    reports.mkdir(parents=True, exist_ok=True)
    with temporary_upgrade_directory(os.environ['RUNNER_TEMP']) as root:
        releases = {}
        for kind in packages:
            old = parse_release(metadata, '0.0.0', kind)
            if old is None or not old.digest:
                raise ValueError('Previous stable release lacks a GitHub SHA-256 digest')
            subprocess.run(['gh', 'release', 'download', metadata['tag_name'], '--repo', REPOSITORY,
                            '--pattern', old.name, '--dir', root], check=True, timeout=240)
            download = root / old.name
            if download.stat().st_size != old.size or sha256(download) != old.digest:
                raise ValueError(f'Previous package does not match published size and SHA-256: {old.name}')
            releases[kind] = old
        os.environ.pop('GH_TOKEN', None)
        # The one-file bootloader may leave extracted files when its process tree is stopped.
        # Place bootloader and setup temporary files under the disposable smoke directory.
        runtime_temp = root / 'runtime-temp'
        runtime_temp.mkdir()
        os.environ.update(TEMP=str(runtime_temp), TMP=str(runtime_temp))
        with settings_sentinel() as settings:
            for kind, new in packages.items():
                verify_upgrade(root, kind, releases[kind], new, settings, reports)


if __name__ == '__main__':
    main()
