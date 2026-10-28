from __future__ import annotations
from qt_dicom_viewer.i18n import message as _msg

import json
import os
import tempfile
import uuid
import ipaddress
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PacsProfile:
    id: str
    name: str
    url: str
    enabled: bool = True
    auth: str = "none"
    username: str = ""
    timeout: int = 15
    # Credentials belong to this session; never serialize them or include in repr.
    secret: str = field(default="", repr=False)
    protocol: str = "dicomweb"
    host: str = ""
    port: int = 104
    called_ae: str = ""
    calling_ae: str = "VOXENRA"
    listen_host: str = "127.0.0.1"
    listen_port: int = 11112

    @classmethod
    def from_dict(cls, data: dict) -> PacsProfile:
        name = str(data.get("name", "")).strip()
        url = str(data.get("url", "")).strip().rstrip("/")
        if not name:
            raise ValueError(_msg('text.0325'))
        protocol = str(data.get("protocol", "dicomweb"))
        if protocol not in ("dicomweb", "dimse"):
            raise ValueError(_msg('dimse.invalidProfile', field="protocol"))
        if protocol == "dimse":
            return cls._from_dimse(data, name)
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise ValueError(_msg('text.0326')) from None
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or any(c.isspace() or ord(c) < 32 for c in url)
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError(_msg('text.0327'))
        auth = str(data.get("auth", "none"))
        if auth not in ("none", "basic", "bearer"):
            raise ValueError(_msg('text.0328'))
        username = str(data.get("username", "")).strip()
        secret = str(data.get("secret", ""))
        if any(c in secret + username for c in "\r\n") or ":" in username:
            raise ValueError(_msg('text.0329'))
        if auth == "basic" and not username:
            raise ValueError(_msg('text.0330'))
        try:
            timeout = int(data.get("timeout", 15))
        except (TypeError, ValueError):
            raise ValueError(_msg('text.0331')) from None
        if not 3 <= timeout <= 120:
            raise ValueError(_msg('text.0331'))
        profile_id = str(data.get("id") or uuid.uuid4())
        try:
            uuid.UUID(profile_id)
        except ValueError:
            raise ValueError(_msg('text.0332')) from None
        return cls(profile_id, name, url, bool(data.get("enabled", True)), auth,
                   username, timeout, secret if auth != "none" else "")

    @classmethod
    def _from_dimse(cls, data, name):
        def integer(key, default, low, high):
            raw = data.get(key, default)
            if isinstance(raw, bool) or not re.fullmatch(r"[0-9]+", str(raw)):
                raise ValueError(_msg('dimse.invalidProfile', field=key))
            result = int(raw)
            if not low <= result <= high:
                raise ValueError(_msg('dimse.invalidProfile', field=key))
            return result

        def aet(key, default):
            result = str(data.get(key, default)).strip()
            if not 1 <= len(result) <= 16 or any(ord(c) < 32 or ord(c) > 126 or c == "\\" for c in result):
                raise ValueError(_msg('dimse.invalidProfile', field=key))
            return result

        host = str(data.get("host", "")).strip()
        if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
            raise ValueError(_msg('dimse.invalidProfile', field="host"))
        listen_host = str(data.get("listen_host", "127.0.0.1")).strip()
        try:
            ipaddress.IPv4Address(listen_host)
        except ValueError:
            raise ValueError(_msg('dimse.invalidProfile', field="listen_host")) from None
        identifier = str(data.get("id") or uuid.uuid4())
        try:
            uuid.UUID(identifier)
        except ValueError:
            raise ValueError(_msg('text.0332')) from None
        return cls(id=identifier, name=name, url="", enabled=bool(data.get("enabled", True)),
                   protocol="dimse", host=host, port=integer("port", 104, 1, 65535),
                   called_ae=aet("called_ae", ""), calling_ae=aet("calling_ae", "VOXENRA"),
                   listen_host=listen_host, listen_port=integer("listen_port", 11112, 1, 65535),
                   timeout=integer("timeout", 15, 3, 120))

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("secret")
        return data


class PacsConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> tuple[list[PacsProfile], str, bool, bool]:
        if not self.path.exists():
            return [], "", True, True
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != 1:
                raise ValueError("unsupported version")
            profiles = [PacsProfile.from_dict(row) for row in data["profiles"]]
            if len({p.id for p in profiles}) != len(profiles):
                raise ValueError("duplicate profile")
            enabled_ids = [p.id for p in profiles if p.enabled]
            default = data.get("defaultId", "")
            if default not in enabled_ids:
                default = next(iter(enabled_ids), "")
            local, pacs = bool(data.get("localEnabled", True)), bool(data.get("pacsEnabled", True))
            return profiles, default, local or not pacs, pacs
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(_msg('text.0333')) from exc

    def save(self, profiles: list[PacsProfile], default: str, local: bool, pacs: bool):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "profiles": [p.public_dict() for p in profiles],
                   "defaultId": default, "localEnabled": local, "pacsEnabled": pacs}
        fd, name = tempfile.mkstemp(prefix=".pacs-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
