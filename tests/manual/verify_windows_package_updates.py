"""Upgrade explicitly pinned baseline packages to the local build on a disposable Windows runner."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import uuid

from voxplane import __version__
from voxplane.core.app_updates import Installation, REPOSITORY, Release, parse_release, version_tuple
from voxplane.infrastructure.update_installer import prepare_installer, launch_installer


def previous_release(metadata, kind):
    """Validate immutable pre-rename assets without relaxing the production updater."""
    version = str(metadata['tag_name']).removeprefix('v')
    if version_tuple(version) >= (2, 6, 0):
        return parse_release(metadata, '0.0.0', kind)
    migrated = deepcopy(metadata)
    base = f'https://github.com/{REPOSITORY}/releases/download/{metadata["tag_name"]}/'
    for asset in migrated.get('assets', []):
        name = asset.get('name', '')
        if name.startswith(f'Voxenra-{version}-'):
            if asset.get('browser_download_url') != base + name:
                raise ValueError('Unexpected historical download URL')
            asset['name'] = name.replace('Voxenra-', 'VoxPlane-', 1)
            asset['browser_download_url'] = base + asset['name']
    result = parse_release(migrated, '0.0.0', kind)
    if result is None:
        return None
    return replace(result, name=result.name.replace('VoxPlane-', 'Voxenra-', 1),
                   url=result.url.replace('/VoxPlane-', '/Voxenra-'),
                   checksum_url=result.checksum_url.replace('/VoxPlane-', '/Voxenra-'))



FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'upgrades'


def load_baseline(path, candidate_version):
    """A missing/invalid baseline is a failed prerequisite, never a green skip."""
    metadata = json.loads(Path(path).read_text(encoding='utf-8'))
    if version_tuple(metadata['tag_name']) >= version_tuple(candidate_version):
        raise ValueError('Upgrade baseline must be older than candidate')
    releases = {kind: previous_release(metadata, kind)
                for kind in ('windows_portable', 'windows_installer')}
    if any(release is None or not release.digest for release in releases.values()):
        raise ValueError('Pinned baseline requires complete assets and SHA-256 digests')
    return metadata, releases


def matches_expected(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches_expected(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(matches_expected(a, e) for a, e in zip(actual, expected)))
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (type(actual) in (int, float)
                and math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-7))
    return type(actual) is type(expected) and actual == expected


def check_restored_workspace(executable, fixture, reports):
    """Exercise the installed runtime, including image values and saved results."""
    expected = json.loads((fixture / 'expected.json').read_text(encoding='utf-8'))
    expected.update(version=__version__, settings={
        'appearance': {'theme': 'graphite'}, 'updates': {'enabled': False}})
    expected_path = reports / 'workspace-expected.json'
    expected_path.write_text(json.dumps(expected), encoding='utf-8')
    report_path = reports / 'workspace-restored.json'
    report_path.unlink(missing_ok=True)
    subprocess.run([str(executable), '--verify-workspace', str(fixture / 'workspace.voxworkspace'),
                    str(expected_path), str(report_path)], check=True, timeout=120)
    report = json.loads(report_path.read_text(encoding='utf-8'))
    observed = {key: value for key, value in expected.items() if key != 'sources'}
    if (report.get('passed') is not True or report.get('errors') != []
            or not matches_expected(report, observed)):
        raise ValueError(f'Installed runtime failed workspace restoration: {report}')
    return report


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def temporary_upgrade_directory(parent):
    directory = TemporaryDirectory(prefix='VoxPlane upgrade ', dir=parent)
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
            or os.environ.get('VOXPLANE_RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise SystemExit('Real-package smoke is restricted to GitHub-hosted Windows runners')
    import winreg
    programs = Path(os.environ['LOCALAPPDATA']) / 'Programs'
    if any((programs / name).exists() for name in ('VoxPlane', 'Voxenra', 'DICOMVision')):
        raise SystemExit('Refusing to change a pre-existing installation')
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{EA2DF9C6-5DC1-4CC3-913B-DB87DB5D0B5E}_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise SystemExit('Refusing to change a pre-existing installer registration')
    except FileNotFoundError:
        pass


@contextmanager
def isolated_preference_roots(paths):
    """Preserve earlier hosted-runner fixtures while each upgrade starts clean."""
    staged = []
    try:
        for path in paths:
            backup = None
            if path.exists():
                backup = path.with_name(path.name + '.upgrade-backup-' + uuid.uuid4().hex)
                path.rename(backup)
            staged.append((path, backup))
        yield
    finally:
        for path, backup in reversed(staged):
            if path.exists():
                shutil.rmtree(path)
            if backup is not None:
                # Do not delete the backup if restoration fails.
                backup.rename(path)


@contextmanager
def settings_sentinel():
    from PySide6.QtCore import QCoreApplication, QStandardPaths
    app = QCoreApplication.instance() or QCoreApplication([])
    paths = []
    for identity in ('Voxenra', 'VoxPlane'):
        app.setOrganizationName(identity)
        app.setApplicationName(identity)
        paths.append(Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)))
    # main() restricts this to a disposable GitHub-hosted Windows runner.
    # Earlier package checks may have created settings; preserve them exactly.
    old, new = paths
    path = old / 'display-settings.json'
    with isolated_preference_roots(paths):
        old.mkdir(parents=True, exist_ok=True)
        data = {'schemaVersion': 3, 'appearance': {'theme': 'graphite'}, 'updates': {'enabled': False}}
        path.write_text(json.dumps(data), encoding='utf-8')
        yield path, new / 'display-settings.json'


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


def stop_scoped_applications(root):
    cleanup = """
    $prefix = $env:VOXPLANE_SMOKE_ROOT + [IO.Path]::DirectorySeparatorChar
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
                   env=dict(os.environ, VOXPLANE_SMOKE_ROOT=str(root)))


def verify_upgrade(root, kind, old, new_package, settings, reports):
    folder = root / kind
    folder.mkdir()
    legacy = version_tuple(old.version) < (2, 6, 0)
    exe = folder / ('Voxenra.exe' if legacy else 'VoxPlane.exe')
    portable = kind == 'windows_portable'
    stage = root / (kind + '-update')
    stage.mkdir()
    log = reports / (kind + '.log')
    try:
        if portable:
            shutil.copyfile(root / old.name, exe)
        else:
            run_installer(root / old.name, '/SP-', '/NOCLOSEAPPLICATIONS', f'/DIR={folder}')

        fixture = folder / '升级 workspace'
        shutil.copytree(FIXTURES / 'v2.5.0', fixture)
        workspace = fixture / 'workspace.voxworkspace'
        workspace_data = workspace.read_bytes()
        health = root / kind / 'old-startup' / 'health.json'
        health.parent.mkdir()
        token = uuid.uuid4().hex
        health.write_text(json.dumps(dict(version=old.version, executable=str(exe), token=token)), encoding='utf-8')
        old_argument = '--voxenra-update-check' if legacy else '--voxplane-update-check'
        with subprocess.Popen([exe, old_argument, health], cwd=folder) as previous:
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
                if legacy:
                    # <=2.5 cannot accept renamed release assets: exercise the
                    # documented manual installation, not a fictitious old updater.
                    stop_tree(previous)
                    current = folder / 'VoxPlane.exe'
                    if portable:
                        shutil.copy2(candidate, current)
                    else:
                        run_installer(candidate, '/SP-', f'/DIR={folder}')
                    ready = stage / 'health.json'
                    ready.write_text(json.dumps(dict(version=__version__, executable=str(current),
                                                    token=token)), encoding='utf-8')
                    upgraded = subprocess.Popen([current, '--voxplane-update-check', ready], cwd=folder)
                    try:
                        deadline = time.monotonic() + 90
                        while not ready.with_name('ready').exists():
                            if upgraded.poll() is not None or time.monotonic() >= deadline:
                                raise RuntimeError('Renamed app failed startup confirmation')
                            time.sleep(.25)
                        assert ready.with_name('ready').read_text() == token
                        if portable:
                            exe.unlink()
                        assert not exe.exists(), 'Old executable was not retired'
                        (stage / 'result').write_text('success')
                    finally:
                        stop_tree(upgraded)
                else:
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
        for path in settings:
            prefs = json.loads(path.read_text(encoding='utf-8'))
            assert prefs['appearance']['theme'] == 'graphite' and prefs['updates']['enabled'] is False
        runtime_reports = reports / kind
        runtime_reports.mkdir(parents=True, exist_ok=True)
        # The update helper intentionally leaves the candidate running. Stop only
        # this isolated installation before another runtime reads its settings.
        stop_scoped_applications(folder)
        check_restored_workspace(folder / 'VoxPlane.exe', fixture, runtime_reports)
        assert workspace.read_bytes() == workspace_data, 'Restoring rewrote the original workspace'
        print(f'{kind} {old.version} → {__version__}: startup, settings and actual workspace '
              'restoration verified; old-client update button NOT exercised', flush=True)
        return {'status': 'passed', 'baseline': old.version, 'candidate': __version__,
                'installation': 'manual_brand_migration' if legacy else 'current_helper',
                'workspace_runtime': 'passed', 'settings': 'passed',
                'old_client_update_button': 'not_exercised'}
    finally:
        # The helper deliberately leaves the new app (or restored old app) running.
        stop_scoped_applications(root)
        setup_log = stage / 'setup.log'
        if setup_log.exists():
            shutil.copyfile(setup_log, reports / 'upgrade-setup.log')
        uninstall = folder / 'unins000.exe'
        if uninstall.is_file():
            run_installer(uninstall)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=FIXTURES / 'windows-baseline-v2.5.0.json')
    args = parser.parse_args(argv)
    require_clean_runner()
    reports = Path('build/test-results/installer').resolve()
    reports.mkdir(parents=True, exist_ok=True)
    result = {'status': 'failed', 'candidate': __version__, 'packages': {},
              'old_client_update_button': 'not_exercised'}
    try:
        metadata, releases = load_baseline(args.baseline, __version__)
        result.update(baseline=metadata['tag_name'], baseline_manifest_sha256=sha256(args.baseline))
        packages = {'windows_portable': Path('dist/VoxPlane.exe'),
                    'windows_installer': Path(f'dist/installers/VoxPlane-{__version__}-windows-x64-setup.exe')}
        for package in packages.values():
            if not package.is_file():
                raise FileNotFoundError(package)
        with temporary_upgrade_directory(os.environ['RUNNER_TEMP']) as root:
            for old in releases.values():
                subprocess.run(['gh', 'release', 'download', metadata['tag_name'], '--repo', REPOSITORY,
                                '--pattern', old.name, '--dir', root], check=True, timeout=240)
                download = root / old.name
                if download.stat().st_size != old.size or sha256(download) != old.digest:
                    raise ValueError(f'Previous package does not match pinned size and SHA-256: {old.name}')
            os.environ.pop('GH_TOKEN', None)
            # Keep one-file bootloader/setup temporary files in the disposable smoke directory.
            runtime_temp = root / 'runtime-temp'
            runtime_temp.mkdir()
            os.environ.update(TEMP=str(runtime_temp), TMP=str(runtime_temp))
            for kind, new in packages.items():
                result['packages'][kind] = {'status': 'failed'}
                with settings_sentinel() as settings:
                    result['packages'][kind] = verify_upgrade(root, kind, releases[kind], new, settings, reports)
        result['status'] = 'passed'
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        (reports / 'package-upgrade.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
