"""Native updater integration against tiny disposable apps, never the installed app."""
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time

import pytest

from voxplane.core.app_updates import Installation, Release
from voxplane.infrastructure.update_installer import prepare_installer, launch_installer


def release(name, version='1.7.0'):
    return Release(version, '', name, '', '', 1, '')


def test_scripts_quote_paths_and_do_not_execute_release_notes(tmp_path):
    target = tmp_path / "My app's $(touch NOT_ALLOWED).app"
    target.mkdir()
    package = tmp_path / 'update.dmg'
    package.write_bytes(b'test')
    command = prepare_installer(Installation('macos', target), release(package.name), package, 'a'*64, pid=2147483647)
    assert command[0] == '/bin/sh'
    script = Path(command[1]).read_text()
    assert '/usr/bin/codesign --verify --deep --strict' in script
    assert script.index('while kill -0') < script.index('/bin/mv "$target" "$backup"')
    if sys.platform != 'win32':
        subprocess.run(['/bin/sh', '-n', command[1]], check=True)


def test_detached_helper_uses_fresh_pyinstaller_environment(tmp_path, monkeypatch):
    import json
    bundle = tmp_path / 'old-bundle'
    bundle.mkdir()
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setenv('PATH', str(bundle) + os.pathsep + os.environ.get('PATH', ''))
    code = 'import os,json; print(json.dumps({k:os.environ.get(k) for k in ["PATH","PYINSTALLER_RESET_ENVIRONMENT"]}))'
    log = tmp_path / 'helper.log'
    process = launch_installer([sys.executable, '-c', code], log)
    assert process.wait(timeout=15) == 0
    data = json.loads(log.read_text())
    assert data['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
    assert str(bundle) not in data['PATH'].split(os.pathsep)


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows PowerShell handoff')
def test_windows_helper_executes_after_launcher_exits(tmp_path):
    script = tmp_path / 'helper.ps1'
    marker = tmp_path / 'completed.txt'
    log = tmp_path / 'helper.log'
    script.write_text("""param([int]$Owner, [string]$Marker)
$ErrorActionPreference = 'Stop'
$parent = Get-Process -Id $Owner -ErrorAction SilentlyContinue
if ($parent) { $parent.WaitForExit() }
Set-Content -LiteralPath $Marker -Value 'completed' -Encoding ASCII
""", encoding='utf-8-sig')
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    parent_code = """import os, sys
from pathlib import Path
from voxplane.infrastructure.update_installer import launch_installer
shell, script, marker, log = sys.argv[1:]
launch_installer([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                  '-File', script, str(os.getpid()), marker], Path(log))
"""
    subprocess.run([sys.executable, '-c', parent_code, str(shell), str(script), str(marker), str(log)],
                   check=True, timeout=30)
    deadline = time.monotonic() + 20
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    assert marker.exists(), log.read_text(errors='replace')
    assert marker.read_text().strip() == 'completed'


@pytest.mark.skipif(sys.platform != 'darwin', reason='Native macOS DMG and app replacement')
@pytest.mark.parametrize('failure', ['', 'checksum', 'replace', 'startup', 'timeout'])
def test_macos_real_dmg_update_and_failure_preserves_original(tmp_path, failure):
    def app_at(path, version):
        (path / 'Contents/MacOS').mkdir(parents=True)
        if version == '1.6.0' or failure == 'startup':
            shutil.copyfile('/usr/bin/false' if failure == 'startup' and version == '1.7.0' else '/usr/bin/true',
                            path / 'Contents/MacOS/VoxPlane')
        else:
            source_code = tmp_path / 'probe.c'
            source_code.write_text(r'''#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 3) return 1;
    FILE *f = fopen(argv[2], "r"); char data[16384] = {0};
    if (!f) return 1; fread(data, 1, sizeof(data)-1, f); fclose(f);
    char *p = strstr(data, "\"token\": \""); if (!p) return 1;
    char token[33] = {0}; memcpy(token, p + 10, 32);
    char path[16384]; strcpy(path, argv[2]); strcpy(strrchr(path, '/') + 1, "ready");
    ACKNOWLEDGE
    sleep(5); return 0;
}'''.replace('ACKNOWLEDGE', 'sleep(30);' if failure == 'timeout' else
                'f=fopen(path,"w"); if(!f) return 1; fputs(token,f); fclose(f);'))
            subprocess.run(['/usr/bin/clang', str(source_code), '-o', str(path / 'Contents/MacOS/VoxPlane')],
                           check=True, capture_output=True)
        (path / 'Contents/MacOS/VoxPlane').chmod(0o755)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
            CFBundleIdentifier='com.junliu.voxplane', CFBundleExecutable='VoxPlane',
            CFBundleName='VoxPlane', CFBundlePackageType='APPL', CFBundleShortVersionString=version)))
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True, capture_output=True)
    target = tmp_path / "Applications with space's" / 'VoxPlane.app'
    app_at(target, '1.6.0')
    source = tmp_path / 'dmg-source' / 'VoxPlane.app'
    app_at(source, '1.7.0')
    stage = tmp_path / 'update-test'
    stage.mkdir()
    package = stage / 'VoxPlane-1.7.0-macos-arm64.dmg'
    subprocess.run(['/usr/bin/hdiutil', 'create', '-srcfolder', str(source.parent), '-volname', 'VoxPlaneUpdateTest',
                    '-format', 'UDZO', str(package)], check=True, capture_output=True, timeout=60)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    command = prepare_installer(Installation('macos', target), release(package.name), package,
                                '0' * 64 if failure == 'checksum' else digest, pid=2147483647)
    if failure == 'timeout':
        script = Path(command[1])
        script.write_text(script.read_text().replace('health_timeout=60', 'health_timeout=3'))
    if failure == 'replace':
        script = Path(command[1])
        script.write_text(script.read_text().replace('/bin/mv "$fresh" "$target"', 'false # inject rename failure'))
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    log = result.stdout + result.stderr
    assert result.returncode == (1 if failure else 0), log
    assert (stage / 'result').read_text() == ('failed' if failure else 'success'), log
    metadata = plistlib.loads((target / 'Contents/Info.plist').read_bytes())
    assert metadata['CFBundleShortVersionString'] == ('1.6.0' if failure else '1.7.0'), log
    assert not package.exists()
    assert not list(target.parent.glob('.voxplane-backup-*'))


def windows_ready_app(stage, target):
    source = r'''using System; using System.IO; using System.Text.RegularExpressions;
class ReadyApp { static int Main(string[] args) {
    if (args.Length != 2 || args[0] != "--voxplane-update-check") return 1;
    string json = File.ReadAllText(args[1]);
    string token = Regex.Match(json, "[a-f0-9]{32}").Value;
    File.WriteAllText(Path.Combine(Path.GetDirectoryName(args[1]), "ready"), token);
    System.Threading.Thread.Sleep(5000); return 0;
}}'''
    script = stage / 'ready-app.ps1'
    script.write_text("Add-Type -TypeDefinition @'\n" + source + "\n'@ -OutputAssembly '" +
                      str(target).replace("'", "''") + "' -OutputType ConsoleApplication\n", encoding='utf-8-sig')
    shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                   check=True, capture_output=True)


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows PowerShell replacement')
@pytest.mark.parametrize('wrong_digest', [False, True])
def test_windows_portable_update_and_recovery(tmp_path, wrong_digest):
    target = tmp_path / 'Portable with spaces' / 'VoxPlane.exe'
    target.parent.mkdir()
    # where.exe exits harmlessly without arguments and is present on supported Windows.
    executable = Path(os.environ['SystemRoot']) / 'System32/where.exe'
    shutil.copy2(executable, target)
    original = target.read_bytes()
    stage = tmp_path / 'update-test'
    stage.mkdir()
    package = stage / 'VoxPlane-1.7.0-windows-x64-portable.exe'
    windows_ready_app(stage, package)
    # An overlay differentiates new/old files while preserving a runnable PE.
    with package.open('ab') as stream: stream.write(b'new version')
    new = package.read_bytes()
    digest = hashlib.sha256(new).hexdigest()
    command = prepare_installer(Installation('windows_portable', target), release(package.name), package,
                                '0' * 64 if wrong_digest else digest, pid=2147483647)
    log = stage / 'helper.log'
    with launch_installer(command, log) as helper:
        assert helper.wait(timeout=60) == (1 if wrong_digest else 0), log.read_text(errors='replace')
    assert target.read_bytes() == (original if wrong_digest else new)
    assert (stage / 'result').read_text().strip() == ('failed' if wrong_digest else 'success')


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows installer handoff and rollback')
@pytest.mark.parametrize('failure', [False, True])
def test_windows_installer_exit_code_and_backup_restore(tmp_path, failure):
    target = tmp_path / "Installed app's directory"
    target.mkdir()
    native = Path(os.environ['SystemRoot']) / 'System32/where.exe'
    shutil.copy2(native, target / 'VoxPlane.exe')
    (target / 'version.txt').write_text('old')
    stage = tmp_path / 'update-test'
    stage.mkdir()
    package = stage / 'setup.exe'
    ready_app = stage / 'ready-app.exe'
    windows_ready_app(stage, ready_app)
    # Compile a tiny stand-in that accepts Inno's /DIR argument, changes one
    # application file, then returns success/failure. Production still runs Inno.
    source = '''using System; using System.IO; class Setup {
        static int Main(string[] args) {
            string dir = Array.Find(args, a => a.StartsWith("/DIR=")).Substring(5).Trim('"');
            File.WriteAllText(Path.Combine(dir, "version.txt"), "new");
            File.Copy(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ready-app.exe"), Path.Combine(dir, "VoxPlane.exe"), true);
            return EXITCODE;
        }
    }'''.replace('EXITCODE', '1' if failure else '0')
    build = stage / 'compile.ps1'
    build.write_text("Add-Type -TypeDefinition @'\n" + source + "\n'@ -OutputAssembly '" + str(package).replace("'", "''")
                     + "' -OutputType ConsoleApplication\n", encoding='utf-8-sig')
    shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(build)], check=True, capture_output=True)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    command = prepare_installer(Installation('windows_installer', target), release(package.name), package, digest, pid=2147483647)
    log = stage / 'helper.log'
    with launch_installer(command, log) as helper:
        assert helper.wait(timeout=60) == (1 if failure else 0), log.read_text(errors='replace')
    assert (target / 'version.txt').read_text() == ('old' if failure else 'new')
    assert (target / 'VoxPlane.exe').read_bytes() == (native.read_bytes() if failure else ready_app.read_bytes())
    assert (stage / 'result').read_text().strip() == ('failed' if failure else 'success')
