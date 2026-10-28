"""Opt-in real DIMSE integration: DIMSE_LAB_TEST=1, dedicated OrbStack lab."""
import hashlib
import json
import os
from threading import Event

import pydicom
import pytest

from manual.dimse_lab import ARTIFACTS, PRIMARY_STUDY, PRIMARY_SERIES, MR_SERIES, profiles
from qt_dicom_viewer.pacs.client import Cancelled, PacsError
from qt_dicom_viewer.pacs.config import PacsProfile
from qt_dicom_viewer.pacs.dimse_client import DimseClient
from qt_dicom_viewer.pacs.importer import import_series
from test_pacs_qml import scene, screenshot
from test_tag_qml import find, click, type_text
from test_dicom_tags import qt_app, wait_until

pytestmark = pytest.mark.skipif(os.environ.get('DIMSE_LAB_TEST') != '1',
                                reason='Opt-in OrbStack DIMSE lab')


@pytest.fixture(params=profiles(), ids=lambda row: row['key'])
def live_profile(request):
    return request.param


def client(profile, cancel=None, **changes):
    return DimseClient(PacsProfile.from_dict(profile | changes), cancel)


def check_pixels(snapshot):
    expected = {row['sop']: row for row in json.loads((ARTIFACTS / 'manifest.json').read_text())}
    for series in snapshot.series:
        for instance in series.instances:
            ds = pydicom.dcmread(instance.path)
            row = expected[str(ds.SOPInstanceUID)]
            assert str(ds.StudyInstanceUID) == row['study']
            assert str(ds.SeriesInstanceUID) == row['series']
            assert hashlib.sha256(ds.pixel_array.tobytes()).hexdigest() == row['pixelSha256']


def test_query_pages_filters_move_and_reimport(live_profile, tmp_path):
    c = client(live_profile)
    assert 'C-ECHO' in c.test_connection()
    first, second = c.studies({}, 0, 20), c.studies({}, 20, 20)
    assert len(first) == 20 and len(second) == 3
    assert len({r['uid'] for r in first + second}) == 23
    assert c.studies({'PatientID':'PACSLAB-MISSING'}, 0, 20) == []
    assert len(c.studies({'PatientName':'测试^*'}, 0, 20)) == 1
    filtered = c.studies({'PatientID':'PACSLAB-001', 'dateFrom':'2026-08-01',
                         'dateTo':'2026-08-01', 'ModalitiesInStudy':'CT'}, 0, 20)
    assert [r['uid'] for r in filtered] == [PRIMARY_STUDY]
    rows = c.series(PRIMARY_STUDY, 0, 20) + c.series(PRIMARY_STUDY, 20, 20)
    assert len(rows) == len({r['uid'] for r in rows}) == 23
    chosen = [r for r in rows if r['uid'] in (PRIMARY_SERIES, MR_SERIES)]
    result = import_series(c, chosen, tmp_path, lambda *a: None)
    assert result.snapshot.dicom_file_count == 18
    check_pixels(result.snapshot)
    again = import_series(c, chosen, tmp_path, lambda *a: None,
                          base_series={s.series_instance_uid: s for s in result.snapshot.series})
    assert len(again.snapshot.series) == 2 and again.snapshot.dicom_file_count == 18
    check_pixels(again.snapshot)


def test_cancel_and_retry(live_profile, tmp_path):
    cancel = Event()
    c = client(live_profile, cancel)
    chosen = [r for r in c.series(PRIMARY_STUDY, 0, 30) if r['uid'] == PRIMARY_SERIES]
    def progress(value, _):
        if value > 0: cancel.set()
    with pytest.raises(Cancelled): import_series(c, chosen, tmp_path, progress)
    assert not list(tmp_path.iterdir())
    result = import_series(client(live_profile), chosen, tmp_path, lambda *a: None)
    assert result.snapshot.dicom_file_count == 16
    check_pixels(result.snapshot)


def test_echo_does_not_hide_unreachable_return_connection(live_profile, tmp_path):
    c = client(live_profile, listen_port=11114)
    assert 'C-ECHO' in c.test_connection()
    rows = [r for r in c.series(PRIMARY_STUDY, 0, 30) if r['uid'] == PRIMARY_SERIES]
    with pytest.raises(PacsError): import_series(c, rows, tmp_path, lambda *a: None)
    assert not list(tmp_path.iterdir())


def test_wrong_ae_reports_failure(live_profile):
    with pytest.raises(PacsError): client(live_profile, called_ae='NO_SUCH_AE').test_connection()


def test_qml_real_query_import_2d(scene, live_profile, tmp_path):
    window, app, warnings = scene
    pacs = app.pacsController
    assert pacs.saveProfile(live_profile | {'id': ''}), pacs.message
    click(window, find(window, 'sidebarPacs'))
    type_text(window, find(window, 'pacsPatientId'), 'PACSLAB-001')
    click(window, find(window, 'pacsQueryStudies'))
    wait_until(lambda: not pacs.busy, 20000)
    assert not pacs.isError, pacs.message
    click(window, find(window, 'pacsStudy-' + PRIMARY_STUDY))
    wait_until(lambda: not pacs.busy, 20000)
    click(window, find(window, 'pacsSeries-' + PRIMARY_SERIES))
    click(window, find(window, 'pacsImportSelected'))
    wait_until(lambda: not pacs.busy, 30000)
    assert not pacs.isError, pacs.message
    assert app.workspaceController.activeTabType == '2d'
    record = app._series_catalog.get_series(PRIMARY_SERIES)
    assert record.dicom_file_count == 16
    wait_until(lambda: app.workspaceController.activeViewport is not None)
    screenshot(window, tmp_path, live_profile['key'] + '-2d')
    assert not warnings, warnings
