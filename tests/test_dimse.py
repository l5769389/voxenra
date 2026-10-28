"""Real DIMSE sockets, independent peer handlers and synthetic pixel evidence."""
from copy import deepcopy
from io import BytesIO
import importlib
import socket
from threading import Event, Timer
import time

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian
from pynetdicom import AE, evt
from pynetdicom.sop_class import Verification, StudyRootQueryRetrieveInformationModelFind as FIND, StudyRootQueryRetrieveInformationModelMove as MOVE
import pytest

from qt_dicom_viewer.pacs.client import PacsError, Cancelled
from qt_dicom_viewer.pacs.config import PacsProfile
from qt_dicom_viewer.pacs.importer import import_series
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
            evt_handlers=[(evt.EVT_C_FIND, self.find), (evt.EVT_C_MOVE, self.move)])
        self.port = self.server.server_address[1]

    def profile(self, **changes):
        return PacsProfile.from_dict(dict(name='DIMSE lab', protocol='dimse', host='127.0.0.1',
            port=self.port, called_ae='LABPACS', calling_ae='VOXENRA',
            listen_host='127.0.0.1', listen_port=self.destination, timeout=3) | changes)

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
        assert event.move_destination == 'VOXENRA'
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
    assert importlib.util.find_spec('qt_dicom_viewer.pacs.dimse_client') is not None, 'DIMSE transport must exist'
    from qt_dicom_viewer.pacs.dimse_client import DimseClient
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
    from qt_dicom_viewer.pacs.dimse_receiver import MoveReceiver
    expected = {str(ds.SOPInstanceUID): (STUDY, SERIES, str(ds.SOPClassUID)) for ds in peer.datasets}
    with MoveReceiver(peer.profile(), Event(), tmp_path, expected, lambda *a: None) as receiver:
        ae = AE(ae_title='UNRELATED')
        ae.add_requested_context(CTImageStorage, ExplicitVRLittleEndian)
        association = ae.associate('127.0.0.1', peer.destination, ae_title='VOXENRA')
        assert not association.is_established
        ae.ae_title = 'LABPACS'
        association = ae.associate('127.0.0.1', peer.destination, ae_title='VOXENRA')
        assert association.is_established
        wrong = deepcopy(peer.datasets[0])
        wrong.SOPInstanceUID = '1.2.3.888'
        assert association.send_c_store(wrong).Status == 0xA900
        association.release()
        ae.shutdown()
        with pytest.raises(PacsError): receiver.verify()
    assert not list(tmp_path.iterdir())
