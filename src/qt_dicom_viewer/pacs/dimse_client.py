"""Study Root DIMSE query/retrieve; every operation owns its association."""
from contextlib import contextmanager
from threading import Event, Thread

from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.pdu_primitives import A_ABORT
from pynetdicom.sop_class import (
    Verification, StudyRootQueryRetrieveInformationModelFind as FIND,
    StudyRootQueryRetrieveInformationModelMove as MOVE,
)

from qt_dicom_viewer.i18n import message as _msg
from .client import PacsError, check_cancel, study_filters, uid, value


class DimseClient:
    def __init__(self, profile, cancel=None):
        self.profile = profile
        self.cancel = cancel if cancel is not None else Event()

    @contextmanager
    def association(self, model):
        check_cancel(self.cancel)
        ae = AE(ae_title=self.profile.calling_ae)
        ae.add_requested_context(model)
        ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = self.profile.timeout
        ae.connection_timeout = min(self.profile.timeout, 5)
        stopped = Event()
        releasing = Event()
        association = None

        def remember_connection(event):
            nonlocal association
            # EVT_REQUESTED fires before synchronous association negotiation.
            # AE.active_associations only lists already-started threads.
            association = event.assoc

        def watch_cancel():
            while not stopped.wait(.05):
                if self.cancel.is_set():
                    connection = association
                    if connection is None:
                        continue
                    if connection is not None:
                        if connection.is_established and not releasing.is_set() and model in (FIND, MOVE):
                            try:
                                connection.send_c_cancel(1, query_model=model)
                            except (ValueError, RuntimeError):
                                pass
                        connection.abort(block=True)
                        # pynetdicom 3.0.4's blocking get_msg() waits on this
                        # queue even after abort. Wake it so our cancellation
                        # check runs without waiting the full DIMSE timeout.
                        connection.dimse.msg_queue.put((None, None))
                        # ACSE establishment/release waits on a separate queue.
                        # Use its normal abort primitive to wake either phase.
                        connection.dul.to_user_queue.put(A_ABORT())
                    return

        watcher = Thread(target=watch_cancel, daemon=True)
        watcher.start()
        try:
            association = ae.associate(self.profile.host, self.profile.port,
                ae_title=self.profile.called_ae, evt_handlers=[(evt.EVT_REQUESTED, remember_connection)])
            check_cancel(self.cancel)
            if not association.is_established:
                raise PacsError(_msg('dimse.associationFailed'))
            yield association
            check_cancel(self.cancel)
        finally:
            try:
                if association is not None and association.is_established:
                    if self.cancel.is_set():
                        association.abort()
                    else:
                        releasing.set()
                        association.release()
            finally:
                stopped.set()
                watcher.join()
                ae.shutdown()
        check_cancel(self.cancel)

    def _status(self, status, operation):
        check_cancel(self.cancel)
        if status is None or not hasattr(status, 'Status'):
            raise PacsError(_msg('dimse.noResponse', operation=operation))
        code = int(status.Status)
        if code == 0xA801:
            raise PacsError(_msg('dimse.unknownDestination'))
        if code not in (0x0000, 0xFF00, 0xFF01):
            raise PacsError(_msg('dimse.statusFailed', operation=operation, status=f'{code:04X}'))
        return code

    def test_connection(self):
        with self.association(Verification) as association:
            self._status(association.send_c_echo(), 'C-ECHO')
        return _msg('dimse.echoSuccess')

    def _find(self, level, keys, identity, max_results=10000):
        query = Dataset()
        query.SpecificCharacterSet = 'ISO_IR 192'
        query.QueryRetrieveLevel = level
        for key, text in keys.items(): setattr(query, key, text)
        rows, seen, complete = [], set(), False
        with self.association(FIND) as association:
            for status, response in association.send_c_find(query, FIND, msg_id=1):
                code = self._status(status, 'C-FIND')
                if code == 0:
                    complete = True
                    break
                if response is None:
                    raise PacsError(_msg('dimse.invalidResponse'))
                identifier = uid(str(getattr(response, identity, '')))
                if identifier in seen:
                    raise PacsError(_msg('dimse.invalidResponse'))
                for key in ('StudyInstanceUID', 'SeriesInstanceUID'):
                    if keys.get(key) and getattr(response, key, keys[key]) != keys[key]:
                        raise PacsError(_msg('dimse.invalidResponse'))
                seen.add(identifier)
                rows.append(response.to_json_dict())
                if len(rows) > max_results:
                    association.send_c_cancel(1, query_model=FIND)
                    raise PacsError(_msg('dimse.queryLimit', count=max_results))
        if not complete:
            raise PacsError(_msg('dimse.noResponse', operation='C-FIND'))
        return rows

    def studies(self, filters, offset, limit):
        keys = dict(StudyInstanceUID='', PatientName='', PatientID='', StudyDate='',
                    StudyDescription='', AccessionNumber='', ModalitiesInStudy='', NumberOfStudyRelatedSeries='')
        keys.update(study_filters(filters))
        rows = self._find('STUDY', keys, 'StudyInstanceUID')
        rows.sort(key=lambda row: (value(row, '00080020'), value(row, '0020000D')), reverse=True)
        return [dict(uid=value(r,'0020000D'), patientName=value(r,'00100010'), patientId=value(r,'00100020'),
                     date=value(r,'00080020'), description=value(r,'00081030'), modality=value(r,'00080061'),
                     accession=value(r,'00080050'), seriesCount=value(r,'00201206')) for r in rows[offset:offset+limit]]

    def series(self, study, offset, limit):
        rows = self._find('SERIES', dict(StudyInstanceUID=uid(study), SeriesInstanceUID='',
            SeriesDescription='', Modality='', SeriesNumber='', NumberOfSeriesRelatedInstances=''), 'SeriesInstanceUID')
        def order(row):
            try: number = int(value(row, '00200011'))
            except ValueError: number = 0
            return number, value(row, '0020000E')
        rows.sort(key=order)
        return [dict(uid=value(r,'0020000E'), studyUid=study, description=value(r,'0008103E'),
                     modality=value(r,'00080060'), number=value(r,'00200011'), instances=value(r,'00201209'))
                for r in rows[offset:offset+limit]]

    def retrieve_series(self, selections, folder, progress):
        from .dimse_receiver import MoveReceiver
        expected = {}
        for selection in selections:
            study, series = uid(selection['studyUid']), uid(selection['uid'])
            progress(0, _msg('text.0334'))
            rows = self._find('IMAGE', dict(StudyInstanceUID=study, SeriesInstanceUID=series,
                SOPInstanceUID='', SOPClassUID=''), 'SOPInstanceUID', max_results=100000)
            count = str(selection.get('instances', ''))
            if not rows or (count.isdigit() and int(count) != len(rows)):
                raise PacsError(_msg('text.0335'))
            for row in rows:
                sop = uid(value(row, '00080018'))
                if sop in expected: raise PacsError(_msg('dimse.invalidResponse'))
                expected[sop] = (study, series, value(row, '00080016'))
        with MoveReceiver(self.profile, self.cancel, folder, expected, progress) as receiver:
            for selection in selections:
                check_cancel(self.cancel)
                query = Dataset()
                query.QueryRetrieveLevel = 'SERIES'
                query.StudyInstanceUID, query.SeriesInstanceUID = selection['studyUid'], selection['uid']
                complete = False
                with self.association(MOVE) as association:
                    for status, _ in association.send_c_move(query, self.profile.calling_ae, MOVE, msg_id=1):
                        code = self._status(status, 'C-MOVE')
                        if code == 0:
                            if (int(getattr(status, 'NumberOfFailedSuboperations', 0)) or
                                    int(getattr(status, 'NumberOfWarningSuboperations', 0))):
                                raise PacsError(_msg('dimse.incomplete'))
                            complete = True
                            break
                if not complete: raise PacsError(_msg('dimse.noResponse', operation='C-MOVE'))
            receiver.verify()
        return len(expected)
