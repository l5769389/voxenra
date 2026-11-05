"""Opt-in compatibility tests against docker/pacs/compose.yaml.

PACS_LAB_TEST=1 enables real HTTP/QML tests. PACS_LAB_NATIVE=1 additionally
checks the downloaded volume in a real native VTK viewport (desktop required).
"""
import hashlib
import json
import os
from threading import Event

import numpy as np
import pydicom
import pytest
from PySide6.QtCore import Qt, QMetaObject, Q_ARG
from PySide6.QtTest import QTest

from manual.pacs_lab import ARTIFACTS, PRIMARY_STUDY, PRIMARY_SERIES, MR_SERIES, profiles
from qt_dicom_viewer.pacs.client import Cancelled, DicomWebClient, PacsError
from qt_dicom_viewer.pacs.config import PacsProfile
from qt_dicom_viewer.pacs.importer import import_series
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click, type_text

pytestmark = pytest.mark.skipif(os.environ.get("PACS_LAB_TEST") != "1", reason="Opt-in Docker PACS lab")


@pytest.fixture(params=["orthanc-open", "orthanc-basic", "orthanc-bearer", "dcm4chee"])
def live_profile(request):
    return next(row for row in profiles() if row["key"] == request.param)


def manifest_by_sop():
    return {row["sop"]: row for row in json.loads((ARTIFACTS / "manifest.json").read_text())}


def check_pixels(snapshot):
    expected = manifest_by_sop()
    for series in snapshot.series:
        for instance in series.instances:
            ds = pydicom.dcmread(instance.path)
            row = expected[str(ds.SOPInstanceUID)]
            assert str(ds.SeriesInstanceUID) == row["series"]
            assert str(ds.StudyInstanceUID) == row["study"]
            assert hashlib.sha256(ds.pixel_array.tobytes()).hexdigest() == row["pixelSha256"]


def test_real_server_queries_pagination_import_and_pixels(live_profile, tmp_path):
    client = DicomWebClient(PacsProfile.from_dict(live_profile))
    assert "连接成功" in client.test_connection()
    first, second = client.studies({}, 0, 20), client.studies({}, 20, 20)
    assert len(first) == 20 and len(second) == 3
    assert len({row["uid"] for row in first + second}) == 23
    filtered = client.studies({"PatientID": "PACSLAB-001", "dateFrom": "2026-08-01", "dateTo": "2026-08-01", "ModalitiesInStudy": "CT"}, 0, 20)
    assert [row["uid"] for row in filtered] == [PRIMARY_STUDY]
    assert client.studies({"PatientID": "PACSLAB-MISSING"}, 0, 20) == []
    assert len(client.studies({"PatientName": "测试^患者"}, 0, 20)) == 1
    assert len(client.studies({"PatientName": "测试^*"}, 0, 20)) == 1
    series = client.series(PRIMARY_STUDY, 0, 20) + client.series(PRIMARY_STUDY, 20, 20)
    assert len(series) == len({row["uid"] for row in series}) == 23
    chosen = [row for row in series if row["uid"] in (PRIMARY_SERIES, MR_SERIES)]
    assert len(chosen) == 2
    assert len(client.instance_uids(PRIMARY_STUDY, PRIMARY_SERIES)) == 16
    updates = []
    result = import_series(client, chosen, tmp_path, lambda n, message: updates.append(n))
    assert result.snapshot.dicom_file_count == 18
    assert len(result.snapshot.series) == 2
    assert updates[-1] == 1.0
    check_pixels(result.snapshot)


def test_real_server_cancel_cleans_partial_download(live_profile, tmp_path):
    cancel = Event()
    client = DicomWebClient(PacsProfile.from_dict(live_profile), cancel)
    series = client.series(PRIMARY_STUDY, 0, 100)
    chosen = [row for row in series if row["uid"] == PRIMARY_SERIES]
    def update(n, message):
        if n > 0:
            cancel.set()
    with pytest.raises(Cancelled):
        import_series(client, chosen, tmp_path, update)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("key", ["orthanc-basic", "orthanc-bearer"])
def test_real_server_rejects_wrong_credentials(key):
    profile = next(row for row in profiles() if row["key"] == key)
    with pytest.raises(PacsError, match="认证失败"):
        DicomWebClient(PacsProfile.from_dict({**profile, "secret": "intentionally-wrong"})).test_connection()


def choose(window, name, index):
    control = find(window, name)
    click(window, control)
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index):
        QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(50)
    assert control.property("currentIndex") == index


def click_series(window, pacs, series_uid):
    index = next(i for i, row in enumerate(pacs.series) if row["uid"] == series_uid)
    view = find(window, "pacsSeriesList")
    QMetaObject.invokeMethod(view, "positionViewAtIndex", Q_ARG(int, index), Q_ARG(int, 1))
    QTest.qWait(50)
    before = view.property("contentY")
    click(window, find(window, "pacsSeries-" + series_uid))
    assert view.property("contentY") == pytest.approx(before)


def snapshot(window, filename):
    QTest.qWait(100)
    path = ARTIFACTS / "screenshots" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(path))


def test_real_qml_configure_test_query_import_and_view(scene, live_profile):
    window, app, warnings = scene
    pacs, workspace = app.pacsController, app.workspaceController
    click(window, find(window, "sidebarSettings"))
    click(window, find(window, "pacsAddProfile"))
    QTest.qWait(100)
    type_text(window, find(window, "pacsProfileName"), live_profile["name"])
    type_text(window, find(window, "pacsProfileUrl"), live_profile["url"])
    if live_profile["auth"] != "none":
        choose(window, "pacsProfileAuth", 1 if live_profile["auth"] == "basic" else 2)
        if live_profile["auth"] == "basic":
            type_text(window, find(window, "pacsProfileUsername"), live_profile["username"])
        type_text(window, find(window, "pacsProfileSecret"), live_profile["secret"])
    click(window, find(window, "pacsTestDraft"))
    wait_until(lambda: not pacs.busy, 15000)
    assert not pacs.isError, pacs.message
    click(window, find(window, "pacsSaveProfile"))
    QTest.qWait(100)
    assert len(pacs.profiles) == 1
    click(window, find(window, "sidebarPacs"))
    type_text(window, find(window, "pacsPatientId"), "PACSLAB-001")
    click(window, find(window, "pacsQueryStudies"))
    wait_until(lambda: not pacs.busy, 15000)
    assert not pacs.isError, pacs.message
    click(window, find(window, "pacsStudy-" + PRIMARY_STUDY))
    wait_until(lambda: not pacs.busy, 15000)
    chosen = [row for row in pacs.series if row["uid"] in (PRIMARY_SERIES, MR_SERIES)]
    assert len(chosen) == 2
    for row in chosen:
        click_series(window, pacs, row["uid"])
    snapshot(window, live_profile["key"] + "-browser.png")
    click(window, find(window, "pacsImportSelected"))
    wait_until(lambda: not pacs.busy, 30000)
    assert not pacs.isError, pacs.message
    assert workspace.activeTabType == "2d"
    wait_until(lambda: bool(workspace.activeViewport.imageSource), 15000)
    assert len(app.panelController.seriesItems) == 2
    assert app._series_catalog.get_series(PRIMARY_SERIES).dicom_file_count == 16
    snapshot(window, live_profile["key"] + "-2d.png")
    app.panelController.selectSeries(PRIMARY_SERIES)
    click(window, find(window, "openView-mpr"))
    wait_until(lambda: workspace.activeTabType == "mpr" and len(workspace.currentTabAllViewports) == 3
               and all(v.imageSource for v in workspace.currentTabAllViewports), 15000)
    snapshot(window, live_profile["key"] + "-mpr.png")
    click(window, find(window, "openView-tag"))
    wait_until(lambda: workspace.activeTabType == "tag" and not workspace.activeTab.tagController.loading, 15000)
    snapshot(window, live_profile["key"] + "-tags.png")
    # Reimport the same two series through the browser; the sidebar remains deduplicated.
    click(window, find(window, "sidebarPacs"))
    for row in chosen:
        click_series(window, pacs, row["uid"])
    click(window, find(window, "pacsImportSelected"))
    wait_until(lambda: not pacs.busy, 30000)
    assert not pacs.isError, pacs.message
    assert len(app.panelController.seriesItems) == 2
    assert not warnings, warnings


@pytest.mark.skipif(os.environ.get("PACS_LAB_NATIVE") != "1", reason="Needs native desktop and OpenGL")
def test_downloaded_volume_renders_in_native_3d_and_switches_settings(scene, tmp_path):
    window, app, warnings = scene
    profile = next(row for row in profiles() if row["key"] == "dcm4chee")
    client = DicomWebClient(PacsProfile.from_dict(profile))
    rows = [row for row in client.series(PRIMARY_STUDY, 0, 100) if row["uid"] == PRIMARY_SERIES]
    result = import_series(client, rows, tmp_path, lambda *_: None)
    app.panelController.acceptPacsImport(result.snapshot)
    app.panelController.selectSeries(PRIMARY_SERIES)
    click(window, find(window, "openView-3d"))
    viewport = app.workspaceController.activeViewport
    wait_until(lambda: viewport.loadState in ("ready", "error"), 20000)
    assert viewport.loadState == "ready", viewport.errorMessage
    wait_until(lambda: viewport._host is not None and viewport._host.frame_ready
               and viewport._host.surface_ready(), 20000)
    frame = viewport.snapshot_image()
    rows = np.frombuffer(frame.constBits(), dtype=np.uint8).reshape(frame.height(), frame.bytesPerLine())
    pixels = rows[:, :3 * frame.width()].reshape(-1, 3)
    assert np.count_nonzero(pixels.max(axis=1) > 80) > 1000
    out = ARTIFACTS / "screenshots/dcm4chee-native-3d.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    assert frame.save(str(out))
    tab = app.workspaceController.activeTabId
    click(window, find(window, "sidebarSettings"))
    wait_until(lambda: not viewport._host.isVisible())
    app.workspaceController.activateTabId(tab)
    wait_until(lambda: viewport._host.isVisible() and viewport._host.surface_ready())
    assert not warnings, warnings
