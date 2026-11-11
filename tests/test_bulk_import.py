"""Large imports must stay cancellable, bounded and observable."""
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QObject, QPointF, QTimer, QUrl, QMetaObject
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from voxplane.core import dicom_scanner as scanner
from voxplane.core.local_import import LocalImportStore, ImportLimits, ImportCancelled, ImportErrorDetail
from voxplane.ui.workers.dicom_scan_worker import DicomScanWorker
from test_local_import import make_series
from test_pacs_qml import scene
from test_dicom_tags import wait_until, qt_app
from test_tag_qml import click


def test_twenty_thousand_files_do_not_rebuild_all_series_per_file(tmp_path, monkeypatch):
    instance = make_series(tmp_path, 1).instances[0]
    def read(path):
        index = int(path.stem)
        return replace(instance, path=path, sop_instance_uid=f"1.2.3.{index + 1}",
                       series_instance_uid=f"1.2.4.{index // 100 + 1}")
    monkeypatch.setattr(scanner, "_read_frames", lambda path: [read(path)])
    builds = []
    build = scanner._build_series_from_map
    def aggregate(*args, **kwargs):
        builds.append(len(args[0]))
        return build(*args, **kwargs)
    monkeypatch.setattr(scanner, "_build_series_from_map", aggregate)
    counts = []
    snapshots = list(scanner.DicomFolderScanner().scan_files(
        (tmp_path / f"{i}.dcm" for i in range(20_000)), folder=tmp_path,
        snapshot_interval=3600, progress=lambda total, *args: counts.append(total)))
    assert builds == [200]  # One final aggregation, not 20,000 growing copies.
    assert snapshots[-1].dicom_file_count == 20_000
    assert snapshots[-1].total_file_count == 20_000
    assert len(snapshots[-1].series) == 200 and counts[-1] == 20_000


def test_cancellation_keeps_every_already_read_instance(tmp_path, monkeypatch):
    instance = make_series(tmp_path, 1).instances[0]
    count = 0
    def read(path):
        nonlocal count
        count += 1
        return replace(instance, path=path, sop_instance_uid=f"1.2.3.{count}")
    monkeypatch.setattr(scanner, "_read_frames", lambda path: [read(path)])
    snapshots = list(scanner.DicomFolderScanner().scan_files(
        (tmp_path / f"{i}.dcm" for i in range(10_000)), folder=tmp_path,
        cancelled=lambda: count >= 1024, snapshot_interval=3600))
    assert len(snapshots) == 1 and snapshots[0].dicom_file_count == 1024


def test_empty_directory_tree_can_be_cancelled(tmp_path, monkeypatch):
    visited = 0
    def walk(*args, **kwargs):
        nonlocal visited
        for i in range(10_000):
            visited += 1
            yield str(tmp_path / str(i)), [], []
    monkeypatch.setattr(scanner.os, "walk", walk)
    messages = []
    with pytest.raises(ImportCancelled):
        LocalImportStore().prepare([tmp_path], cancelled=lambda: visited == 20, progress=messages.append)
    assert visited == 20 and "枚举" in messages[0]


def test_unreadable_directory_is_reported_instead_of_silently_skipped(tmp_path, monkeypatch):
    def walk(*args, onerror=None, **kwargs):
        onerror(PermissionError("blocked"))
        return iter(())
    monkeypatch.setattr(scanner.os, "walk", walk)
    with pytest.raises(ImportErrorDetail, match="访问权限"):
        LocalImportStore().prepare([tmp_path])


def test_worker_only_queues_one_preview_and_logs_unexpected_failures(tmp_path, monkeypatch, caplog):
    instance = make_series(tmp_path, 1).instances[0]
    monkeypatch.setattr(scanner, "_read_frames", lambda p: [replace(instance, path=p, sop_instance_uid=f"1.2.3.{int(p.stem) + 1}")])
    store = LocalImportStore()
    monkeypatch.setattr(store, "prepare", lambda *a, **k: [tmp_path / f"{i}.dcm" for i in range(200)])
    worker = DicomScanWorker([tmp_path], store)
    worker.process_report_interval = 0
    previews, final = [], []
    worker.process.connect(previews.append)
    worker.finished.connect(final.append)
    worker.run()  # No acknowledgement: a slow GUI must not accumulate previews.
    assert len(previews) == len(final) == 1
    assert final[0].dicom_file_count == 200
    monkeypatch.setattr(store, "prepare", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic failure")))
    errors = []
    worker.failed.connect(errors.append)
    worker.run()
    assert "应用日志" in errors[0] and "synthetic failure" in caplog.text


def task_dialog(window):
    dialog = window.findChild(QObject, "importTaskDialog")
    assert dialog is not None
    wait_until(lambda: dialog.property("visible"))
    return dialog


def test_import_task_reports_limit_and_retry_without_restoring_banner(scene, tmp_path):
    window, app, warnings = scene
    panel = app.panelController
    series = make_series(tmp_path, 3)
    panel._import_store.limits = ImportLimits(max_files=2)
    panel.importUrls([QUrl.fromLocalFile(str(i.path)) for i in series.instances])
    wait_until(lambda: not panel.scanning)
    dialog = task_dialog(window)
    assert panel.importError and "2 个上限" in panel.statusMessage
    QTest.qWait(4200)
    assert dialog.property("visible")  # Errors never auto-dismiss.
    panel._import_store.limits = ImportLimits()
    retry = dialog.findChild(QObject, "importTaskRetry")
    assert retry.isVisible() and retry.isEnabled()
    click(retry.window(), retry)
    wait_until(lambda: not panel.scanning)
    assert not panel.importError and panel.hasSeries
    wait_until(lambda: not dialog.property("visible"), timeout=6000)
    assert not warnings, warnings


@pytest.mark.parametrize("partial", [False, True])
def test_progress_task_keeps_gui_alive_and_cancel_is_visible(scene, tmp_path, monkeypatch, partial):
    window, app, warnings = scene
    panel = app.panelController
    entered, release = Event(), Event()
    prepare = panel._import_store.prepare
    def slow(*args, **kwargs):
        kwargs["progress"]("正在枚举文件 · 已发现 12,000 个文件")
        entered.set()
        assert release.wait(5)
        return prepare(*args, **kwargs)
    if partial:
        make_series(tmp_path, 3)
        read = scanner._read_frames
        def pause_after_read(path):
            frames = read(path)
            entered.set()
            assert release.wait(5)
            return frames
        monkeypatch.setattr(scanner, "_read_frames", pause_after_read)
    else:
        monkeypatch.setattr(panel._import_store, "prepare", slow)
    pulses = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: pulses.append(1))
    timer.start()
    try:
        panel.importUrls([QUrl.fromLocalFile(str(tmp_path))])
        wait_until(entered.is_set)
        dialog = task_dialog(window)
        wait_until(lambda: len(pulses) > 5)
        assert dialog.findChild(QObject, "importTaskProgress").property("indeterminate")
        button = dialog.findChild(QObject, "importTaskClose")
        click(button.window(), button)
        release.set()
        wait_until(lambda: not panel.scanning)
        assert "取消" in panel.statusMessage
        assert panel.hasSeries == partial
        assert panel.importTaskOpen == dialog.property("visible") == partial
        if partial:
            click(button.window(), button)
            wait_until(lambda: not panel.importTaskOpen)
    finally:
        release.set()
        timer.stop()
    assert not warnings, warnings


def test_many_small_archives_do_not_flood_gui_status_events(tmp_path, monkeypatch):
    import zipfile
    from voxplane.core import local_import
    monkeypatch.setattr(local_import.time, "monotonic", lambda: 100.0)
    archives = []
    for index in range(100):
        path = tmp_path / f"{index}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("file.dcm", b"not a DICOM")
        archives.append(path)
    messages = []
    store = LocalImportStore()
    try:
        assert len(store.prepare(archives, progress=messages.append)) == 100
        assert len(messages) == 1  # Enumeration/short archives share the same reporting interval.
    finally:
        store.cleanup()


def test_task_window_size_and_buttons_stay_fixed_for_long_progress_and_errors(scene, tmp_path):
    window, app, warnings = scene
    panel = app.panelController
    panel._set_scanning(True)
    panel._import_task_open = True
    panel.importTaskChanged.emit()
    dialog = task_dialog(window)
    area = dialog.findChild(QObject, "importTaskMessageArea")
    message = dialog.findChild(QObject, "importTaskMessage")
    close = dialog.findChild(QObject, "importTaskClose")
    popup = message.window()
    QTest.qWait(80)
    geometry = (dialog.property("width"), dialog.property("height"), popup.width(), popup.height())
    button_y = close.mapToScene(QPointF()).y()
    cases = [
        (True, False, "正在枚举文件 · 已发现 1 个文件"),
        (True, False, "正在解压文件 · 已发现 99,999 个文件 · 已解压 32,768.0 MiB"),
        (True, False, "正在读取影像 · 100,000 / 100,000 个文件\n识别 99,999 个 DICOM · 跳过 1 个文件"),
        (False, True, "无法读取：" + "很长的目录名称" * 80),
        (False, True, "Cannot read: " + "VeryLongPathWithoutAnySpaces/" * 60),
        (False, False, "已取消导入；已载入的序列仍可使用。"),
        (False, False, "已导入 1 个序列"),
    ]
    try:
        for index, (scanning, error, text) in enumerate(cases):
            panel._set_status(text, error)
            panel._set_scanning(scanning)
            QTest.qWait(60)
            assert (dialog.property("width"), dialog.property("height"), popup.width(), popup.height()) == geometry
            assert message.width() <= area.property("availableWidth")
            assert close.mapToScene(QPointF()).y() == button_y
            assert close.mapToScene(QPointF(close.width(), close.height())).y() < popup.height()
            if error:
                assert area.property("contentHeight") > area.height()  # Full error remains scrollable.
            frame = popup.grabWindow()
            for x, y in ((0, 0), (frame.width() - 1, 0), (0, frame.height() - 1),
                         (frame.width() - 1, frame.height() - 1)):
                assert frame.pixelColor(x, y) == QColor("#1b2128")  # No nested rounded frame.
            assert frame.save(str(tmp_path / f"import-state-{index}.png"))
        QMetaObject.invokeMethod(message, "selectAll")
        assert message.property("selectedText") == panel.statusMessage
        assert close.property("text") == "确定" and close.isVisible()
        click(popup, close)
        wait_until(lambda: not panel.importTaskOpen)
        assert not popup.isVisible()
    finally:
        panel._set_scanning(False)
        panel.closeImportTask()
    assert not warnings, warnings


@pytest.mark.parametrize("outcome", ["clean", "duplicate", "existing", "existing-copies", "existing-unreadable",
                                     "restored", "mixed-existing", "non-dicom", "empty", "bad-archive"])
def test_import_feedback_matches_outcome(scene, tmp_path, outcome):
    window, app, warnings = scene
    panel = app.panelController
    folder = tmp_path / "images"
    folder.mkdir()
    series = make_series(folder, 3)
    paths = [i.path for i in series.instances]
    dialog = window.findChild(QObject, "importTaskDialog")
    notice = window.findChild(QObject, "importAlreadyListedNotice")
    opened = []
    dialog.visibleChanged.connect(lambda: opened.append(dialog.property("visible")))
    # Deterministically exercise a scan that finishes before the progress delay.
    panel._progress_delay.setInterval(10_000)
    if outcome in ("existing", "existing-copies", "existing-unreadable", "restored", "mixed-existing"):
        previous = paths[:2] if outcome == "mixed-existing" else paths
        assert panel.importUrls([QUrl.fromLocalFile(str(p)) for p in previous])
        wait_until(lambda: not panel.scanning)
        assert not panel.importTaskOpen and not dialog.property("visible")
        if outcome == "restored":
            panel.clearSeries()
            assert not panel.hasSeries
    if outcome in ("duplicate", "existing-copies"):
        duplicate = folder / "copy.dcm"
        duplicate.write_bytes(paths[0].read_bytes())
        paths.append(duplicate)
    elif outcome in ("non-dicom", "existing-unreadable", "empty"):
        unreadable = folder / "not-an-image.txt"
        unreadable.write_text("not a DICOM")
        paths = [unreadable] if outcome == "empty" else paths + [unreadable]
    elif outcome == "bad-archive":
        archive = folder / "corrupt.zip"
        archive.write_bytes(b"not a ZIP archive")
        paths = [archive]
    assert panel.importUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    wait_until(lambda: not panel.scanning)
    if outcome in ("clean", "existing", "existing-copies", "restored"):
        assert not any(opened)
        assert not panel.importTaskOpen and not dialog.property("visible")
        assert not panel.importError and panel.hasSeries
        assert len(app._series_catalog.get_series(series.series_instance_uid).instances) == 3
        assert notice.property("visible") == (outcome in ("existing", "existing-copies"))
        if notice.property("visible"):
            assert notice.property("text") == "影像已在列表中"
            assert not window.property("shortcutPopupOpen")
            wait_until(lambda: not notice.property("visible"), timeout=5000)
    else:
        assert panel.importTaskOpen and dialog.property("visible")
        assert not notice.property("visible")
        assert panel.importError == (outcome in ("empty", "bad-archive"))
        if outcome == "mixed-existing":
            assert "已在列表中" in panel.statusMessage
            assert panel._last_import_snapshot.existing_file_count == 2
            assert len(app._series_catalog.get_series(series.series_instance_uid).instances) == 3
        elif outcome in ("duplicate", "non-dicom"):
            assert panel._last_import_snapshot.skipped_file_count == 1
        QTest.qWait(4200)
        assert panel.importTaskOpen and dialog.property("visible")
        button = dialog.findChild(QObject, "importTaskClose")
        assert button.property("text") == "确定"
        click(button.window(), button)
        wait_until(lambda: not panel.importTaskOpen and not dialog.property("visible"))
    assert not warnings, warnings
