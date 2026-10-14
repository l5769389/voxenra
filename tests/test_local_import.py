from pathlib import Path
import bz2
import gzip
import lzma
import os
import tarfile
import zipfile
from threading import Event

import py7zr
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from qt_dicom_viewer.core.local_import import (
    LocalImportStore,
    ImportLimits,
    ImportErrorDetail,
    ImportCancelled,
)
from test_dicom_tags import make_series as original_series, wait_until, qt_app
import pydicom
from qt_dicom_viewer.core.dicom_scanner import _read_instance, _build_series_record
from test_pet_fusion import paired_series
from test_pacs_qml import scene
from test_tag_qml import find, click
from rar_fixture import stored_rar


def make_series(root, count):
    series = original_series(root, count)
    for instance in series.instances:
        dataset = pydicom.dcmread(instance.path)
        dataset.PixelData = dataset.pixel_array[0].tobytes()
        dataset.NumberOfFrames = 1
        dataset.save_as(instance.path, enforce_file_format=True)
    return _build_series_record([_read_instance(i.path) for i in series.instances])


def make_archive(root, series, kind):
    target = root / ("scans." + kind)
    if kind == "rar":
        stored_rar(
            target,
            [
                ("影像/检查/" + i.path.name, i.path.read_bytes())
                for i in series.instances
            ],
        )
    elif kind == "zip":
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for i in series.instances:
                out.write(i.path, "影像/" + i.path.name)
    elif kind in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
        mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[
            kind
        ]
        with tarfile.open(target, mode) as out:
            folder = tarfile.TarInfo(".")
            folder.type = tarfile.DIRTYPE
            out.addfile(folder)
            for i in series.instances:
                out.add(i.path, arcname="影像/" + i.path.name)
    elif kind == "7z":
        with py7zr.SevenZipFile(target, "w") as out:
            for i in series.instances:
                out.write(i.path, "影像/" + i.path.name)
    else:
        with {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[kind](
            target, "wb"
        ) as out:
            out.write(series.instances[0].path.read_bytes())
    return target


@pytest.mark.parametrize('single_catalog_record', [False, True])
@pytest.mark.parametrize('phase_index', [0, 1])
def test_reimport_single_phase_preserves_cross_series_four_d(tmp_path, single_catalog_record, phase_index):
    from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
    from qt_dicom_viewer.ui.workers.dicom_scan_worker import DicomScanWorker
    from test_four_d import _cross_series_four_d

    records = _cross_series_four_d(tmp_path)
    base = records[:1] if single_catalog_record else records
    phase = records[phase_index]
    incoming_folder = tmp_path / 'incoming'
    incoming_folder.mkdir()
    files = []
    for instance in phase.instances:
        path = incoming_folder / instance.path.name
        path.write_bytes(instance.path.read_bytes())
        files.append(path)
    incoming = list(DicomFolderScanner().scan_files(files, folder=incoming_folder))[-1]
    worker = DicomScanWorker(files, base_series={r.series_instance_uid: r for r in base})
    try:
        merged = worker._merge_snapshot(incoming)
        assert len(merged.series) == 3
        assert merged.dicom_file_count == 2
        assert merged.existing_file_count == 2
        by_uid = {r.series_instance_uid: r for r in merged.series}
        for index, previous in enumerate(records):
            restored = by_uid[previous.series_instance_uid]
            assert restored.supports_four_d
            assert restored.phase_identifiers == (0, 1, 2)
            assert restored.initial_phase_identifier == index
            assert restored.series_description == previous.series_description
            assert restored.series_number == previous.series_number
            assert restored.dicom_file_count == 2
            assert [len(p.instances) for p in restored.phases] == [2, 2, 2]
            updated_phase = restored.phase_by_identifier(phase_index)
            assert all(i.path.parent == incoming_folder for i in updated_phase.instances)
    finally:
        worker.store.cleanup()


@pytest.mark.parametrize(
    "kind",
    ["rar", "zip", "7z", "tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "bz2", "xz"],
)
def test_archive_preparation_preserves_source_bytes_and_session_lifetime(
    tmp_path, kind
):
    series = make_series(tmp_path, 2)
    archive = make_archive(tmp_path, series, kind)
    before = archive.read_bytes()
    store = LocalImportStore()
    try:
        files = store.prepare([archive])
        assert len(files) == (1 if kind in ("gz", "bz2", "xz") else 2)
        assert [p.read_bytes() for p in files] == [
            i.path.read_bytes() for i in series.instances[: len(files)]
        ]
        assert all(p.is_relative_to(store.root) for p in files)
        assert archive.read_bytes() == before
        assert all(i.path.exists() for i in series.instances)
    finally:
        store.cleanup()
    assert all(not p.exists() for p in files) and archive.exists()


@pytest.mark.parametrize(
    "name",
    [
        "../outside.dcm",
        "/absolute.dcm",
        "C:\\outside.dcm",
        "..\\outside.dcm",
        "folder/file:ads",
        "NUL.dcm",
    ],
)
def test_archive_unsafe_paths_never_escape_or_leave_partial_cache(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("valid.dcm", b"first")
        out.writestr(name, b"do not write outside")
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail, match="路径"):
        store.prepare([archive])
    assert not list(store.root.iterdir())
    assert not (tmp_path / "outside.dcm").exists()


@pytest.mark.parametrize("kind", ["zip", "tar", "7z"])
def test_archive_links_are_rejected(tmp_path, kind):
    archive = tmp_path / ("links." + kind)
    if kind == "zip":
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as out:
            out.writestr(info, "../outside")
    elif kind == "tar":
        with tarfile.open(archive, "w") as out:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../outside"
            out.addfile(info)
    else:
        target = tmp_path / "file"
        target.write_bytes(b"source")
        link = tmp_path / "link"
        link.symlink_to(target)
        with py7zr.SevenZipFile(archive, "w") as out:
            out.write(link, "link")
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail, match="链接|特殊"):
        store.prepare([archive])
    assert not list(store.root.iterdir())


def test_cancel_size_limits_nested_archives_and_duplicates(tmp_path):
    series = make_series(tmp_path, 2)
    inner = make_archive(tmp_path, series, "zip")
    outer = tmp_path / "nested.zip"
    with zipfile.ZipFile(outer, "w") as out:
        out.write(inner, "inside.zip")
    store = LocalImportStore(tmp_path / "cache")
    assert len(store.prepare([outer])) == 2
    cancelled = Event()
    with pytest.raises(ImportCancelled):
        store.prepare(
            [inner], cancelled=cancelled.is_set, progress=lambda _: cancelled.set()
        )
    small = LocalImportStore(
        tmp_path / "small", limits=ImportLimits(max_total_bytes=32)
    )
    with pytest.raises(ImportErrorDetail, match="体积"):
        small.prepare([inner])
    assert not list(small.root.iterdir())
    shallow = LocalImportStore(tmp_path / "shallow", limits=ImportLimits(max_depth=1))
    with pytest.raises(ImportErrorDetail, match="嵌套"):
        shallow.prepare([outer])
    assert not list(shallow.root.iterdir())
    assert (
        len(
            store.prepare(
                [series.first_file, series.first_file, series.first_file.parent]
            )
        )
        == 2 + 4
    )  # includes archive-expanded duplicates; scanner de-duplicates SOPs


@pytest.mark.parametrize("kind", ["zip", "7z"])
def test_corrupt_and_encrypted_archives_report_errors(tmp_path, kind):
    archive = tmp_path / ("bad." + kind)
    archive.write_bytes(b"not an archive")
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail):
        store.prepare([archive])
    assert not list(store.root.iterdir())
    if kind == "7z":
        original = tmp_path / "source"
        original.write_bytes(b"example")
        with py7zr.SevenZipFile(archive, "w", password="secret") as out:
            out.write(original, "source")
        with pytest.raises(ImportErrorDetail, match="加密"):
            store.prepare([archive])
        assert not list(store.root.iterdir())


def drop_files(window, paths, *, actions=Qt.CopyAction, position=QPoint(550, 260)):
    mime = QMimeData()
    mime.setUrls(
        [p if isinstance(p, QUrl) else QUrl.fromLocalFile(str(p)) for p in paths]
    )
    enter = QDragEnterEvent(position, actions, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window, enter)
    accepted = enter.isAccepted()
    if not accepted:
        QApplication.sendEvent(window, QDragLeaveEvent())
        return False
    event = QDropEvent(QPointF(position), actions, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window, event)
    return event.isAccepted() and event.dropAction() == Qt.CopyAction


@pytest.mark.parametrize("kind", ["files", "folder", "zip", "7z", "rar"])
def test_real_qml_drop_imports_without_modifying_source_and_can_open_views(
    scene, tmp_path, kind
):
    window, app, warnings = scene
    folder = tmp_path / "input"
    folder.mkdir()
    series = make_series(folder, 2)
    originals = [i.path.read_bytes() for i in series.instances]
    if kind == "files":
        paths = [i.path for i in series.instances]
    elif kind == "folder":
        paths = [folder]
    else:
        paths = [make_archive(tmp_path, series, kind)]
    assert drop_files(window, paths, actions=Qt.CopyAction | Qt.MoveAction)
    wait_until(lambda: not app.panelController.scanning)
    assert not app.panelController.importError, app.panelController.statusMessage
    record = app._series_catalog.get_series(series.series_instance_uid)
    assert record and len(record.instances) == 2
    assert [i.path.read_bytes() for i in series.instances] == originals
    app.panelController.openSeriesView(series.series_instance_uid, "2d")
    wait_until(lambda: app.workspaceController.activeLoadState.status == "ready")
    view = app.workspaceController.activeViewport
    app.panelController.clearSeries()
    assert view.loadState == "ready" and all(i.path.exists() for i in record.instances)
    assert window.grabWindow().save(str(tmp_path / ("import-" + kind + ".png")))
    assert not warnings, warnings


def test_incremental_single_file_import_merges_series_and_rejects_remote_or_move_only(
    scene, tmp_path
):
    window, app, warnings = scene
    folder = tmp_path / "input"
    folder.mkdir()
    series = make_series(folder, 2)
    for i in series.instances:
        assert drop_files(window, [i.path])
        wait_until(lambda: not app.panelController.scanning)
    assert (
        app._series_catalog.get_series(series.series_instance_uid).dicom_file_count == 2
    )
    assert drop_files(window, [series.first_file])
    wait_until(lambda: not app.panelController.scanning)
    assert (
        app._series_catalog.get_series(series.series_instance_uid).dicom_file_count == 2
    )
    assert not drop_files(window, [QUrl("https://example.test/study.zip")])
    assert not drop_files(window, [series.first_file], actions=Qt.MoveAction)
    assert not warnings, warnings


def test_busy_drop_cancel_failure_and_manual_file_selection(
    scene, tmp_path, monkeypatch
):
    window, app, warnings = scene
    series = make_series(tmp_path, 2)
    panel = app.panelController
    entered, release = Event(), Event()
    prepare = panel._import_store.prepare

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(panel._import_store, "prepare", slow)
    assert drop_files(window, [series.first_file])
    wait_until(entered.is_set)
    assert not drop_files(window, [series.first_file])
    click(window, find(window, "sidebarOpenFolder"))
    release.set()
    wait_until(lambda: not panel.scanning)
    assert "取消" in panel.statusMessage and not panel.hasSeries
    monkeypatch.setattr(panel._import_store, "prepare", prepare)
    monkeypatch.setattr(
        "qt_dicom_viewer.ui.controller.panel_controller.select_import_paths",
        lambda *args: [str(i.path) for i in series.instances],
    )
    click(window, find(window, "homeOpenImport"))
    wait_until(lambda: not panel.scanning)
    assert panel.hasSeries and not panel.importError
    bad = tmp_path / "corrupt.zip"
    bad.write_bytes(b"bad")
    assert drop_files(window, [bad])
    wait_until(lambda: not panel.scanning)
    assert panel.importError and panel.hasSeries
    from test_tag_qml import descendants
    assert not any(i.objectName() == "localImportBanner" for i in descendants(window.contentItem()))
    assert not warnings, warnings


def test_reimport_after_sidebar_clear_preserves_open_series(scene, tmp_path):
    window, app, warnings = scene
    series = make_series(tmp_path, 3)
    assert drop_files(window, [i.path for i in series.instances])
    wait_until(lambda: not app.panelController.scanning)
    app.panelController.openSeriesView(series.series_instance_uid, "2d")
    wait_until(lambda: app.workspaceController.activeLoadState.status == "ready")
    view = app.workspaceController.activeViewport
    app.panelController.clearSeries()
    assert drop_files(window, [series.first_file])
    wait_until(lambda: not app.panelController.scanning)
    assert (
        app._series_catalog.get_series(series.series_instance_uid).dicom_file_count == 3
    )
    assert view.loadState == "ready" and app.workspaceController.activeViewport is view
    assert not warnings, warnings


def test_shutdown_cancels_extraction_before_removing_cache(
    scene, tmp_path, monkeypatch
):
    window, app, warnings = scene
    series = make_series(tmp_path, 2)
    archive = make_archive(tmp_path, series, "zip")
    panel = app.panelController
    cache = panel._import_store.root
    entered = Event()
    prepare = panel._import_store.prepare

    def slow(paths, *, cancelled, progress):
        def block(message):
            entered.set()
            # Simulate an extraction boundary while the GUI closes the app.
            while not cancelled():
                Event().wait(0.005)

        return prepare(paths, cancelled=cancelled, progress=block)

    monkeypatch.setattr(panel._import_store, "prepare", slow)
    assert drop_files(window, [archive])
    wait_until(entered.is_set)
    app.shutdown()
    assert panel._scan_thread is None or not panel._scan_thread.isRunning()
    assert not cache.exists() and archive.exists()
    assert not warnings, warnings


@pytest.mark.skipif(
    os.environ.get("VOXENRA_NATIVE_QA") != "1",
    reason="Requires a native desktop OpenGL window",
)
@pytest.mark.parametrize("kind", ["ct", "pet", "fusion"])
def test_native_volume_receives_file_drop(scene, paired_series, tmp_path, kind, monkeypatch):
    from qt_dicom_viewer.model import DicomFolderScanSnapshot

    window, app, warnings = scene
    _, ct, pet = paired_series
    app.panelController.acceptPacsImport(
        DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet])
    )
    workspace = app.workspaceController
    if kind == "fusion":
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        wait_until(lambda: workspace.activeLoadState.status == "ready")
        workspace.activeTab.openVolumeView()
    else:
        record = ct if kind == "ct" else pet
        workspace.createTab(record.series_instance_uid, kind, "3d")
    wait_until(lambda: workspace.activeLoadState.status == "ready")
    view = workspace.activeViewport
    wait_until(lambda: view._host is not None and view._host.isVisible())
    folder = tmp_path / "drop"
    folder.mkdir()
    incoming = make_series(folder, 2)
    archive = make_archive(tmp_path, incoming, "rar")
    widget = view._host.vtk_widget
    assert drop_files(
        widget,
        [archive],
        actions=Qt.CopyAction | Qt.MoveAction,
        position=QPoint(30, 30),
    )
    wait_until(lambda: not app.panelController.scanning)
    assert not app.panelController.importError, app.panelController.statusMessage
    assert (
        app._series_catalog.get_series(incoming.series_instance_uid).dicom_file_count
        == 2
    )
    assert workspace.activeViewport is view and view.loadState == "ready"
    # The single mixed picker must open above VTK from either rail width.
    from PySide6.QtCore import QTimer
    from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
    errors, opened = [], []
    for entry in ("sidebarOpenFolder", "compactSidebarImport"):
        if entry == "compactSidebarImport":
            click(window, find(window, "sidebarToggle"))
        def inspect_picker():
            dialog = QApplication.activeModalWidget()
            try:
                assert isinstance(dialog, LocalImportDialog)
                assert dialog.isVisible()
                opened.append(entry)
                assert dialog.grab().save(str(tmp_path / (entry + "-picker.png")))
            except BaseException as error:
                errors.append(error)
            finally:
                if dialog is not None:
                    dialog.reject()
        QTimer.singleShot(250, inspect_picker)
        click(window, find(window, entry))
    assert not errors, errors
    assert opened == ["sidebarOpenFolder", "compactSidebarImport"]
    assert workspace.activeViewport is view and view.loadState == "ready"
    assert not warnings, warnings
