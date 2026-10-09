"""在本机架构的 macOS 上构建 .app 和带 Finder 安装界面的 DMG。"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from packaging_utils import APP_NAME, BUNDLE_ID, PROJECT_ROOT, app_version, prepare_assets
from macos_signing import preflight, notarize_app, notarize_dmg


def pyinstaller_command(root: Path, assets: Path, *, identity: str | None = None) -> list[str]:
    from build_windows import pyinstaller_command as base_command

    # 共用经过验证的 QML、Qt 插件、VTK 隐式导入清单。
    command = base_command(root, installer=True, icon=assets / "app.icns")
    command[command.index("--distpath") + 1] = str(root / "dist" / "macos")
    command[command.index("--workpath") + 1] = str(root / "build" / "macos" / APP_NAME)
    command[command.index("--specpath") + 1] = str(root / "build" / "macos")
    options = ["--osx-bundle-identifier", BUNDLE_ID,
               "--target-architecture", platform.machine(),
               "--codesign-identity", identity or "-"]
    return command[:-1] + options + command[-1:]


def dmg_command(root: Path, assets: Path, application: Path, output: Path) -> list[str]:
    return [sys.executable, "-m", "dmgbuild", "-s", str(root / "packaging/macos/dmg_settings.py"),
            "-D", f"app={application}", "-D", f"icon={assets / 'app.icns'}",
            "-D", f"readme={root / 'packaging/macos/安装说明.txt'}", APP_NAME, str(output)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-only", action="store_true", help="仅构建 .app，不生成 DMG。")
    parser.add_argument("--release", action="store_true", help="正式分发模式：必须具备 Developer ID 和公证配置，不允许退回测试签名。")
    parser.add_argument("--check-signing", action="store_true", help="仅检查证书和公证认证，不构建或上传应用。")
    parser.add_argument("--sign-identity", default=os.getenv("MACOS_SIGN_IDENTITY"),
                        help="钥匙串中的 Developer ID Application 身份；缺省为 ad-hoc 测试签名。")
    parser.add_argument("--notary-profile", default=os.getenv("MACOS_NOTARY_PROFILE"),
                        help="已保存的 notarytool 钥匙串配置名；提供时公证应用和 DMG 并装订票据。")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or platform.machine() not in {"arm64", "x86_64"}:
        print("请在 Apple Silicon 或 Intel Mac 上运行对应架构的 Python。", file=sys.stderr)
        return 1
    if sys.version_info[:2] != (3, 13) and not args.check_signing:
        print("请通过 bash scripts/build_macos.sh 使用 Python 3.13 构建。", file=sys.stderr)
        return 1
    if (args.release or args.check_signing) and (not args.sign_identity or args.sign_identity == "-" or not args.notary_profile):
        parser.error("正式签名检查需要 --sign-identity 和 --notary-profile。")
    if args.release and args.app_only:
        parser.error("正式分发需要生成 DMG，不能同时使用 --app-only。")
    if args.notary_profile and (not args.sign_identity or args.sign_identity == "-"):
        parser.error("公证需要 Developer ID 签名。")
    try:
        if args.sign_identity and args.sign_identity != "-":
            args.sign_identity = preflight(args.sign_identity, args.notary_profile)
        if args.check_signing:
            print("Developer ID 身份和 Apple 公证认证检查通过；尚未构建、签名或上传应用。")
            return 0
        assets = prepare_assets(PROJECT_ROOT)
        subprocess.run(pyinstaller_command(PROJECT_ROOT, assets, identity=args.sign_identity),
                       cwd=PROJECT_ROOT, check=True,
                       env={**os.environ, "PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR": "1"})
        application = PROJECT_ROOT / "dist/macos" / f"{APP_NAME}.app"
        if not (application / "Contents/MacOS" / APP_NAME).is_file():
            raise FileNotFoundError(f"没有生成预期应用：{application}")
        # PyInstaller 没有 bundle-version CLI 选项；修改构建产物后重新签署外层 bundle。
        plist_path = application / "Contents/Info.plist"
        with plist_path.open("rb") as stream:
            metadata = plistlib.load(stream)
        icon_name = metadata.get("CFBundleIconFile", "")
        if not icon_name or not (application / "Contents/Resources" / icon_name).is_file():
            raise FileNotFoundError("应用包缺少 Info.plist 声明的 ICNS 图标。")
        metadata.update(CFBundleShortVersionString=app_version(PROJECT_ROOT),
                        CFBundleVersion=app_version(PROJECT_ROOT),
                        CFBundleDisplayName=APP_NAME, CFBundleName=APP_NAME)
        with plist_path.open("wb") as stream:
            plistlib.dump(metadata, stream)
        signing = ["codesign", "--force", "--sign", args.sign_identity or "-"]
        if args.sign_identity and args.sign_identity != "-":
            signing += ["--options", "runtime", "--timestamp", "--preserve-metadata=entitlements"]
        subprocess.run(signing + [str(application)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(application)], check=True)
        print(f"应用：{application}")
        logs = PROJECT_ROOT / "build/macos/notarization" / f"{app_version(PROJECT_ROOT)}-{platform.machine()}"
        if args.notary_profile:
            notarize_app(application, args.notary_profile, logs)
        if args.app_only:
            return 0
        output = PROJECT_ROOT / "dist/installers" / f"{APP_NAME}-{app_version(PROJECT_ROOT)}-macos-{platform.machine()}.dmg"
        output.parent.mkdir(parents=True, exist_ok=True)
        # A rejected or interrupted notarization must not replace a distributable artifact.
        with TemporaryDirectory(prefix=".macos-build-", dir=output.parent) as temporary:
            staged = Path(temporary) / output.name
            subprocess.run(dmg_command(PROJECT_ROOT, assets, application, staged), cwd=PROJECT_ROOT, check=True)
            if not staged.is_file():
                raise FileNotFoundError(f"没有生成预期 DMG：{staged}")
            subprocess.run(["hdiutil", "verify", str(staged)], check=True)
            if args.notary_profile:
                notarize_dmg(staged, args.sign_identity, args.notary_profile, logs)
            elif args.sign_identity and args.sign_identity != "-":
                subprocess.run(["codesign", "--force", "--sign", args.sign_identity, "--timestamp", str(staged)], check=True)
            staged.replace(output)
        print(f"安装包：{output}")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"macOS 打包失败：{error}", file=sys.stderr)
        return error.returncode if isinstance(error, subprocess.CalledProcessError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
