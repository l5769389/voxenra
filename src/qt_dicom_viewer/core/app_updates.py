"""Release validation and installed-application detection, without UI or network I/O."""
from __future__ import annotations

from dataclasses import dataclass
import platform
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, unquote

REPOSITORY = "l5769389/voxenra"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
MAX_PACKAGE_SIZE = 2 * 1024**3


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Invalid stable version")
    return tuple(map(int, value.removeprefix("v").split(".")))


@dataclass(frozen=True)
class Installation:
    kind: str
    target: Path | None
    reason: str = ""


def detect_installation() -> Installation:
    if not getattr(sys, "frozen", False):
        return Installation("", None, "updates.development")
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        if executable.parent.name == "MacOS" and executable.parent.parent.name == "Contents":
            bundle = executable.parent.parent.parent
            if bundle.suffix == ".app":
                if str(bundle).startswith("/Volumes/") or "AppTranslocation" in bundle.parts:
                    return Installation("", None, "updates.moveApplication")
                return Installation("macos", bundle)
    if sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}:
        if executable.name.lower() == "voxenra.exe":
            if (executable.parent / "unins000.exe").is_file():
                return Installation("windows_installer", executable.parent)
            # A directory portable build has no matching release archive. Do not
            # silently convert it into an installed or single-file application.
            if not (executable.parent / "_internal").is_dir():
                return Installation("windows_portable", executable)
    return Installation("", None, "updates.unsupported")


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    name: str
    url: str
    checksum_url: str
    size: int
    digest: str


def trusted_download_url(url: str, *, redirect=False) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if redirect:
            return parsed.hostname in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        return (parsed.hostname == "github.com"
                and unquote(parsed.path).startswith(f"/{REPOSITORY}/releases/download/"))
    except (ValueError, TypeError):
        return False


def parse_release(payload: dict, current: str, kind: str) -> Release | None:
    if not isinstance(payload, dict):
        raise ValueError("Invalid release response")
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix("v")
    suffix = {"macos": "macos-arm64.dmg", "windows_installer": "windows-x64-setup.exe",
              "windows_portable": "windows-x64-portable.exe"}.get(kind)
    notes = payload.get("body") or ""
    if not isinstance(notes, str):
        raise ValueError("Invalid release notes")
    if suffix is None:
        return Release(version, notes[:32000], "", "", "", 0, "")
    name = f"Voxenra-{version}-{suffix}"
    entries = payload.get("assets", [])
    if not isinstance(entries, list):
        raise ValueError("Invalid release assets")
    assets = {entry.get("name"): entry for entry in entries if isinstance(entry, dict)}
    asset, checksum = assets.get(name), assets.get(name + ".sha256")
    if not asset or not checksum or asset.get("state") != "uploaded" or checksum.get("state") != "uploaded":
        raise ValueError("Release assets are not ready")
    url, checksum_url = asset.get("browser_download_url", ""), checksum.get("browser_download_url", "")
    for address, filename in ((url, name), (checksum_url, name + ".sha256")):
        if (not trusted_download_url(address)
                or unquote(urlsplit(address).path) != f"/{REPOSITORY}/releases/download/{tag}/{filename}"):
            raise ValueError("Unexpected release download URL")
    size = asset.get("size", 0)
    if type(size) is not int or not 0 < size <= MAX_PACKAGE_SIZE:
        raise ValueError("Invalid package size")
    digest = asset.get("digest") or ""
    if digest and not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("Invalid release digest")
    return Release(version, notes[:32000], name, url, checksum_url, size, digest.removeprefix("sha256:").lower())


def parse_checksum(data: bytes, filename: str) -> str:
    text = data.decode("utf-8-sig").strip()
    match = re.fullmatch(r"([a-fA-F0-9]{64})(?:[ \t]+\*?([^\r\n]+))?", text)
    if not match or (match[2] is not None and match[2] != filename):
        raise ValueError("Invalid package checksum")
    return match[1].lower()
