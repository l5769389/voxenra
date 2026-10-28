"""A temporary C-STORE receiver restricted to the requested instance manifest."""
from hashlib import file_digest
from threading import Event, Lock

from pynetdicom import AE, evt, AllStoragePresentationContexts, ALL_TRANSFER_SYNTAXES

from qt_dicom_viewer.i18n import message as _msg
from .client import PacsError, check_cancel


class MoveReceiver:
    def __init__(self, profile, cancel, folder, expected, progress):
        self.profile, self.cancel, self.folder = profile, cancel, folder
        self.expected, self.progress = expected, progress
        self.received = {}
        self.error = False
        self.lock = Lock()
        self.closing = Event()
        self.server = None
        self.ae = AE(ae_title=profile.calling_ae)
        self.ae.require_called_aet = True
        self.ae.require_calling_aet = [profile.called_ae]
        self.ae.acse_timeout = self.ae.dimse_timeout = self.ae.network_timeout = profile.timeout
        self.ae.maximum_associations = 4
        for context in AllStoragePresentationContexts:
            self.ae.add_supported_context(context.abstract_syntax, ALL_TRANSFER_SYNTAXES)

    def __enter__(self):
        check_cancel(self.cancel)
        try:
            self.server = self.ae.start_server((self.profile.listen_host, self.profile.listen_port),
                block=False, evt_handlers=[(evt.EVT_C_STORE, self._store)])
        except OSError:
            self.ae.shutdown()
            raise PacsError(_msg('dimse.listenFailed', port=self.profile.listen_port)) from None
        return self

    def _store(self, event):
        with self.lock:
            if self.cancel.is_set() or self.closing.is_set(): return 0xA700
            target = None
            try:
                ds = event.dataset
                sop = str(ds.SOPInstanceUID)
                expected = self.expected.get(sop)
                if (expected is None or (str(ds.StudyInstanceUID), str(ds.SeriesInstanceUID)) != expected[:2]
                        or str(ds.SOPClassUID) != str(event.request.AffectedSOPClassUID)
                        or sop != str(event.request.AffectedSOPInstanceUID)
                        or (expected[2] and str(ds.SOPClassUID) != expected[2])):
                    self.error = True
                    return 0xA900
                ds.file_meta = event.file_meta
                # Never let peer-controlled identifiers become paths.
                index = len(self.received)
                target = self.folder / f'.receiving-{index:06d}'
                ds.save_as(target, enforce_file_format=True)
                with target.open('rb') as source:
                    digest = file_digest(source, 'sha256').hexdigest()
                if sop in self.received:
                    target.unlink()
                    if self.received[sop] != digest:
                        self.error = True
                        return 0xA900
                    return 0x0000
                target.replace(self.folder / f'{index:06d}.dcm')
                self.received[sop] = digest
                self.progress(len(self.received) / len(self.expected),
                    _msg('text.0336', value1=len(self.received), value2=len(self.expected)))
                return 0x0000
            except Exception:
                self.error = True
                if target is not None: target.unlink(missing_ok=True)
                return 0xA700

    def verify(self):
        check_cancel(self.cancel)
        with self.lock:
            if self.error or set(self.received) != set(self.expected):
                raise PacsError(_msg('dimse.incomplete'))

    def __exit__(self, *args):
        # Stop admission, then abort any lingering stores before staging is removed.
        self.closing.set()
        if self.server is not None: self.server.shutdown()
        for association in self.ae.active_associations: association.abort()
        self.ae.shutdown()
        with self.lock: pass
