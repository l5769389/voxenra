"""Bounded untrusted MIME parsing without a QML workspace."""
import json

import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication
from voxplane.ui.annotation_clipboard import MIME_TYPE, read_annotation
from test_dicom_tags import qt_app


@pytest.fixture
def parse(qt_app):
    def parse_raw(raw):
        mime = QMimeData()
        mime.setData(MIME_TYPE, raw)
        QGuiApplication.clipboard().setMimeData(mime)
        return read_annotation()
    yield parse_raw
    QGuiApplication.clipboard().clear()


@pytest.mark.parametrize("size, accepted", [(256 * 1024 - 1, True), (256 * 1024, True), (256 * 1024 + 1, False)])
def test_payload_byte_limit(parse, size, accepted):
    payload = {"version": 1, "kind": "length", "points": [[1, 2], [3, 4]]}
    raw = json.dumps(payload).encode()
    raw += b" " * (size - len(raw))
    assert len(raw) == size
    assert parse(raw) == (payload if accepted else None)


@pytest.mark.parametrize("raw", [b"", b"{", b'{"version": 1,}', b"\xff", b"[]", b"null"])
def test_malformed_raw_json_is_rejected(parse, raw):
    assert parse(raw) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10000001, -10000001])
@pytest.mark.parametrize("axis", [0, 1])
def test_nonfinite_or_excessive_coordinates_are_rejected(parse, value, axis):
    points = [[1, 2], [3, 4]]
    points[1][axis] = value
    assert parse(json.dumps({"version": 1, "kind": "length", "points": points}).encode()) is None


def test_finite_coordinate_boundary_is_accepted(parse):
    payload = {"version": 1, "kind": "length", "points": [[-10000000, 10000000], [0.25, -0.5]]}
    assert parse(json.dumps(payload).encode()) == payload
