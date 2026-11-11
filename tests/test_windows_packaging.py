"""验证打包参数、平台保护和无控制台日志；不替代 Windows 真机验收。"""

from __future__ import annotations

import importlib.util
import io
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from voxplane.infrastructure import logging_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_windows", PROJECT_ROOT / "scripts" / "build_windows.py"
)
build_windows = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    spec.loader.exec_module(build_windows)
finally:
    sys.path.pop(0)


@pytest.mark.parametrize('fail', [False, True])
def test_upgrade_smoke_isolates_and_restores_prior_test_preferences(tmp_path, fail):
    from manual import verify_windows_package_updates as smoke
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir(); new.mkdir()
    (old / 'settings.json').write_bytes(b'old original')
    (new / 'settings.json').write_bytes(b'prior test original')
    for _ in range(2):
        try:
            with smoke.isolated_preference_roots((old, new)):
                assert not old.exists() and not new.exists()
                old.mkdir(); new.mkdir()
                (old / 'settings.json').write_bytes(b'sentinel')
                (new / 'settings.json').write_bytes(b'migrated')
                if fail:
                    raise RuntimeError('simulated upgrade failure')
        except RuntimeError as error:
            assert fail and str(error) == 'simulated upgrade failure'
        assert (old / 'settings.json').read_bytes() == b'old original'
        assert (new / 'settings.json').read_bytes() == b'prior test original'
        assert sorted(p.name for p in tmp_path.iterdir()) == ['new', 'old']


def test_upgrade_smoke_removes_only_its_new_preferences(tmp_path):
    from manual import verify_windows_package_updates as smoke
    root = tmp_path / 'new'
    with smoke.isolated_preference_roots((root,)):
        root.mkdir()
        (root / 'settings.json').write_bytes(b'sentinel')
    assert not root.exists()


@pytest.mark.parametrize('locked_attempts', [0, 2])
def test_upgrade_smoke_waits_for_temporary_file_locks(tmp_path, monkeypatch, locked_attempts):
    from manual import verify_windows_package_updates as smoke
    original_cleanup = smoke.TemporaryDirectory.cleanup
    attempts = []

    def cleanup(directory):
        attempts.append(directory.name)
        if len(attempts) <= locked_attempts:
            raise PermissionError('Uninstaller is releasing its temporary file')
        original_cleanup(directory)

    monkeypatch.setattr(smoke.TemporaryDirectory, 'cleanup', cleanup)
    monkeypatch.setattr(smoke.time, 'sleep', lambda _: None)
    with smoke.temporary_upgrade_directory(tmp_path) as folder:
        (folder / 'runtime.tmp').write_text('temporary')
    assert len(attempts) == locked_attempts + 1
    assert not folder.exists()


def test_upgrade_smoke_reports_persistent_cleanup_failure(tmp_path, monkeypatch):
    from manual import verify_windows_package_updates as smoke

    def cleanup():
        raise PermissionError('Still locked')

    directory = SimpleNamespace(name=str(tmp_path), cleanup=cleanup)
    monkeypatch.setattr(smoke, 'TemporaryDirectory', lambda **_: directory)
    clock = iter([0, 31])
    monkeypatch.setattr(smoke.time, 'monotonic', lambda: next(clock, 31))
    with pytest.raises(PermissionError, match='Still locked'):
        with smoke.temporary_upgrade_directory(tmp_path):
            pass


def test_onefile_build_keeps_package_resource_layout() -> None:
    command = build_windows.pyinstaller_command(PROJECT_ROOT)

    assert "--onefile" in command
    assert "--windowed" in command
    assert "--console" not in command
    assert command[command.index("--name") + 1] == "VoxPlane"
    assert command[command.index("--additional-hooks-dir") + 1] == str(PROJECT_ROOT / "packaging/hooks")
    assert (PROJECT_ROOT / "packaging/hooks/hook-voxplane.py").is_file()
    assert command[-1] == str(PROJECT_ROOT / "scripts/windows_entry.py")
    assert command[command.index("--icon") + 1] == str(PROJECT_ROOT / "build/installer-assets/app.ico")
    assert {"PySide6.QtQuick", "PySide6.QtQuickControls2", "PySide6.QtSvg"} <= set(command)
    assert {
        "vtkmodules.qt.QVTKRenderWindowInteractor", "vtkmodules.vtkRenderingOpenGL2",
        "vtkmodules.vtkRenderingVolumeOpenGL2", "vtkmodules.vtkRenderingFreeType",
        "vtkmodules.vtkInteractionStyle",
    } <= set(command)
    assert (
        PROJECT_ROOT
        / "src/voxplane/qml/sections/center/viewportArea/MontageViewport.qml"
    ).is_file()


def test_console_build_uses_separate_executable() -> None:
    command = build_windows.pyinstaller_command(PROJECT_ROOT, console=True)

    assert "--console" in command
    assert "--windowed" not in command
    assert command[command.index("--name") + 1] == "VoxPlane-debug"


def test_directory_portable_avoids_startup_extraction_and_installer_output() -> None:
    command = build_windows.pyinstaller_command(PROJECT_ROOT, portable_dir=True)
    assert "--onedir" in command and "--onefile" not in command
    assert command[command.index("--distpath") + 1] == str(PROJECT_ROOT / "dist/portable")
    installed = build_windows.pyinstaller_command(PROJECT_ROOT, installer=True)
    assert installed[installed.index("--distpath") + 1] == str(PROJECT_ROOT / "dist/windows")


def test_build_paths_do_not_depend_on_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    command = build_windows.pyinstaller_command(PROJECT_ROOT)

    assert command[command.index("--distpath") + 1] == str(PROJECT_ROOT / "dist")
    assert command[command.index("--paths") + 1] == str(PROJECT_ROOT / "src")


def test_incomplete_source_tree_is_rejected(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="QML"):
        build_windows.pyinstaller_command(tmp_path)


def test_non_windows_host_does_not_start_packager(monkeypatch, capsys) -> None:
    monkeypatch.setattr(build_windows.sys, "platform", "darwin")
    monkeypatch.setattr(
        build_windows.subprocess, "run",
        lambda *args, **kwargs: pytest.fail("非 Windows 环境不应执行打包"),
    )

    assert build_windows.main([]) == 1
    assert "Windows" in capsys.readouterr().err


@pytest.fixture
def simulated_windows(monkeypatch):
    monkeypatch.setattr(build_windows.sys, "platform", "win32")
    monkeypatch.setattr(build_windows.sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(build_windows.sys, "maxsize", 2**63 - 1)
    monkeypatch.setattr(build_windows.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(build_windows, "prepare_assets", lambda root: root / "build/installer-assets")


def test_build_failure_preserves_nonzero_exit_code(simulated_windows, monkeypatch) -> None:
    def failed_build(command, **kwargs):
        assert kwargs["check"] is True
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(build_windows.subprocess, "run", failed_build)

    assert build_windows.main([]) == 2


def test_success_without_output_is_reported_as_failure(
    simulated_windows, monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(build_windows, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build_windows, "pyinstaller_command", lambda *a, **kw: ["packager"])
    monkeypatch.setattr(build_windows.subprocess, "run", lambda *a, **kw: None)

    assert build_windows.main([]) == 1


def test_success_requires_expected_executable(simulated_windows, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(build_windows, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build_windows, "pyinstaller_command", lambda *a, **kw: ["packager"])

    def successful_build(*args, **kwargs):
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "VoxPlane.exe").touch()

    monkeypatch.setattr(build_windows.subprocess, "run", successful_build)

    assert build_windows.main([]) == 0


def test_directory_portable_checks_nested_executable(simulated_windows, monkeypatch, tmp_path):
    monkeypatch.setattr(build_windows, "PROJECT_ROOT", tmp_path)
    def command(root, **kwargs):
        assert kwargs["portable_dir"]
        return ["packager"]
    monkeypatch.setattr(build_windows, "pyinstaller_command", command)
    def build(*args, **kwargs):
        target = tmp_path / "dist/portable/VoxPlane/VoxPlane.exe"
        target.parent.mkdir(parents=True)
        target.touch()
    monkeypatch.setattr(build_windows.subprocess, "run", build)
    assert build_windows.main(["--portable-dir"]) == 0


@pytest.mark.parametrize("has_console", [False, True])
def test_logging_works_with_and_without_console(has_console, monkeypatch, tmp_path) -> None:
    console = io.StringIO() if has_console else None
    monkeypatch.setattr(logging_config.sys, "stdout", console)
    monkeypatch.setattr(logging_config.sys, "stderr", console)
    monkeypatch.setattr(logging_config, "QStandardPaths", SimpleNamespace(
        AppLocalDataLocation=0,
        writableLocation=lambda _: str(tmp_path),
    ))
    configuration = {}
    # 不修改 pytest 的根日志配置，只捕获待安装的处理器进行验证。
    monkeypatch.setattr(logging_config.logging, "basicConfig", lambda **kw: configuration.update(kw))

    log_path = logging_config.configure_logging()
    logger = logging.Logger("packaged-app")
    logger.handlers = configuration["handlers"]
    try:
        logger.warning("文件日志正常")
        assert "文件日志正常" in log_path.read_text(encoding="utf-8")
        assert len(logger.handlers) == (2 if has_console else 1)
        if has_console:
            assert "文件日志正常" in console.getvalue()
    finally:
        for handler in logger.handlers:
            handler.close()
