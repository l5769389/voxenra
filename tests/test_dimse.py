"""Real DIMSE sockets, independent peer handlers and synthetic pixel evidence."""
from copy import deepcopy
from io import BytesIO
import importlib
import socket
from threading import Event, Thread, Timer
import time

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian
from pynetdicom import AE, evt
from pynetdicom.pdu import A_RELEASE_RQ
from pynetdicom.sop_class import Verification, StudyRootQueryRetrieveInformationModelFind as FIND, StudyRootQueryRetrieveInformationModelMove as MOVE
import pytest

from voxplane.pacs.client import PacsError, Cancelled
from voxplane.pacs.config import PacsProfile
from voxplane.pacs.importer import import_series
from test_pacs import dicom_bytes, STUDY, SERIES


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class DimsePeer:
    def __init__(self):
        self.datasets = [pydicom.dcmread(BytesIO(dicom_bytes(i))) for i in range(1, 4)]
        self.find_status = 0x0000
        self.move_status = None
        self.wrong_uid = False
        self.omit = False
        self.duplicate = False
        self.conflict = False
        self.delay = 0
        self.release_delay = 0
        self.releasing = Event()
        self.entered = Event()
        self.requests = []
        self.destination = free_port()
        self.ae = AE(ae_title='LABPACS')
        self.ae.require_called_aet = True
        self.ae.add_supported_context(Verification)
        self.ae.add_supported_context(FIND)
        self.ae.add_supported_context(MOVE)
        self.ae.add_requested_context(CTImageStorage, ExplicitVRLittleEndian)
        self.server = self.ae.start_server(('127.0.0.1', 0), block=False,
            evt_handlers=[(evt.EVT_C_FIND, self.find), (evt.EVT_C_MOVE, self.move),
                          (evt.EVT_PDU_RECV, self.receive_pdu)])
        self.port = self.server.server_address[1]

    def profile(self, **changes):
        return PacsProfile.from_dict(dict(name='DIMSE lab', protocol='dimse', host='127.0.0.1',
            port=self.port, called_ae='LABPACS', calling_ae='VOXPLANE',
            listen_host='127.0.0.1', listen_port=self.destination, timeout=3) | changes)

    def receive_pdu(self, event):
        if isinstance(event.pdu, A_RELEASE_RQ) and self.release_delay:
            self.releasing.set()
            time.sleep(self.release_delay)

    def find(self, event):
        q = event.identifier; self.requests.append(deepcopy(q))
        self.entered.set()
        time.sleep(self.delay)
        if self.find_status:
            yield self.find_status, None
            return
        if getattr(q, 'PatientID', '') == 'ABSENT':
            yield 0x0000, None
            return
        if q.QueryRetrieveLevel == 'STUDY':
            row = Dataset()
            row.StudyInstanceUID, row.PatientID, row.PatientName = STUDY, 'PACS-DEMO', '测试^患者'
            row.SpecificCharacterSet = 'ISO_IR 192'
            row.StudyDate, row.ModalitiesInStudy = '20260906', ['CT']
            row.NumberOfStudyRelatedSeries = 1
            yield 0xFF00, row
        elif q.QueryRetrieveLevel == 'SERIES':
            assert q.StudyInstanceUID == STUDY
            row = Dataset(); row.StudyInstanceUID, row.SeriesInstanceUID = STUDY, SERIES
            row.Modality, row.SeriesNumber, row.NumberOfSeriesRelatedInstances = 'CT', 1, 3
            row.SeriesDescription = 'Axial CT'
            yield 0xFF00, row
        else:
            assert q.QueryRetrieveLevel == 'IMAGE' and q.SeriesInstanceUID == SERIES
            for ds in self.datasets:
                row = Dataset()
                row.StudyInstanceUID, row.SeriesInstanceUID = STUDY, SERIES
                row.SOPInstanceUID, row.SOPClassUID = ds.SOPInstanceUID, ds.SOPClassUID
                yield 0xFF00, row
        yield 0x0000, None

    def move(self, event):
        q = event.identifier
        assert q.QueryRetrieveLevel == 'SERIES' and q.StudyInstanceUID == STUDY and q.SeriesInstanceUID == SERIES
        assert event.move_destination == 'VOXPLANE'
        self.entered.set()
        if self.move_status == 0xA801:
            yield None, None
            return
        yield '127.0.0.1', self.destination
        payload = deepcopy(self.datasets[:2] if self.omit else self.datasets)
        if self.wrong_uid:
            payload[0].StudyInstanceUID = '1.2.3.999'
        if self.duplicate:
            payload.append(deepcopy(payload[0]))
            if self.conflict:
                payload[-1].PixelData = b'\0' * len(payload[-1].PixelData)
        yield len(payload)
        for ds in payload:
            time.sleep(self.delay)
            if event.is_cancelled:
                yield 0xFE00, None
                return
            yield 0xFF00, ds

    def close(self):
        self.server.shutdown(); self.ae.shutdown()


@pytest.fixture
def peer():
    p = DimsePeer()
    try:
        yield p
    finally:
        p.close()


def client(peer, cancel=None, **kwargs):
    assert importlib.util.find_spec('voxplane.pacs.dimse_client') is not None, 'DIMSE transport must exist'
    from voxplane.pacs.dimse_client import DimseClient
    return DimseClient(peer.profile(**kwargs), cancel)


def test_echo_query_move_and_pixel_identity(peer, tmp_path):
    c = client(peer)
    assert 'C-ECHO' in c.test_connection()
    rows = c.studies({'PatientID':'PACS-DEMO', 'dateFrom':'2026-09-01'}, 0, 20)
    assert rows[0]['uid'] == STUDY and rows[0]['patientName'] == '测试 患者'
    assert peer.requests[-1].StudyDate == '20260901-'
    assert c.studies({'PatientID':'ABSENT'}, 0, 20) == []
    series = c.series(STUDY, 0, 20)
    assert series[0]['instances'] == '3'
    progress = []
    result = import_series(c, series, tmp_path, lambda v,m: progress.append(v))
    assert result.snapshot.dicom_file_count == 3 and result.snapshot.skipped_file_count == 0
    received = {str(d.SOPInstanceUID): d for d in map(pydicom.dcmread, result.folder.glob('*.dcm'))}
    for ds in peer.datasets:
        np.testing.assert_array_equal(received[str(ds.SOPInstanceUID)].pixel_array, ds.pixel_array)
    assert progress and progress[-1] == 1
    # Receiver has been released after the import.
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', peer.destination))


@pytest.mark.parametrize('failure', ['wrong_uid', 'omit', 'destination'])
def test_incomplete_or_wrong_move_never_publishes_and_cleans_staging(peer, tmp_path, failure):
    if failure == 'destination': peer.move_status = 0xA801
    else: setattr(peer, failure, True)
    c = client(peer)
    with pytest.raises(PacsError):
        import_series(c, c.series(STUDY, 0, 20), tmp_path, lambda *a: None)
    assert list(tmp_path.iterdir()) == []


def test_failed_query_is_not_an_empty_success(peer):
    peer.find_status = 0xA700
    with pytest.raises(PacsError, match='A700'):
        client(peer).studies({}, 0, 20)


def test_wrong_remote_ae_and_busy_receive_port_are_actionable(peer, tmp_path):
    with pytest.raises(PacsError): client(peer, called_ae='WRONG').test_connection()
    c = client(peer)
    rows = c.series(STUDY, 0, 20)
    with socket.socket() as s:
        s.bind(('127.0.0.1', peer.destination)); s.listen()
        with pytest.raises(PacsError): import_series(c, rows, tmp_path, lambda *a: None)
    assert list(tmp_path.iterdir()) == []


def test_cancel_stalled_query_is_bounded(peer):
    cancel = Event(); c = client(peer, cancel)
    peer.delay = 2
    timer = Timer(.25, cancel.set); timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(Cancelled): c.studies({}, 0, 20)
        assert time.monotonic() - started < 1.5
    finally: timer.cancel()


def test_cancel_move_removes_partial_files_and_listener(peer, tmp_path):
    cancel = Event(); c = client(peer, cancel)
    rows = c.series(STUDY, 0, 20)
    def progress(value, message):
        if value > 0: cancel.set()
    with pytest.raises(Cancelled): import_series(c, rows, tmp_path, progress)
    assert list(tmp_path.iterdir()) == []
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', peer.destination))


@pytest.mark.parametrize('conflict', [False, True])
def test_duplicate_store_is_idempotent_only_for_identical_data(peer, tmp_path, conflict):
    peer.duplicate, peer.conflict = True, conflict
    c = client(peer)
    rows = c.series(STUDY, 0, 20)
    if conflict:
        with pytest.raises(PacsError):
            import_series(c, rows, tmp_path, lambda *a: None)
        assert not list(tmp_path.iterdir())
    else:
        result = import_series(c, rows, tmp_path, lambda *a: None)
        assert result.snapshot.dicom_file_count == 3


def test_receive_rejects_unrelated_sender_and_instance(peer, tmp_path):
    from voxplane.pacs.dimse_receiver import MoveReceiver
    expected = {str(ds.SOPInstanceUID): (STUDY, SERIES, str(ds.SOPClassUID)) for ds in peer.datasets}
    with MoveReceiver(peer.profile(), Event(), tmp_path, expected, lambda *a: None) as receiver:
        ae = AE(ae_title='UNRELATED')
        ae.add_requested_context(CTImageStorage, ExplicitVRLittleEndian)
        association = ae.associate('127.0.0.1', peer.destination, ae_title='VOXPLANE')
        assert not association.is_established
        ae.ae_title = 'LABPACS'
        association = ae.associate('127.0.0.1', peer.destination, ae_title='VOXPLANE')
        assert association.is_established
        wrong = deepcopy(peer.datasets[0])
        wrong.SOPInstanceUID = '1.2.3.888'
        assert association.send_c_store(wrong).Status == 0xA900
        association.release()
        ae.shutdown()
        with pytest.raises(PacsError): receiver.verify()
    assert not list(tmp_path.iterdir())


def test_cancel_during_association_handshake_is_bounded(peer):
    cancel, accepted, stop = Event(), Event(), Event()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(5)
        def blackhole():
            connection, _ = listener.accept()
            with connection:
                accepted.set()
                stop.wait(5)
        worker = Thread(target=blackhole, daemon=True)
        worker.start()
        c = client(peer, cancel, port=listener.getsockname()[1])
        timer = Timer(.25, cancel.set)
        timer.start()
        started = time.monotonic()
        try:
            with pytest.raises(Cancelled): c.test_connection()
            assert accepted.is_set()
            assert time.monotonic() - started < 1.5
        finally:
            stop.set()
            timer.cancel()
            worker.join(2)


def test_cancel_during_association_release_is_bounded(peer):
    cancel = Event()
    peer.release_delay = 2
    def cancel_release():
        if peer.releasing.wait(5): cancel.set()
    worker = Thread(target=cancel_release, daemon=True)
    worker.start()
    started = time.monotonic()
    try:
        with pytest.raises(Cancelled): client(peer, cancel).test_connection()
        assert time.monotonic() - started < 1.5
    finally:
        worker.join(3)


@pytest.mark.parametrize('terminal', ['success', 'eof', 'abort', 'warning', 'failed_suboperation', 'warning_suboperation'])
def test_complete_stores_require_successful_move_terminal(peer, tmp_path, monkeypatch, terminal):
    """Real C-STORE transport plus controlled remote C-MOVE terminal responses.

    All objects arrive before the response is altered: file-count validation
    alone must never make an incomplete/failed exchange publish an import.
    """
    from contextlib import contextmanager
    from types import SimpleNamespace
    c = client(peer)
    original_association = c.association
    connections = []
    stores_before_terminal = []
    pending_seen = []

    @contextmanager
    def association(model):
        with original_association(model) as connection:
            connections.append(connection)
            if model != MOVE:
                yield connection
                return
            def responses(*args, **kwargs):
                for status, response in connection.send_c_move(*args, **kwargs):
                    if status.Status != 0:
                        pending_seen.append(int(status.Status))
                        yield status, response
                        continue
                    files = list(tmp_path.glob('import-*/*.dcm'))
                    stores_before_terminal.extend(str(pydicom.dcmread(p).SOPInstanceUID) for p in files)
                    if terminal == 'eof':
                        return
                    if terminal == 'abort':
                        connection.abort()
                        yield Dataset(), None  # pynetdicom's aborted-response sentinel
                        return
                    status = deepcopy(status)
                    if terminal == 'warning':
                        status.Status = 0xB000
                    elif terminal == 'failed_suboperation':
                        status.NumberOfFailedSuboperations = 1
                    elif terminal == 'warning_suboperation':
                        status.NumberOfWarningSuboperations = 1
                    yield status, response
            yield SimpleNamespace(send_c_move=responses)

    monkeypatch.setattr(c, 'association', association)
    selections = c.series(STUDY, 0, 20)
    if terminal == 'success':
        result = import_series(c, selections, tmp_path, lambda *a: None)
        assert result.snapshot.dicom_file_count == 3
    else:
        with pytest.raises(PacsError):
            import_series(c, selections, tmp_path, lambda *a: None)
        assert list(tmp_path.iterdir()) == []
    assert pending_seen and all(status == 0xFF00 for status in pending_seen)
    assert set(stores_before_terminal) == {str(ds.SOPInstanceUID) for ds in peer.datasets}
    assert not c.cancel.is_set()
    assert all(not connection.is_established and (connection.is_released or connection.is_aborted)
               for connection in connections)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', peer.destination))


@pytest.mark.parametrize('termination', ['eof', 'abort'])
def test_query_pending_without_final_success_is_not_published(peer, monkeypatch, termination):
    from contextlib import contextmanager
    from types import SimpleNamespace
    c = client(peer)
    original_association = c.association
    connections = []
    pending = []

    @contextmanager
    def association(model):
        with original_association(model) as connection:
            connections.append(connection)
            def responses(*args, **kwargs):
                for status, response in connection.send_c_find(*args, **kwargs):
                    if status.Status == 0:
                        if termination == 'abort':
                            connection.abort()
                            yield Dataset(), None
                        return
                    pending.append(str(response.StudyInstanceUID))
                    yield status, response
            yield SimpleNamespace(send_c_find=responses)
    monkeypatch.setattr(c, 'association', association)
    with pytest.raises(PacsError):
        c.studies({}, 0, 20)
    assert pending == [STUDY]
    assert not c.cancel.is_set()
    assert all(not connection.is_established and (connection.is_released or connection.is_aborted)
               for connection in connections)


def test_peer_abort_after_valid_pending_query_is_not_success(peer):
    # Abort on the remote peer, rather than modelling a client cancellation.
    original_find = peer.find
    def abort_after_pending(event):
        for status, row in original_find(event):
            if status == 0:
                event.assoc.abort()
                return
            yield status, row
    peer.server.bind(evt.EVT_C_FIND, abort_after_pending)
    c = client(peer)
    with pytest.raises(PacsError):
        c.studies({}, 0, 20)
    assert peer.entered.is_set()
    assert not c.cancel.is_set()
