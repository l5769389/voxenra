from __future__ import annotations
from voxplane.i18n import message as _msg

import base64
import json
import re
import socket
import ssl
import tempfile
from datetime import date
from email.message import Message
from email.parser import BytesHeaderParser
from http.client import HTTPException
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pydicom

from .config import PacsProfile


class PacsError(Exception):
    """A safe, user-facing error, without response bodies or credentials."""


class Cancelled(PacsError):
    pass


def check_cancel(cancel: Event):
    if cancel.is_set():
        raise Cancelled(_msg('text.0338'))


def uid(value: str) -> str:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", value) or len(value) > 64:
        raise PacsError(_msg('text.0339'))
    return value


def value(row: dict, tag: str) -> str:
    values = row.get(tag, {}).get("Value", [])
    if not values:
        return ""
    if isinstance(values[0], dict):
        return str(values[0].get("Alphabetic") or values[0].get("Ideographic")
                   or values[0].get("Phonetic") or "").replace("^", " ")
    return " / ".join(str(v) for v in values)


def study_filters(filters: dict) -> dict:
    result = {}
    for key in ("PatientName", "PatientID", "AccessionNumber", "ModalitiesInStudy",
                "StudyInstanceUID", "StudyDescription"):
        text = str(filters.get(key, "")).strip()
        if text:
            result[key] = text
    dates = []
    for key in ("dateFrom", "dateTo"):
        text = str(filters.get(key, "")).strip()
        try:
            dates.append(date.fromisoformat(text).strftime("%Y%m%d") if text else "")
        except ValueError:
            raise PacsError(_msg('text.0340')) from None
    if all(dates) and dates[0] > dates[1]:
        raise PacsError(_msg('text.0341'))
    if any(dates):
        result["StudyDate"] = "-".join(dates)
    return result


class _SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        def origin(parts):
            return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        if origin(before) != origin(after) or after.username or after.password:
            raise PacsError(_msg('text.0342'))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DicomWebClient:
    def __init__(self, profile: PacsProfile, cancel: Event | None = None):
        self.profile = profile
        self.cancel = cancel if cancel is not None else Event()
        self.opener = build_opener(_SameOriginRedirect())

    def _open(self, path: str, params: dict | None, accept: str):
        check_cancel(self.cancel)
        headers = {"Accept": accept, "Accept-Encoding": "identity"}
        if self.profile.auth != "none" and not self.profile.secret:
            raise PacsError(_msg('text.0343'))
        if self.profile.auth == "basic":
            encoded = base64.b64encode(f"{self.profile.username}:{self.profile.secret}".encode()).decode()
            headers["Authorization"] = "Basic " + encoded
        elif self.profile.auth == "bearer":
            headers["Authorization"] = "Bearer " + self.profile.secret
        url = self.profile.url + path + ("?" + urlencode(params, doseq=True) if params else "")
        try:
            return self.opener.open(Request(url, headers=headers), timeout=self.profile.timeout)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            messages = {401: _msg('text.0344'), 403: _msg('text.0345'),
                        404: _msg('text.0346'), 406: _msg('text.0347')}
            raise PacsError(messages.get(status, _msg('text.0348', value1=status))) from None
        except (URLError, HTTPException, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise PacsError(_msg('text.0349')) from None
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise PacsError(_msg('text.0350')) from None
            raise PacsError(_msg('text.0351')) from None

    def query(self, path: str, params: dict) -> list[dict]:
        with self._open(path, params, "application/dicom+json") as response:
            if response.status == 204:
                return []
            if response.status != 200:
                raise PacsError(_msg('text.0352', value1=response.status))
            if response.headers.get_content_type() not in ("application/dicom+json", "application/json"):
                raise PacsError(_msg('text.0353'))
            data = bytearray()
            while chunk := response.read(65536):
                check_cancel(self.cancel)
                data.extend(chunk)
                if len(data) > 32 * 1024 * 1024:
                    raise PacsError(_msg('text.0354'))
            try:
                result = json.loads(data)
                if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                    raise ValueError()
                # Validate the DICOM JSON shape before exposing it to the UI.
                for row in result:
                    if any(not isinstance(element, dict) or not isinstance(element.get("Value", []), list)
                           for element in row.values()):
                        raise ValueError()
                return result
            except (ValueError, TypeError):
                raise PacsError(_msg('text.0355')) from None

    def test_connection(self):
        rows = self.query("/studies", {"limit": 1})
        for row in rows:
            uid(value(row, "0020000D"))
        return _msg('text.0356')

    def _page(self, path: str, params: dict, offset: int, limit: int, identity_tag: str):
        rows, seen = [], set()
        while len(rows) < limit:
            page = self.query(path, {**params, "limit": limit - len(rows), "offset": offset + len(rows)})
            if not page:
                break
            if len(page) > limit - len(rows):
                raise PacsError(_msg('text.0357'))
            for row in page:
                identity = uid(value(row, identity_tag))
                if identity in seen:
                    raise PacsError(_msg('text.0358'))
                seen.add(identity)
            rows.extend(page)
        return rows

    def studies(self, filters: dict, offset: int, limit: int) -> list[dict]:
        rows = self._page("/studies", {**study_filters(filters),
                          "includefield": ["StudyDescription", "NumberOfStudyRelatedSeries"]},
                          offset, limit, "0020000D")
        return [{"uid": uid(value(row, "0020000D")), "patientName": value(row, "00100010"),
                 "patientId": value(row, "00100020"), "date": value(row, "00080020"),
                 "description": value(row, "00081030"), "modality": value(row, "00080061"),
                 "accession": value(row, "00080050"), "seriesCount": value(row, "00201206")}
                for row in rows]

    def series(self, study: str, offset: int, limit: int) -> list[dict]:
        rows = self._page(f"/studies/{uid(study)}/series",
                          {"includefield": ["SeriesDescription", "NumberOfSeriesRelatedInstances"]},
                          offset, limit, "0020000E")
        return [{"uid": uid(value(row, "0020000E")), "studyUid": study,
                 "description": value(row, "0008103E"), "modality": value(row, "00080060"),
                 "number": value(row, "00200011"), "instances": value(row, "00201209")}
                for row in rows]

    def instance_uids(self, study: str, series: str) -> list[str]:
        found, seen, offset = [], set(), 0
        while True:
            rows = self.query(f"/studies/{uid(study)}/series/{uid(series)}/instances",
                              {"limit": 200, "offset": offset})
            if not rows:
                break
            for row in rows:
                sop = uid(value(row, "00080018"))
                if sop in seen:
                    raise PacsError(_msg('text.0359'))
                seen.add(sop)
                found.append(sop)
            offset += len(rows)
            # Continue even after a short page: servers may impose their own cap.
            if offset > 100000:
                raise PacsError(_msg('text.0360'))
        if not found:
            raise PacsError(_msg('text.0361'))
        return found

    def download_instance(self, study: str, series: str, sop: str, target: Path):
        path = f"/studies/{uid(study)}/series/{uid(series)}/instances/{uid(sop)}"
        accept = 'multipart/related; type="application/dicom"; transfer-syntax=1.2.840.10008.1.2.1'
        with self._open(path, None, accept) as response, tempfile.TemporaryFile() as spool:
            if response.status != 200:
                raise PacsError(_msg('text.0362'))
            total = 0
            while chunk := response.read(65536):
                check_cancel(self.cancel)
                spool.write(chunk)
                total += len(chunk)
            expected = response.headers.get("Content-Length")
            if expected is not None and total != int(expected):
                raise PacsError(_msg('text.0363'))
            spool.seek(0)
            with target.open("wb") as output:
                content_type = response.headers.get_content_type()
                if content_type == "application/dicom":
                    while chunk := spool.read(65536):
                        check_cancel(self.cancel)
                        output.write(chunk)
                elif content_type == "multipart/related":
                    self._extract_instance(spool, response.headers, output)
                else:
                    raise PacsError(_msg('text.0364'))
        check_cancel(self.cancel)
        try:
            ds = pydicom.dcmread(target, stop_before_pixels=True)
            if (str(ds.StudyInstanceUID), str(ds.SeriesInstanceUID), str(ds.SOPInstanceUID)) != (study, series, sop):
                raise PacsError(_msg('text.0365'))
            if str(ds.file_meta.MediaStorageSOPInstanceUID) != sop:
                raise PacsError(_msg('text.0366'))
        except (AttributeError, ValueError, OSError, pydicom.errors.InvalidDicomError):
            raise PacsError(_msg('text.0367')) from None

    def _extract_instance(self, spool, headers: Message, output):
        boundary = headers.get_param("boundary")
        if not boundary or len(boundary) > 200:
            raise PacsError(_msg('text.0368'))
        try:
            delimiter = b"--" + boundary.encode("ascii")
        except UnicodeError:
            raise PacsError(_msg('text.0369')) from None
        # Bound preamble and header reads. Pixel data is always copied in chunks.
        for _ in range(64):
            line = spool.readline(8192)
            if line.rstrip(b"\r\n") == delimiter:
                break
            if not line:
                raise PacsError(_msg('text.0370'))
        else:
            raise PacsError(_msg('text.0371'))
        part_headers = bytearray()
        while True:
            line = spool.readline(8192)
            part_headers.extend(line)
            if len(part_headers) > 65536 or not line:
                raise PacsError(_msg('text.0371'))
            if line in (b"\r\n", b"\n"):
                break
        if BytesHeaderParser().parsebytes(bytes(part_headers)).get_content_type() != "application/dicom":
            raise PacsError(_msg('text.0372'))
        marker = b"\r\n" + delimiter
        buffer = b""
        while True:
            check_cancel(self.cancel)
            chunk = spool.read(65536)
            buffer += chunk
            match = re.search(re.escape(marker) + br"(--|\r\n)", buffer)
            if match:
                if match.group(1) == b"--":
                    output.write(buffer[:match.start()])
                    return
                raise PacsError(_msg('text.0373'))
            if not chunk:
                raise PacsError(_msg('text.0374'))
            keep = len(marker) + 4
            if len(buffer) > keep:
                output.write(buffer[:-keep])
                buffer = buffer[-keep:]
