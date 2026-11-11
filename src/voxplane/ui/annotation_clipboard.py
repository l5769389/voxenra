"""Versioned, bounded geometry clipboard; no patient identifiers or cached metrics."""

import json
import math

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QColor, QGuiApplication

MIME_TYPE = "application/x-voxplane-annotation+json"
LEGACY_MIME_TYPE = "application/x-voxenra-annotation+json"
MAX_BYTES = 256 * 1024


def write_annotation(payload):
    mime = QMimeData()
    mime.setData(
        MIME_TYPE, json.dumps(dict(payload, version=1), allow_nan=False).encode("utf-8")
    )
    QGuiApplication.clipboard().setMimeData(mime)


def read_annotation():
    mime = QGuiApplication.clipboard().mimeData()
    if mime is None:
        return None
    kind = next((name for name in (MIME_TYPE, LEGACY_MIME_TYPE) if mime.hasFormat(name)), None)
    if kind is None:
        return None
    raw = bytes(mime.data(kind))
    if len(raw) > MAX_BYTES:
        return None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return None
        kind = payload.get("kind")
        if kind not in ("length", "angle", "rect", "ellipse", "curve", "freehand", "arrow", "text"):
            return None
        points = payload.get("points")
        if not isinstance(points, list) or (not 3 <= len(points) <= 4096 if kind in ("freehand", "curve") else len(points) != (3 if kind == "angle" else 2)):
            return None
        if any(
            not isinstance(p, list)
            or len(p) != 2
            or any(
                type(v) not in (int, float) or abs(v) > 1e7 or not math.isfinite(v)
                for v in p
            )
            for p in points
        ):
            return None
        if "smooth" in payload and not isinstance(payload["smooth"], bool):
            return None
        if kind == "text":
            if (
                not isinstance(payload.get("text"), str)
                or len(payload["text"]) > 200
                or not isinstance(payload.get("color"), str)
                or not QColor(payload["color"]).isValid()
                or type(payload.get("fontSize")) is not int
                or not 10 <= payload["fontSize"] <= 48
            ):
                return None
        return payload
    except (ValueError, TypeError, RecursionError):
        return None
