"""Contract tests against a real loopback HTTP DICOMweb server, with synthetic data."""
from __future__ import annotations

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

from voxplane.pacs.client import Cancelled, DicomWebClient, PacsError, study_filters
from voxplane.pacs.config import PacsConfigStore, PacsProfile
from voxplane.pacs.importer import import_series
from voxplane.ui.controller.pacs_controller import PacsController
from test_dicom_tags import qt_app, wait_until

STUDY = "1.2.826.0.1.3680043.10.999.10"
SERIES = STUDY + ".1"


def element(vr, *values):
    return {"vr": vr, "Value": list(values)}


def dicom_bytes(index):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = SERIES + f".{index}"
    ds = FileDataset("", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = STUDY, SERIES
    ds.PatientName, ds.PatientID = "DEMO^PATIENT", "PACS-DEMO"
    ds.StudyDescription, ds.SeriesDescription = "PACS synthetic study", "Axial CT"
    ds.Modality, ds.StudyDate, ds.SeriesNumber, ds.InstanceNumber = "CT", "20260906", 1, index
    ds.Rows, ds.Columns = 32, 32
    ds.PixelSpacing, ds.ImagePositionPatient, ds.ImageOrientationPatient = [1, 1], [0, 0, index], [1, 0, 0, 0, 1, 0]
    ds.SliceThickness, ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
    ds.PixelData = (np.arange(1024, dtype=np.uint16).reshape(32, 32) + index).tobytes()
    output = io.BytesIO()
    ds.save_as(output, enforce_file_format=True)
    return output.getvalue()


class FakePacs:
    def __init__(self):
        self.requests = []
        self.expected_auth = None
        self.error_status = None
        self.html = False
        self.malformed = False
        self.empty = False
        self.cap = 200
        self.ignore_offset = False
        self.truncated = False
        self.wrong_uid = False
        self.raw = False
        self.delay = False
        self.disconnect = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.study_rows = [{"0020000D": element("UI", STUDY), "00100010": element("PN", {"Alphabetic": "DEMO^PATIENT"}),
                            "00100020": element("LO", "PACS-DEMO"), "00080020": element("DA", "20260906"),
                            "00081030": element("LO", "PACS synthetic study"), "00080061": element("CS", "CT")}]
        self.series_rows = [{"0020000E": element("UI", SERIES), "0008103E": element("LO", "Axial CT"),
                             "00080060": element("CS", "CT"), "00200011": element("IS", 1), "00201209": element("IS", 3)}]
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append((self.path, dict(self.headers)))
                if outer.disconnect:
                    self.close_connection = True
                    return
                if outer.delay:
                    outer.entered.set()
                    outer.release.wait(5)
                if outer.expected_auth is not None and self.headers.get("Authorization") != outer.expected_auth:
                    self.send(401, b"secret server detail", "text/plain")
                    return
                if outer.error_status:
                    self.send(outer.error_status, b"private error body", "text/plain")
                    return
                if outer.html:
                    self.send(200, b"<html>Login</html>", "text/html")
                    return
                if outer.malformed:
                    self.send(200, b'{"bad": 1}', "application/dicom+json")
                    return
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                if parts.path.endswith("/studies"):
                    rows = outer.study_rows
                elif parts.path.endswith("/series"):
                    rows = outer.series_rows
                elif parts.path.endswith("/instances"):
                    rows = [{"00080018": element("UI", SERIES + f".{i}")} for i in range(1, 4)]
                else:
                    index = int(parts.path.rsplit(".", 1)[-1])
                    data = dicom_bytes(9 if outer.wrong_uid else index)
                    if outer.raw:
                        self.send(200, data, "application/dicom")
                        return
                    boundary = b"pacs-boundary"
                    body = b"--" + boundary + b"\r\nContent-Type: application/dicom\r\n\r\n" + data
                    if not outer.truncated:
                        body += b"\r\n--" + boundary + b"--\r\n"
                    self.send(200, body, 'multipart/related; type="application/dicom"; boundary="pacs-boundary"')
                    return
                offset = 0 if outer.ignore_offset else int(query.get("offset", ["0"])[0])
                limit = min(outer.cap, int(query.get("limit", ["200"])[0]))
                rows = [] if outer.empty else rows[offset:offset + limit]
                self.send(204 if not rows else 200, json.dumps(rows).encode() if rows else b"", "application/dicom+json")

            def send(self, code, body, content_type):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/dicom-web"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def pacs_server():
    server = FakePacs()
    try:
        yield server
    finally:
        server.close()


def profile(server, **kwargs):
    return PacsProfile.from_dict({"name": "Orthanc Local", "url": server.url, **kwargs})


@pytest.fixture
def controller(qt_app, tmp_path):
    result = PacsController(config_path=tmp_path / "pacs.json", import_root=tmp_path / "imports")
    yield result
    result.shutdown()


@pytest.mark.parametrize("address", ["host:8042", "ftp://server/path", "https://user:pass@host/", "http://host?q=token", "http://host/#fragment", "http://host:0", "http://host:99999", "http://host/\r\n"])
def test_profile_rejects_invalid_address(address):
    # Internal whitespace/control characters must never become request headers.
    if address.endswith("\r\n"):
        address = "http://ho\r\nst/"
    with pytest.raises(ValueError):
        PacsProfile.from_dict({"name": "PACS", "url": address})


def test_settings_persist_without_secrets_and_default_recovery(controller, tmp_path, pacs_server):
    assert controller.saveProfile({"name": "Clinic", "url": pacs_server.url, "auth": "basic", "username": "user", "secret": "private-password"})
    first = controller.profiles[0]["id"]
    assert controller.saveProfile({"name": "Backup", "url": pacs_server.url})
    second = controller.profiles[1]["id"]
    controller.setDefault(second)
    controller.setProfileEnabled(second, False)
    assert controller.defaultName == "Clinic"
    payload = (tmp_path / "pacs.json").read_text()
    assert "private-password" not in payload and "secret" not in payload
    assert "private-password" not in repr(controller._profile(first))
    profiles, default, local, pacs = PacsConfigStore(tmp_path / "pacs.json").load()
    assert default == first and local and pacs and not profiles[0].secret
    controller.setSources(False, False)
    assert controller.localEnabled and controller.pacsEnabled and controller.isError
    controller.setSources(False, True)
    assert not controller.localEnabled
    controller.deleteProfile(first)
    assert not controller.enabledProfiles and controller.selectedProfileId == ""
    assert not controller.saveProfile({"name": "Backup", "url": pacs_server.url})


def test_bad_config_file_is_not_rewritten(tmp_path):
    path = tmp_path / "pacs.json"
    path.write_text("broken")
    with pytest.raises(ValueError):
        PacsConfigStore(path).load()
    assert path.read_text() == "broken"


def test_connection_and_query_encode_filters_and_support_server_page_cap(pacs_server):
    client = DicomWebClient(profile(pacs_server))
    assert "连接成功" in client.test_connection()
    pacs_server.cap = 1
    pacs_server.study_rows += [{"0020000D": element("UI", STUDY + ".2")}]
    result = client.studies({"PatientName": "张*", "PatientID": "A&B", "dateFrom": "2026-01-01", "dateTo": "2026-09-06", "ModalitiesInStudy": "CT"}, 0, 20)
    assert len(result) == 2 and result[0]["patientName"] == "DEMO PATIENT"
    query = parse_qs(urlsplit(pacs_server.requests[1][0]).query)
    assert query["PatientName"] == ["张*"] and query["PatientID"] == ["A&B"]
    assert query["StudyDate"] == ["20260101-20260906"]
    assert client.series(STUDY, 0, 20)[0]["instances"] == "3"
    assert len(client.instance_uids(STUDY, SERIES)) == 3
    assert pacs_server.requests[0][1]["Accept"] == "application/dicom+json"


@pytest.mark.parametrize("filters", [{"dateFrom": "2026-02-30"}, {"dateFrom": "2026-03-01", "dateTo": "2026-02-01"}])
def test_invalid_dates(filters):
    with pytest.raises(PacsError):
        study_filters(filters)


@pytest.mark.parametrize("auth", ["basic", "bearer"])
def test_http_authentication(pacs_server, auth):
    pacs_server.expected_auth = "Basic " + base64.b64encode(b"user:password").decode() if auth == "basic" else "Bearer password"
    with pytest.raises(PacsError, match="认证失败"):
        DicomWebClient(profile(pacs_server)).test_connection()
    assert "连接成功" in DicomWebClient(profile(pacs_server, auth=auth, username="user", secret="password")).test_connection()
    with pytest.raises(PacsError, match="本次会话"):
        DicomWebClient(profile(pacs_server, auth=auth, username="user")).test_connection()


@pytest.mark.parametrize("fault,match", [("html", "DICOM JSON"), ("malformed", "无效"), ("error_status", "HTTP 500")])
def test_bad_responses_are_reported_safely(pacs_server, fault, match):
    setattr(pacs_server, fault, 500 if fault == "error_status" else True)
    with pytest.raises(PacsError, match=match) as error:
        DicomWebClient(profile(pacs_server)).test_connection()
    assert "private error" not in str(error.value)


def test_empty_archive_is_connected(pacs_server):
    pacs_server.empty = True
    client = DicomWebClient(profile(pacs_server))
    assert "连接成功" in client.test_connection()
    assert client.studies({}, 0, 20) == []


@pytest.mark.parametrize("raw", [False, True])
def test_complete_series_import_and_pixels(pacs_server, tmp_path, raw):
    pacs_server.raw = raw
    client = DicomWebClient(profile(pacs_server))
    progress = []
    result = import_series(client, client.series(STUDY, 0, 20), tmp_path, lambda n, text: progress.append(n))
    assert len(result.snapshot.series) == 1 and result.snapshot.dicom_file_count == 3
    assert result.snapshot.series[0].series_instance_uid == SERIES
    assert progress[-1] == 1.0
    for index, instance in enumerate(result.snapshot.series[0].instances, 1):
        ds = pydicom.dcmread(instance.path)
        np.testing.assert_array_equal(ds.pixel_array, np.arange(1024).reshape(32, 32) + index)
    assert all('transfer-syntax=1.2.840.10008.1.2.1' in headers["Accept"] for path, headers in pacs_server.requests if "/instances/" in path)


@pytest.mark.parametrize("fault", ["truncated", "wrong_uid", "ignore_offset"])
def test_failed_import_leaves_no_partial_series(pacs_server, tmp_path, fault):
    client = DicomWebClient(profile(pacs_server))
    selection = client.series(STUDY, 0, 20)
    setattr(pacs_server, fault, True)
    with pytest.raises(PacsError):
        import_series(client, selection, tmp_path, lambda *_: None)
    assert list(tmp_path.iterdir()) == []


def test_cancel_after_first_instance_cleans_downloads(pacs_server, tmp_path):
    cancel = threading.Event()
    client = DicomWebClient(profile(pacs_server), cancel)
    def progress(value, message):
        if value > 0:
            cancel.set()
    with pytest.raises(Cancelled):
        import_series(client, client.series(STUDY, 0, 20), tmp_path, progress)
    assert list(tmp_path.iterdir()) == []


def test_controller_query_import_and_cancel_discard_stale_results(controller, pacs_server):
    assert controller.saveProfile({"name": "PACS", "url": pacs_server.url})
    controller.queryStudies({}, 20)
    wait_until(lambda: not controller.busy)
    assert len(controller.studies) == 1 and not controller.isError
    controller.selectStudy(STUDY)
    wait_until(lambda: not controller.busy)
    controller.selectAllSeries(True)
    received = []
    controller.imported.connect(received.append)
    controller.importSelected()
    wait_until(lambda: not controller.busy, 15000)
    assert len(received) == 1 and received[0].dicom_file_count == 3
    assert controller.selectedCount == 0 and "导入完成" in controller.message
    pacs_server.delay = True
    controller.queryStudies({}, 20)
    wait_until(pacs_server.entered.is_set)
    controller.cancel()
    pacs_server.release.set()
    wait_until(lambda: not controller.busy)
    assert not controller.studies and "取消" in controller.message


def test_edit_secret_is_retained_only_for_same_endpoint(controller, pacs_server):
    controller.saveProfile({"name": "PACS", "url": pacs_server.url, "auth": "bearer", "secret": "token"})
    row = controller.profiles[0]
    assert controller.saveProfile({**row, "secret": "", "name": "Renamed"})
    assert controller._profile(row["id"]).secret == "token"
    assert controller.saveProfile({**row, "secret": "", "url": "http://elsewhere/dicomweb"})
    assert not controller._profile(row["id"]).secret


def test_connection_status_changes_on_failure(controller, pacs_server):
    controller.saveProfile({"name": "PACS", "url": pacs_server.url})
    controller.testProfile(controller.profiles[0]["id"])
    wait_until(lambda: not controller.busy)
    assert controller.profiles[0]["status"] == "连接成功"
    pacs_server.error_status = 401
    controller.testProfile(controller.profiles[0]["id"])
    wait_until(lambda: not controller.busy)
    assert controller.isError and controller.profiles[0]["status"] == "连接失败"


def test_multipart_preserves_binary_boundary_prefixes_and_chunk_edges(tmp_path):
    from email.message import Message
    payload = b"DICOM binary\r\n--boundary-not-a-delimiter\x00" + b"X" * 65515 + b"\x00\r\n"
    response = b"--boundary\r\nContent-Type: application/dicom\r\n\r\n" + payload + b"\r\n--boundary--\r\n"
    headers = Message()
    headers["Content-Type"] = 'multipart/related; boundary="boundary"'
    client = DicomWebClient(PacsProfile.from_dict({"name": "PACS", "url": "http://localhost/dicom-web"}))
    output = io.BytesIO()
    client._extract_instance(io.BytesIO(response), headers, output)
    assert output.getvalue() == payload


def test_redirect_does_not_forward_credentials_to_other_origin():
    from urllib.request import Request
    from voxplane.pacs.client import _SameOriginRedirect
    redirect = _SameOriginRedirect()
    request = Request("https://pacs.example/dicomweb", headers={"Authorization": "Bearer private"})
    for target in ("http://pacs.example/dicomweb", "https://other.example/", "https://pacs.example:8443/"):
        with pytest.raises(PacsError, match="重定向"):
            redirect.redirect_request(request, None, 302, "Found", {}, target)
    forwarded = redirect.redirect_request(request, None, 302, "Found", {}, "https://pacs.example/dicomweb/")
    assert forwarded.get_header("Authorization") == "Bearer private"


def test_series_count_mismatch_does_not_import(pacs_server, tmp_path):
    client = DicomWebClient(profile(pacs_server))
    rows = client.series(STUDY, 0, 20)
    rows[0]["instances"] = "4"
    with pytest.raises(PacsError, match="数量"):
        import_series(client, rows, tmp_path, lambda *_: None)
    assert not list(tmp_path.iterdir())


def test_controller_pagination_clears_stale_selection(controller, pacs_server):
    pacs_server.study_rows = [{"0020000D": element("UI", STUDY + f".{i}")} for i in range(25)]
    controller.saveProfile({"name": "PACS", "url": pacs_server.url})
    controller.queryStudies({}, 20)
    wait_until(lambda: not controller.busy)
    assert controller.studyPage == 1 and len(controller.studies) == 20 and controller.hasStudyNext
    controller.selectStudy(controller.studies[0]["uid"])
    wait_until(lambda: not controller.busy)
    controller.selectAllSeries(True)
    assert controller.selectedCount == 1
    controller.changeStudyPage(1)
    wait_until(lambda: not controller.busy)
    assert controller.studyPage == 2 and len(controller.studies) == 5 and not controller.hasStudyNext
    assert not controller.series and not controller.selectedCount and not controller.selectedStudyUid
    controller.changeStudyPage(-1)
    wait_until(lambda: not controller.busy)
    assert controller.studyPage == 1 and len(controller.studies) == 20


def test_shutdown_discards_completed_import_before_gui_delivery(controller, pacs_server):
    controller.saveProfile({"name": "PACS", "url": pacs_server.url})
    controller.queryStudies({}, 20)
    wait_until(lambda: not controller.busy)
    controller.selectStudy(STUDY)
    wait_until(lambda: not controller.busy)
    controller.selectAllSeries(True)
    controller.importSelected()
    controller._pool.waitForDone()  # Deliberately do not pump queued GUI signals.
    assert controller.busy and list(controller._import_root.iterdir())
    controller.shutdown()
    assert not list(controller._import_root.iterdir())


def test_saving_tested_draft_keeps_connection_status(controller, pacs_server):
    draft = {"name": "PACS", "url": pacs_server.url}
    controller.testDraft(draft)
    wait_until(lambda: not controller.busy)
    assert controller.saveProfile(draft)
    assert controller.profiles[0]["status"] == "连接成功"


def test_remote_disconnect_becomes_user_facing_connection_error(pacs_server):
    pacs_server.disconnect = True
    with pytest.raises(PacsError, match="无法连接"):
        DicomWebClient(profile(pacs_server)).test_connection()
