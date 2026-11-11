from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pydicom
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from shiboken6 import delete

from voxplane.core.dicom_scanner import _read_instance, _build_series_record
from voxplane.core.series_sidebar import build_sidebar_rows, patient_key
from voxplane.core.series_thumbnail import read_series_thumbnail
from voxplane.model import DicomFolderScanSnapshot
from voxplane.service.thumbnail_service import ThumbnailRequest, ThumbnailService
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, make_dicom, make_series, wait_until
from test_tag_qml import find, click, type_text, descendants


def test_patient_study_series_grouping_identity_search_and_collapse(tmp_path):
    base = make_series(tmp_path, 1)
    a = replace(base, patient_name="同名患者", patient_id="A", study_instance_uid="study-1",
                study_date="20260903", study_time="093012.5", series_number=2)
    b = replace(a, series_instance_uid="series-2", series_number=1, series_description="")
    c = replace(a, series_instance_uid="series-3", study_instance_uid="study-2", study_date="20260801")
    d = replace(a, patient_id="B", series_instance_uid="series-4", study_instance_uid="study-3")
    e = replace(a, patient_id_issuer="Another hospital", series_instance_uid="series-5")
    rows = build_sidebar_rows([a, b, c, d, e], "", set(), {})
    assert sum(row["kind"] == "patient" for row in rows) == 3
    assert sum(row["kind"] == "study" for row in rows) == 4
    own = build_sidebar_rows([a, b, c], "", set(), {})
    assert [row["seriesInstanceUid"] for row in own if row["kind"] == "series"] == [b.series_instance_uid, a.series_instance_uid, c.series_instance_uid]
    assert own[1]["label"] == "2026/09/03 09:30:12"
    assert own[2]["label"] == "[无描述]"
    key = patient_key(a)
    assert len(build_sidebar_rows([a, b, c], "", {key}, {})) == 1
    assert len(build_sidebar_rows([a, b, c], "同名", {key}, {})) == len(own)
    assert build_sidebar_rows([a], "missing", set(), {}) == []
    assert patient_key(replace(a, patient_id="")) != patient_key(replace(c, patient_id=""))


@pytest.mark.parametrize("kind", ["gray", "inverted", "rgb", "multiframe"])
def test_thumbnail_decodes_frame_and_preserves_contrast(tmp_path, kind):
    path = tmp_path / "image.dcm"
    ds = make_dicom(path)
    ramp = np.tile(np.arange(64, dtype=np.uint16), (32, 1))
    ds.Rows, ds.Columns = ramp.shape
    ds.NumberOfFrames = 2 if kind == "multiframe" else 1
    ds.RescaleIntercept = 0
    ds.WindowCenter = 32
    ds.WindowWidth = 64
    if kind == "rgb":
        ds.SamplesPerPixel = 3
        ds.PlanarConfiguration = 0
        ds.PhotometricInterpretation = "RGB"
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        pixels = np.zeros((32, 64, 3), dtype=np.uint8)
        pixels[:, :, 0] = 255
        ds.PixelData = pixels.tobytes()
    else:
        ds.PhotometricInterpretation = "MONOCHROME1" if kind == "inverted" else "MONOCHROME2"
        ds.PixelData = (np.stack([ramp, np.zeros_like(ramp)]) if kind == "multiframe" else ramp).tobytes()
    ds.save_as(path, enforce_file_format=True)
    image = read_series_thumbnail(path)
    assert (image.width(), image.height()) == (128, 64)
    if kind == "rgb":
        assert image.pixelColor(50, 30).red() == 255 and image.pixelColor(50, 30).green() == 0
    else:
        left, right = image.pixelColor(1, 30).red(), image.pixelColor(126, 30).red()
        assert left > right if kind == "inverted" else left < right


def test_thumbnail_queue_coalesces_and_handles_decode_failure(qt_app, tmp_path):
    entered, release = Event(), Event()
    reads, results = [], []

    def reader(path):
        reads.append(path.name)
        if path.name == "slow":
            entered.set()
            assert release.wait(3)
        if path.name == "missing":
            raise ValueError("no pixel data")
        image = QImage(8, 8, QImage.Format_Grayscale8)
        image.fill(180)
        return image

    service = ThumbnailService(reader=reader)
    service.finished.connect(lambda request, image: results.append((request, image)))
    try:
        service.submit(ThumbnailRequest("one", tmp_path / "slow"))
        wait_until(entered.is_set)
        service.submit(ThumbnailRequest("one", tmp_path / "skip"))
        service.submit(ThumbnailRequest("one", tmp_path / "latest"))
        service.submit(ThumbnailRequest("two", tmp_path / "missing"))
        release.set()
        wait_until(lambda: len(results) == 2)
        assert reads == ["slow", "latest", "missing"]
        assert results[0][0].path.name == "latest" and not results[0][1].isNull()
        assert results[1][1].isNull()
        service.submit(ThumbnailRequest("one", tmp_path / "latest"))
        QTest.qWait(30)
        assert len(reads) == 3
    finally:
        release.set()
        service.shutdown()
        delete(service)


def test_thumbnail_cancel_discards_in_flight_result(qt_app, tmp_path):
    entered, release = Event(), Event()
    results = []

    def reader(path):
        entered.set()
        assert release.wait(3)
        image = QImage(8, 8, QImage.Format_Grayscale8)
        image.fill(180)
        return image

    service = ThumbnailService(reader=reader)
    service.finished.connect(lambda request, image: results.append(request))
    try:
        service.submit(ThumbnailRequest("removed", tmp_path / "slow"))
        wait_until(entered.is_set)
        service.cancel("removed")
        release.set()
        QTest.qWait(80)
        assert results == []
    finally:
        release.set()
        service.shutdown()
        delete(service)


def phantom_series(tmp_path, series_index, patient_id, study_uid, date):
    instances = []
    yy, xx = np.mgrid[:96, :96]
    pixels = np.zeros((96, 96), dtype=np.uint16)
    body = ((xx - 48) / 32) ** 2 + ((yy - 48) / 38) ** 2 < 1
    pixels[body] = 1060
    pixels[(xx - 48) ** 2 + (yy - 61) ** 2 < 8 ** 2] = 1400
    pixels[((xx - 35) / 9) ** 2 + ((yy - 43) / 17) ** 2 < 1] = 200
    pixels[((xx - 61) / 9) ** 2 + ((yy - 43) / 17) ** 2 < 1] = 200
    for index in range(3):
        path = tmp_path / f"series-{series_index}-{index}.dcm"
        ds = make_dicom(path, series_index * 10 + index + 1)
        ds.PatientID = patient_id
        ds.PatientName = "演示患者 " + patient_id[-1]
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = "1.2.826.0.1.3680043.10.888." + str(series_index)
        ds.StudyDate, ds.StudyTime = date, "093012"
        ds.SeriesNumber = series_index
        ds.SeriesDescription = ["胸部 · 薄层重建", "胸部 · 复查", "腹部 · 轴位"][series_index - 1]
        ds.Rows = ds.Columns = 96
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, index * 2]
        ds.SliceThickness = 2
        ds.NumberOfFrames = 1
        ds.PixelData = np.roll(pixels, index, axis=0).tobytes()
        ds.save_as(path, enforce_file_format=True)
        instances.append(_read_instance(path))
    return _build_series_record(instances)


@pytest.fixture
def sidebar_scene(qt_app, tmp_path):
    records = [
        phantom_series(tmp_path, 1, "DEMO-A", "1.2.3.1", "20260903"),
        phantom_series(tmp_path, 2, "DEMO-A", "1.2.3.2", "20260822"),
        phantom_series(tmp_path, 3, "DEMO-B", "1.2.3.3", "20260901"),
    ]
    provider = DicomImageProvider()
    app = AppController(provider, settings_path=tmp_path / "display-settings.json",
                        pacs_config_path=tmp_path / "pacs.json", pacs_import_root=tmp_path / "imports")
    panel = app.panelController
    snapshot = DicomFolderScanSnapshot(tmp_path, 9, 9, 0, records)
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    engine = QQmlApplicationEngine()
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    engine.addImageProvider("navigation", SvgIconProvider())
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.addImageProvider("dicom", provider)
    engine.rootContext().setContextProperty("appController", app)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/voxplane/qml/Main.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    try:
        wait_until(lambda: len(panel._thumbnails) == 3)
        QTest.qWait(80)
        yield window, app, records, warnings
    finally:
        window.hide()
        app.shutdown()
        delete(engine)
        # Dispose Qt-owned children on the GUI thread, before a later background
        # worker can trigger Python GC for this completed test's controller cycle.
        delete(app)


def drag_width(window, target_width):
    sidebar = find(window, "sidebarContainer")
    handle = find(window, "sidebarResizeHandle")
    origin = handle.mapToScene(QPointF(handle.width() / 2, 180)).toPoint()
    end = QPoint(origin.x() + int(target_width - sidebar.width()), origin.y())
    QTest.mouseMove(window, origin)
    assert handle.property("cursorShape") == Qt.SizeHorCursor
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, origin)
    for step in range(1, 9):
        point = QPoint(round(origin.x() + (end.x() - origin.x()) * step / 8), origin.y())
        QTest.mouseMove(window, point, 15)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(60)


def right_click(window, item):
    pos = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, pos)
    QTest.qWait(40)


def test_open_series_directory_and_remove_keeps_existing_tab(qt_app, tmp_path, monkeypatch):
    series = make_series(tmp_path, 3)
    provider = DicomImageProvider()
    app = AppController(provider, settings_path=False)
    panel = app.panelController
    snapshot = DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [series])
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    try:
        assert panel.openSeriesDirectory(series.series_instance_uid)
        assert Path(opened[0].toLocalFile()) == tmp_path
        assert not panel.openSeriesDirectory("missing-series")

        panel.selectSeries(series.series_instance_uid)
        panel.openSeriesView(series.series_instance_uid, "tag")
        wait_until(lambda: app.workspaceController.activeTab is not None
                   and not app.workspaceController.activeTab.tagController.loading)
        tag_controller = app.workspaceController.activeTab.tagController
        tab_count = len(app.workspaceController.tabs)
        image_id = "thumbnail-" + series.series_instance_uid
        image = QImage(4, 4, QImage.Format_Grayscale8)
        image.fill(128)
        provider.set_image(image_id, image)
        panel._thumbnails[series.series_instance_uid] = "image://dicom/" + image_id

        panel.removeSeries(series.series_instance_uid)
        assert panel.activeSeriesUid == ""
        assert not any(row["seriesInstanceUid"] == series.series_instance_uid
                       for row in panel.sidebarItems)
        assert len(app.workspaceController.tabs) == tab_count
        assert app.workspaceController.activeTab.tagController is tag_controller
        assert app._series_catalog.get_series(series.series_instance_uid) is series
        assert image_id not in provider._images
        assert series.first_file.exists()

        panel._update_series_record(snapshot)
        assert not any(row["seriesInstanceUid"] == series.series_instance_uid
                       for row in panel.sidebarItems)
        assert not panel.openSeriesDirectory(series.series_instance_uid)
    finally:
        app.shutdown()
        delete(app)


def test_sidebar_group_search_selection_and_thumbnails(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    panel = app.panelController
    assert records[0].study_date == "20260903" and records[0].study_time == "093012"
    for series in records:
        thumbnail = find(window, "seriesThumbnail-" + series.series_instance_uid)
        assert thumbnail.property("paintedWidth") > 0
        assert thumbnail.property("source").toString().startswith("image://dicom/thumbnail-")
    first_uid = records[0].series_instance_uid
    click(window, find(window, "series-" + first_uid))
    assert panel.activeSeriesUid == first_uid
    click(window, find(window, "openView-2d"))
    assert app.workspaceController.activeTabType == "2d"
    wait_until(lambda: app.workspaceController.activeViewport.imageSource != "")
    QTest.qWait(60)
    assert window.grabWindow().save(str(tmp_path / "dicom-sidebar-expanded.png"))
    study = next(row for row in panel.sidebarItems if row["kind"] == "study")
    click(window, find(window, "sidebar-" + study["key"]))
    assert not any(row["seriesInstanceUid"] == first_uid for row in panel.sidebarItems)
    type_text(window, find(window, "sidebarPatientSearch"), "demo-a")
    assert sum(row["kind"] == "patient" for row in panel.sidebarItems) == 1
    assert sum(row["kind"] == "series" for row in panel.sidebarItems) == 2
    click(window, find(window, "sidebarToggle"))
    assert find(window, "compactSeriesRail").isVisible()
    assert not any(item.objectName() == "sidebarPatientSearch" and item.isVisible() for item in descendants(window.contentItem()))
    click(window, find(window, "sidebarToggle"))
    assert panel.activeSeriesUid == first_uid
    assert find(window, "sidebarPatientSearch").property("text") == "demo-a"
    type_text(window, find(window, "sidebarPatientSearch"), "")
    assert not any(row["seriesInstanceUid"] == first_uid for row in panel.sidebarItems)
    assert not warnings, warnings


def test_sidebar_resize_limits_auto_collapse_and_restore(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    sidebar = find(window, "sidebarContainer")
    assert sidebar.width() == 300
    click(window, find(window, "series-" + records[0].series_instance_uid))
    click(window, find(window, "openView-tag"))
    wait_until(lambda: not app.workspaceController.activeTab.tagController.loading)
    drag_width(window, 330)
    assert sidebar.width() == pytest.approx(330)
    drag_width(window, 450)
    assert sidebar.width() == pytest.approx(350)
    drag_width(window, 200)
    assert sidebar.width() == pytest.approx(200) and not sidebar.property("collapsed")
    QTest.mouseMove(window, QPoint(600, 300))
    QTest.qWait(80)
    assert window.grabWindow().save(str(tmp_path / "dicom-sidebar-minimum.png"))
    drag_width(window, 199)
    assert sidebar.width() == 52 and sidebar.property("collapsed")
    assert find(window, "sidebarToggle").property("text") == "›"
    QTest.mouseMove(window, QPoint(600, 300))
    QTest.qWait(80)
    assert window.grabWindow().save(str(tmp_path / "dicom-sidebar-collapsed.png"))
    click(window, find(window, "sidebarToggle"))
    assert sidebar.width() == 200
    drag_width(window, 320)
    click(window, find(window, "sidebarToggle"))
    click(window, find(window, "sidebarToggle"))
    assert sidebar.width() == pytest.approx(320)
    window.resize(1000, 600)
    QTest.qWait(50)
    assert find(window, "tagPanel").width() > 0
    assert not warnings, warnings


def test_split_toolbar_and_series_context_menu(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    panel = app.panelController
    workspace = app.workspaceController
    first_uid = records[0].series_instance_uid
    top_button_names = [
        "sidebarOpenFolder", "sidebarPacs", "openView-2d", "openView-mpr",
    ]
    bottom_button_names = ["openView-3d", "openView-montage", "openView-4d", "openView-tag", "openView-fusion"]
    button_names = top_button_names + bottom_button_names
    panel.selectSeries(first_uid)

    for width in [200, 300, 350]:
        drag_width(window, width)
        buttons = [find(window, name) for name in button_names]
        assert all(button.property("baseBorderWidth") == 0 for button in buttons)
        assert all(button.property("text") == "" for button in buttons)
        rows = [
            [find(window, name) for name in top_button_names],
            [find(window, name) for name in bottom_button_names],
        ]
        for row in rows:
            bounds = [
                (
                    button.mapToScene(QPointF(0, 0)).x(),
                    button.mapToScene(QPointF(button.width(), 0)).x(),
                )
                for button in row
            ]
            assert all(right + 3 <= next_left
                       for (_, right), (next_left, _) in zip(bounds, bounds[1:]))
        assert rows[1][0].mapToScene(QPointF(0, 0)).y() > rows[0][0].mapToScene(QPointF(0, 0)).y()
        assert find(window, "openView-montage").isEnabled()
        assert find(window, "openView-fusion").isEnabled()

    window.resize(1000, 600)
    QTest.qWait(40)
    right_click(window, find(window, "series-" + first_uid))
    assert panel.activeSeriesUid == first_uid
    action_codes = ["2d", "montage", "mpr", "fusion", "3d", "4d", "tag", "directory", "deidentify", "remove"]
    actions = {code: find(window, "seriesContextAction-" + code) for code in action_codes}
    assert all(action.height() <= 32 for action in actions.values())
    assert all(actions[code].property("actionEnabled")
               for code in ["2d", "montage", "mpr", "fusion", "3d", "tag", "directory", "deidentify", "remove"])
    assert all(not actions[code].property("actionEnabled")
               for code in ["4d"])
    assert not any(item.objectName() in {"seriesContextAction-compatibility", "seriesContextAction-compare"}
                   for item in descendants(window.contentItem()))
    for action in actions.values():
        top_left = action.mapToScene(QPointF(0, 0))
        bottom_right = action.mapToScene(QPointF(action.width(), action.height()))
        assert 0 <= top_left.x() < bottom_right.x() <= window.width()
        assert 0 <= top_left.y() < bottom_right.y() <= window.height()
    assert window.grabWindow().save(str(tmp_path / "dicom-series-context-menu.png"))

    click(window, actions["2d"])
    assert workspace.activeTabType == "2d"
    right_click(window, find(window, "series-" + first_uid))
    click(window, find(window, "seriesContextAction-mpr"))
    assert workspace.activeTabType == "mpr"
    right_click(window, find(window, "series-" + first_uid))
    click(window, find(window, "seriesContextAction-tag"))
    wait_until(lambda: workspace.activeTabType == "tag"
               and not workspace.activeTab.tagController.loading)
    tab_count = len(workspace.tabs)
    tag_tab = workspace.activeTab
    assert tab_count == 3
    right_click(window, find(window, "series-" + first_uid))
    click(window, find(window, "seriesContextAction-tag"))
    assert len(workspace.tabs) == tab_count and workspace.activeTab is tag_tab
    right_click(window, find(window, "series-" + first_uid))
    click(window, find(window, "seriesContextAction-remove"))
    assert not any(row["seriesInstanceUid"] == first_uid for row in panel.sidebarItems)
    assert len(workspace.tabs) == tab_count and workspace.activeTab is tag_tab
    assert records[0].first_file.exists()
    QTest.qWait(40)
    assert window.grabWindow().save(str(tmp_path / "dicom-series-removed.png"))
    assert not warnings, warnings


def test_mr_group_order_uses_numeric_time_echo_and_component_not_hashed_uid(tmp_path):
    from voxplane.model.dicom_types import MrParameters
    base = replace(make_series(tmp_path, 1), modality='MR', series_number=301)
    records = []
    for uid, time, echo, component in [('1', 10, 23, 'MAGNITUDE'), ('2', 2, 23, 'PHASE'),
                                     ('3', 2, 23, 'MAGNITUDE'), ('4', 2, 8, 'MAGNITUDE'),
                                     ('5', 1, 8, 'MAGNITUDE')]:
        instance = replace(base.instances[0], mr_parameters=MrParameters(
            temporal_position=time, echo_time=echo, component=component))
        records.append(replace(base, series_instance_uid=uid, instances=(instance,)))
    rows = build_sidebar_rows(records, '', set(), {})
    assert [row['seriesInstanceUid'] for row in rows if row['kind'] == 'series'] == ['5', '4', '3', '2', '1']
