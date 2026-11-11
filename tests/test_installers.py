"""安装器配置与失败路径回归；不替代各平台安装/卸载验收。"""

import importlib
import runpy
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def builders(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return (importlib.import_module("build_macos"),
            importlib.import_module("build_windows_installer"),
            importlib.import_module("packaging_utils"))


def test_macos_command_preserves_qml_and_vtk(builders):
    mac, _, _ = builders
    command = mac.pyinstaller_command(ROOT, ROOT / "build/installer assets", identity="Developer ID: Test")
    assert "--onedir" in command and "--windowed" in command
    assert "--osx-bundle-version" not in command
    assert command[command.index("--distpath") + 1] == str(ROOT / "dist/macos")
    assert command[command.index("--codesign-identity") + 1] == "Developer ID: Test"
    assert "vtkmodules.vtkRenderingVolumeOpenGL2" in command
    assert command.count("--icon") == 1
    assert command[command.index("--icon") + 1] == str(ROOT / "build/installer assets/app.icns")
    assert command[command.index("--additional-hooks-dir") + 1] == str(ROOT / "packaging/hooks")


def test_windows_installer_and_portable_outputs_are_separate(builders):
    _, win, utils = builders
    command = win.pyinstaller_command(ROOT, installer=True)
    assert "--onedir" in command and "--onefile" not in command
    assert command[command.index("--distpath") + 1] == str(ROOT / "dist/windows")
    compiler = ROOT / "Program Files/Inno Setup 6/ISCC.exe"
    command = win.installer_command(ROOT, compiler, ROOT / "build/installer assets")
    assert command[0] == str(compiler)
    assert f"/DAssetsDir={ROOT / 'build/installer assets'}" in command
    assert f"/DAppVersion={utils.app_version()}" in command


def test_invalid_version_is_rejected(builders, tmp_path):
    _, _, utils = builders
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.1.0/../bad"\n')
    with pytest.raises(ValueError):
        utils.app_version(tmp_path)


def test_missing_explicit_inno_compiler_does_not_fallback(builders, tmp_path):
    _, win, _ = builders
    with pytest.raises(FileNotFoundError, match="Inno Setup"):
        win.find_iscc(str(tmp_path / "missing.exe"))


def test_dmg_has_app_applications_link_and_instructions(builders, tmp_path):
    mac, _, _ = builders
    defines = {"app": str(tmp_path / "path with spaces/VoxPlane.app"),
               "icon": str(tmp_path / "app.icns"), "readme": str(tmp_path / "安装说明.txt")}
    settings = runpy.run_path(str(ROOT / "packaging/macos/dmg_settings.py"), init_globals={"defines": defines})
    assert settings["symlinks"] == {"Applications": "/Applications"}
    assert set(settings["icon_locations"]) == {"VoxPlane.app", "Applications", "安装说明.txt"}
    assert settings["show_toolbar"] is False
    assert settings["format"] == "ULMO" and settings["compression_level"] == 9
    command = mac.dmg_command(ROOT, ROOT / "build/assets", Path(defines["app"]), ROOT / "dist/test.dmg")
    assert f"app={defines['app']}" in command


@pytest.mark.parametrize("index,platform", [(0, "win32"), (1, "darwin")])
def test_wrong_platform_does_not_start_build(builders, monkeypatch, index, platform):
    builder = builders[index]
    monkeypatch.setattr(builder.sys, "platform", platform)
    monkeypatch.setattr(builder.subprocess, "run", lambda *a, **kw: pytest.fail("wrong host"))
    assert builder.main([]) == 1


def test_windows_compile_error_is_propagated(builders, monkeypatch):
    _, win, _ = builders
    monkeypatch.setattr(win.sys, "platform", "win32")
    monkeypatch.setattr(win.sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(win.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(win, "find_iscc", lambda _: Path("ISCC.exe"))
    monkeypatch.setattr(win, "prepare_assets", lambda _: ROOT / "build/assets")
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(7, command)
    monkeypatch.setattr(win.subprocess, "run", fail)
    assert win.main([]) == 7


def test_installer_is_per_user_and_does_not_delete_user_data():
    source = (ROOT / "packaging/windows/VoxPlane.iss").read_text()
    assert "PrivilegesRequired=lowest" in source
    assert "UsePreviousAppDir=yes" in source
    assert "Compression=lzma2/ultra64" in source
    assert "LZMAUseSeparateProcess=yes" in source
    assert r"DefaultDirName={localappdata}\Programs\VoxPlane" in source
    assert 'Type: filesandordirs; Name: "{app}\\_internal\\PySide6"' in source
    assert "[UninstallDelete]" not in source
    assert "skipifsilent" in source
    assert "ChineseSimplified.isl" in source
    assert "WizardStyle=modern dynamic" in source
    assert source.count('AppUserModelID: "com.junliu.voxplane"') == 2
    assert 'Type: files; Name: "{app}\\Voxenra.exe"' in source
    assert 'Type: files; Name: "{autoprograms}\\Voxenra.lnk"' in source
    assert 'Type: files; Name: "{autodesktop}\\Voxenra.lnk"' in source
    assert 'AppId={{EA2DF9C6-5DC1-4CC3-913B-DB87DB5D0B5E}' in source


def test_generated_icons_include_small_and_retina_images(builders, tmp_path):
    import shutil
    Image = pytest.importorskip("PIL.Image")
    _, _, utils = builders
    brand = "src/voxplane/qml/assets/brand/voxplane-mark.png"
    (tmp_path / brand).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / brand, tmp_path / brand)
    assets = utils.prepare_assets(tmp_path)
    with Image.open(assets / "app.ico") as icon:
        assert icon.ico.sizes() == {(s, s) for s in (16, 24, 32, 48, 64, 128, 256)}
        for size in icon.ico.sizes():
            frame = icon.ico.getimage(size).convert("RGBA")
            assert frame.getextrema()[3] == (0, 255)
    with Image.open(assets / "app.icns") as icon:
        assert (512, 512, 2) in icon.info["sizes"]
        icon.load()
        assert icon.size == (1024, 1024)
        assert icon.convert("RGBA").getextrema()[3] == (0, 255)
