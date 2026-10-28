"""Local/PACS imports share one catalog without losing temporal sources."""
from pathlib import Path
from threading import Event
import shutil

import pytest
from PySide6.QtCore import QUrl

from qt_dicom_viewer.core.local_import import ImportCancelled
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.pacs.client import check_cancel
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_four_d import _cross_series_four_d


@pytest.fixture
def importing_app(qt_app, tmp_path, monkeypatch):
    records = _cross_series_four_d(tmp_path / 'source')
    entered, release = Event(), Event()
    release.set()
    files = {i.sop_instance_uid: i.path for r in records for i in r.instances}

    class Client:
        def __init__(self, profile, cancel):
            self.cancel = cancel
            self.profile = profile

        def instance_uids(self, study, uid):
            entered.set()
            assert release.wait(5)
            check_cancel(self.cancel)
            return [i.sop_instance_uid for r in records if r.series_instance_uid == uid for i in r.instances]

        def download_instance(self, study, uid, sop, target):
            check_cancel(self.cancel)
            shutil.copyfile(files[sop], target)

        def test_connection(self):
            return 'Synthetic connection succeeded'

        def studies(self, filters, offset, limit):
            return [{'uid': records[0].study_instance_uid}]

    monkeypatch.setattr('qt_dicom_viewer.pacs.transport.DicomWebClient', Client)
    app = AppController(DicomImageProvider(), settings_path=False,
                        pacs_config_path=tmp_path / 'pacs.json', pacs_import_root=tmp_path / 'downloads')
    pacs = app.pacsController
    pacs.saveProfile({'name': 'Synthetic PACS', 'url': 'http://localhost/dicom-web'})
    chosen = records[0]
    pacs._series = [{'uid': chosen.series_instance_uid, 'studyUid': chosen.study_instance_uid, 'instances': '2'}]
    pacs.selectAllSeries(True)
    snapshot = DicomFolderScanSnapshot(tmp_path / 'source', 6, 6, 0, records)
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    try:
        yield app, records, entered, release
    finally:
        release.set()
        app.shutdown()


def test_pacs_single_phase_reimport_preserves_open_four_d(importing_app):
    app, records, _, _ = importing_app
    uid = records[0].series_instance_uid
    workspace = app.workspaceController
    workspace.createTab(uid, 'Temporal', '4d')
    tab = workspace.activeTab
    wait_until(lambda: tab.voiController._phase_ready and not tab._active_mpr_requests)
    failures = []
    app.render_service.failed.connect(failures.append)
    app.pacsController.importSelected()
    wait_until(lambda: not app.pacsController.busy)
    assert not app.pacsController.isError
    for original in records:
        current = app._series_catalog.get_series(original.series_instance_uid)
        assert current.phase_identifiers == (0, 1, 2)
        assert all(i.path.parent.parent == app.pacsController._import_root
                   for i in current.phases[0].instances)
    workspace.activateTabId(tab.tab_config.tab_id)
    tab.setPhaseIndex(1)
    wait_until(lambda: tab._current_phase_index == 1 and tab.voiController._phase_ready)
    assert not failures


def test_pacs_merge_does_not_readd_hidden_or_concurrently_removed_series(importing_app):
    app, records, entered, release = importing_app
    panel, pacs = app.panelController, app.pacsController
    panel.removeSeries(records[1].series_instance_uid)
    release.clear()
    pacs.importSelected()
    wait_until(entered.is_set)
    panel.removeSeries(records[0].series_instance_uid)
    release.set()
    wait_until(lambda: not pacs.busy)
    assert set(panel._scan_series_record) == {records[2].series_instance_uid}
    assert app._series_catalog.get_series(records[0].series_instance_uid).phase_identifiers == (0, 1, 2)
    assert not app.workspaceController._tab_dict  # No hidden source is opened on completion.


def test_local_import_waits_for_pacs_import_and_can_retry_after_cancel(importing_app):
    app, records, entered, release = importing_app
    pacs, panel = app.pacsController, app.panelController
    release.clear()
    pacs.importSelected()
    wait_until(entered.is_set)
    urls = [QUrl.fromLocalFile(str(records[1].instances[0].path))]
    accepted = panel.importUrls(urls)
    blocked = not accepted and not panel.scanning and panel.importError and bool(panel.statusMessage)
    pacs.cancel()
    release.set()
    wait_until(lambda: not pacs.busy and not panel.scanning)
    assert blocked
    assert not list(pacs._import_root.iterdir())
    panel.retryImport()
    assert panel.scanning
    wait_until(lambda: not panel.scanning)
    assert not panel.importError


def test_pacs_import_waits_for_local_but_query_and_test_still_work(importing_app, monkeypatch):
    app, _, _, _ = importing_app
    panel, pacs = app.panelController, app.pacsController
    entered, release = Event(), Event()

    def prepare(paths, *, cancelled, progress):
        entered.set()
        assert release.wait(5)
        if cancelled():
            raise ImportCancelled()
        return ()

    monkeypatch.setattr(panel._import_store, 'prepare', prepare)
    panel._start_import(['synthetic-source'])
    wait_until(entered.is_set)
    try:
        pacs.importSelected()
        blocked = not pacs.busy and pacs.isError and bool(pacs.message)
        wait_until(lambda: not pacs.busy)
        assert blocked
        pacs.testProfile(pacs.selectedProfileId)
        wait_until(lambda: not pacs.busy)
        assert not pacs.isError
        pacs.queryStudies({}, 20)
        wait_until(lambda: not pacs.busy)
        assert pacs.studies and not pacs.isError
    finally:
        panel.cancelImport()
        release.set()
        wait_until(lambda: not panel.scanning)


def test_pacs_import_waits_for_workspace_restore(importing_app):
    app, _, _, _ = importing_app
    document, pacs = app.workspaceDocumentController, app.pacsController
    document._restoring = True
    try:
        pacs.importSelected()
        blocked = not pacs.busy and pacs.isError and bool(pacs.message)
        wait_until(lambda: not pacs.busy)
        assert blocked
    finally:
        document._restoring = False


def test_skip_missing_waits_for_active_pacs_import(importing_app, monkeypatch):
    app, _, entered, release = importing_app
    document, pacs = app.workspaceDocumentController, app.pacsController
    document._pending = {'snapshot': object()}
    started = []
    monkeypatch.setattr(document, '_begin_restore', lambda: started.append(True))
    release.clear()
    pacs.importSelected()
    wait_until(entered.is_set)
    try:
        document.skipMissing()
        assert not started and document.isError
    finally:
        document._pending = None
        pacs.cancel()
        release.set()
        wait_until(lambda: not pacs.busy)


def test_pacs_sequential_first_import_links_cross_series_phases(importing_app):
    app, records, _, _ = importing_app
    panel, pacs = app.panelController, app.pacsController
    panel.clearSeries()
    app._series_catalog.replace(None)
    for record in records:
        pacs._series = [{'uid': record.series_instance_uid, 'studyUid': record.study_instance_uid, 'instances': '2'}]
        pacs.selectAllSeries(True)
        pacs.importSelected()
        wait_until(lambda: not pacs.busy)
        assert not pacs.isError, pacs.message
    assert set(panel._scan_series_record) == {r.series_instance_uid for r in records}
    assert all(r.phase_identifiers == (0, 1, 2) for r in panel._scan_series_record.values())
