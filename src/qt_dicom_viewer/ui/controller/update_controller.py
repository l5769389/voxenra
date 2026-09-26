"""Asynchronous release checking, streamed downloads, and an exit-safe handoff."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import shutil
import tempfile

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl, QStandardPaths, QSaveFile, QIODevice, QLockFile
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from qt_dicom_viewer import __version__
from qt_dicom_viewer.core.app_updates import RELEASE_API, RELEASE_PAGE, detect_installation, parse_release, parse_checksum, trusted_download_url
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property
from qt_dicom_viewer.infrastructure.update_installer import prepare_installer, launch_installer

logger = logging.getLogger(__name__)


class UpdateController(QObject):
    changed = Signal()
    showDialog = Signal()
    exitRequested = Signal()
    _i18n_message = Signal()

    def __init__(self, settings, parent=None, *, installation=None, network=None, cache=None, version=__version__):
        super().__init__(parent)
        self._settings = settings
        self._installation = installation or detect_installation()
        self._version = version
        self._network = network
        self._cache = Path(cache) if cache else Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "updates"
        self._release = None
        self._state = "idle"
        self._message = _msg("updates.idle")
        self._progress = 0.0
        self._reply = None
        self._file = None
        self._stage = None
        self._command = None
        self._lock = None
        self._manual = False
        self._closed = False
        self._started = False
        self._finishing = False
        self._session_dismissed = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._startup_check)
        try:
            cached = self._cache / "available.json"
            if cached.stat().st_size <= 1024 * 1024:
                self._release = parse_release(json.loads(cached.read_bytes()), self._version, self._installation.kind)
                if self._release:
                    self._state = "available"
                    self._message = _msg("updates.available", version=self.latestVersion)
        except (OSError, ValueError, TypeError, KeyError):
            pass

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(str, constant=True)
    def currentVersion(self): return self._version

    @Property(bool, notify=changed)
    def supportsInstallation(self): return bool(self._installation.kind)

    @Property(bool, notify=changed)
    def busy(self): return self._state in {"checking", "checksum", "downloading"}

    @Property(bool, notify=changed)
    def hasUpdate(self): return self._release is not None

    @Property(str, notify=changed)
    def latestVersion(self): return self._release.version if self._release else ""

    @Property(str, notify=changed)
    def releaseNotes(self): return self._release.notes if self._release else ""

    @Property(float, notify=changed)
    def progress(self): return self._progress

    @Property(bool, notify=changed)
    def canInstall(self):
        return bool(self._release and self._installation.kind and not self.busy)

    @Property(bool, notify=changed)
    def hasLog(self):
        return bool(self._stage and (self._stage / "install.log").is_file())

    @translated_property(str, notify=_i18n_message, notify_name="_i18n_message", source_notify="changed")
    def message(self): return self._message

    def _set_state(self, state, message):
        self._state, self._message = state, message
        self.changed.emit()

    def start(self):
        """Called once, only after the real application's first window loads."""
        if not self._started:
            self._started = True
            self._startup_timer.start(5000)

    @Slot()
    def _startup_check(self):
        if self._closed:
            return
        # A failed helper has already restored/restarted the old app. Keep its
        # log available without presenting another failure or upgrade prompt.
        try:
            record = json.loads((self._cache / "pending.json").read_text(encoding="utf-8"))
            name = record["directory"]
            if not isinstance(name, str) or not name.startswith("update-") or Path(name).name != name:
                raise ValueError("Invalid update directory")
            stage = self._cache / name
            result = (stage / "result").read_text(encoding="ascii").strip()
            (self._cache / "pending.json").unlink()
            if result == "failed":
                self._stage = stage
                self._settings.setValue("updates", "dismissedVersion", record.get("version", ""))
                self.changed.emit()
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self._settings.section("updates")["enabled"]:
            self._check(False)

    @Slot()
    def check(self): self._check(True)

    @Slot()
    def show(self): self.showDialog.emit()

    def _check(self, manual):
        if self.busy or self._state == "ready" or self._closed:
            if manual:
                self.showDialog.emit()
            return
        self._manual = manual
        self._set_state("checking", _msg("updates.checking"))
        self._get(RELEASE_API, "checking", 1024 * 1024)

    def _get(self, url, phase, limit):
        if self._network is None:
            self._network = QNetworkAccessManager(self)
        self._phase, self._limit = phase, limit
        self._buffer, self._received = bytearray(), 0
        self._request_failure, self._redirects = "", 0
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"Voxenra/{self._version}".encode("ascii"))
        request.setRawHeader(b"Accept", b"application/vnd.github+json" if phase == "checking" else b"application/octet-stream")
        request.setTransferTimeout(30000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.UserVerifiedRedirectPolicy)
        reply = self._network.get(request)
        self._reply = reply
        reply.setReadBufferSize(1024 * 1024)
        reply.readyRead.connect(lambda: self._read() if self._reply is reply else None)
        reply.redirected.connect(lambda url: self._redirect(url) if self._reply is reply else None)
        reply.finished.connect(lambda: self._finished() if self._reply is reply else None)
        self._timer.start(30 * 60 * 1000 if phase == "downloading" else 45000)

    def _redirect(self, url):
        self._redirects += 1
        valid = (url.toString() == RELEASE_API if self._phase == "checking"
                 else trusted_download_url(url.toString(), redirect=True))
        if not valid or self._redirects > 5:
            self._abort("updates.invalidDownload")
        elif self._reply:
            self._reply.redirectAllowed()

    @Slot()
    def _timeout(self): self._abort("updates.networkError")

    def _abort(self, key):
        self._request_failure = key
        if self._reply and not self._finishing:
            self._reply.abort()

    def _read(self):
        reply = self._reply
        if reply is None or self._request_failure:
            return
        try:
            while reply.bytesAvailable():
                chunk = bytes(reply.read(64 * 1024))
                if not chunk:
                    break
                self._received += len(chunk)
                if self._received > self._limit:
                    self._abort("updates.invalidDownload")
                    return
                if self._phase == "downloading":
                    self._file.write(chunk)
                    self._hash.update(chunk)
                    self._progress = self._received / self._limit
                else:
                    self._buffer.extend(chunk)
            if self._phase == "downloading":
                self.changed.emit()
        except OSError:
            self._abort("updates.storageError")

    def _finished(self):
        reply = self._reply
        if reply is None:
            return
        self._finishing = True
        self._read()
        self._finishing = False
        self._reply = None
        self._timer.stop()
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        failed = reply.error() != QNetworkReply.NoError or status != 200
        reply.deleteLater()
        if self._closed or self._request_failure == "cancelled":
            self._discard_download()
            return
        if self._request_failure or failed:
            self._fail(self._request_failure or "updates.networkError")
            return
        try:
            if self._phase == "checking":
                payload = json.loads(self._buffer)
                release = parse_release(payload, self._version, self._installation.kind)
                self._release = release
                # Keep the badge available offline and after an opted-out restart.
                try:
                    if release:
                        self._write_json(self._cache / "available.json", payload)
                    else:
                        (self._cache / "available.json").unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not cache release information", exc_info=True)
                if not release:
                    self._set_state("current", _msg("updates.current"))
                    return
                self._set_state("available", _msg(self._installation.reason) if self._installation.reason else _msg("updates.available", version=release.version))
                dismissed = self._settings.section("updates")["dismissedVersion"]
                if (self._manual or (release.version not in {dismissed, self._session_dismissed}
                        and self._settings.section("updates")["enabled"])):
                    self.showDialog.emit()
            elif self._phase == "checksum":
                self._digest = parse_checksum(bytes(self._buffer), self._release.name)
                if self._release.digest and self._release.digest != self._digest:
                    self._fail("updates.checksumError")
                    return
                self._file = (self._stage / self._release.name).open("xb")
                self._hash = hashlib.sha256()
                self._set_state("downloading", _msg("updates.downloading"))
                self._get(self._release.url, "downloading", self._release.size)
            else:
                self._file.close()
                self._file = None
                if self._received != self._release.size or self._hash.hexdigest() != self._digest:
                    self._fail("updates.checksumError")
                    return
                self._command = prepare_installer(self._installation, self._release,
                                                  self._stage / self._release.name, self._digest)
                self._save_pending()
                self._set_state("ready", _msg("updates.ready"))
                self.exitRequested.emit()
        except (ValueError, UnicodeError, TypeError, KeyError):
            logger.exception("Invalid update response")
            self._fail("updates.invalidDownload")
        except OSError:
            logger.exception("Cannot prepare application update")
            self._fail("updates.storageError")

    def _save_pending(self):
        self._write_json(self._cache / "pending.json", {"directory": self._stage.name, "version": self.latestVersion})

    @staticmethod
    def _write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        target = QSaveFile(str(path))
        payload = json.dumps(data).encode("utf-8")
        if not target.open(QIODevice.WriteOnly) or target.write(payload) != len(payload) or not target.commit():
            raise OSError("Could not save update state")

    @Slot()
    def install(self):
        if not self.canInstall or self._closed:
            return
        if self._state == "ready":
            self.exitRequested.emit()
            return
        try:
            self._cache.mkdir(parents=True, exist_ok=True)
            self._lock = QLockFile(str(self._cache / "download.lock"))
            if not self._lock.tryLock(0):
                self._lock = None
                self._fail("updates.otherInstance")
                return
            target = self._installation.target
            if not target or not target.exists():
                raise OSError("Missing installation")
            for directory in (self._cache, target.parent):
                if shutil.disk_usage(directory).free < self._release.size * 6 + 100 * 1024**2:
                    self._fail("updates.diskSpace")
                    return
            self._stage = Path(tempfile.mkdtemp(prefix="update-", dir=self._cache))
            self._progress = 0.0
            self._set_state("checksum", _msg("updates.verifying"))
            self._get(self._release.checksum_url, "checksum", 4096)
        except OSError:
            self._fail("updates.storageError")

    def _discard_download(self):
        if self._file:
            try:
                self._file.close()
            except OSError:
                logger.warning("Could not flush incomplete update", exc_info=True)
            finally:
                self._file = None
        if self._stage and self._release and self._release.name:
            try:
                (self._stage / self._release.name).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove incomplete update", exc_info=True)
        self._command = None
        if self._lock:
            self._lock.unlock()
            self._lock = None

    def _fail(self, key):
        self._discard_download()
        if self._state == "checking":
            logger.info("Update check ended silently: %s", key)
            self._set_state("available" if self._release else "idle",
                            _msg("updates.available", version=self.latestVersion) if self._release else _msg("updates.idle"))
            return
        self._set_state("error", _msg(key))

    @Slot()
    def dismiss(self):
        if self._release:
            self._session_dismissed = self._release.version
            self._settings.setValue("updates", "dismissedVersion", self._release.version)
        self._cancel_request()
        self._discard_download()
        if self._release:
            self._set_state("available", _msg("updates.available", version=self.latestVersion))
        else:
            self._set_state("idle", _msg("updates.idle"))

    @Slot()
    def openDownloads(self): QDesktopServices.openUrl(QUrl(RELEASE_PAGE))

    @Slot()
    def openLog(self):
        if self._stage:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._stage)))

    def shutdown(self):
        self._closed = True
        self._startup_timer.stop()
        self._timer.stop()
        self._cancel_request()
        if self._state != "ready":
            self._discard_download()

    def _cancel_request(self):
        reply, self._reply = self._reply, None
        self._timer.stop()
        if reply:
            reply.abort()
            reply.deleteLater()

    def install_after_exit(self):
        """The event loop has exited and workspace/render workers have shut down."""
        if self._state != "ready" or not self._command:
            return
        try:
            launch_installer(self._command, self._stage / "install.log")
        except OSError:
            (self._stage / "result").write_text("failed", encoding="ascii")
            raise
        finally:
            if self._lock:
                self._lock.unlock()
                self._lock = None
