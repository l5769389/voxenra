"""Dialog keyboard actions use the visible controls and respect the current task state."""
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtTest import QSignalSpy, QTest

from qt_dicom_viewer.core.app_updates import parse_release
from qt_dicom_viewer.core.local_import import ImportLimits
from qt_dicom_viewer.core.series_export import export_series
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from test_app_updates import Network, release_payload
from test_bulk_import import task_dialog
from test_dicom_tags import make_series, qt_app, wait_until
from test_export_qml import load_series
from test_pacs_qml import scene
from test_pet_fusion import paired_series
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, find, type_text


def test_export_enter_starts_then_acknowledges_and_escape_discards_reopened_form(scene, tmp_path):
    window, app, warnings = scene
    load_series(app, tmp_path)
    export = app.seriesExportController
    destination = tmp_path / "exports"
    app.settingsController.setValue("export", "directory", str(destination))
    click(window, find(window, "sidebarExport"))
    dialog = window.findChild(QObject, "exportDialog")
    wait_until(lambda: dialog.property("opened") and dialog.property("activeFocus"))
    assert find(window, "startExport").isEnabled()
    dismiss = find(window, "cancelExport")
    assert dismiss.property("dialogKeyHint") == "Esc"
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: bool(export.outputDirectory))
    output = Path(export.outputDirectory)
    assert len(list(output.glob("*.dcm"))) == 2
    assert dismiss.property("dialogKeyHint") == "Enter / Esc"
    QTest.keyClick(window, Qt.Key_Enter)
    assert not export.dialogOpen and len(list(destination.iterdir())) == 1

    click(window, find(window, "sidebarExport"))
    assert dismiss.property("dialogKeyHint") == "Esc"
    combo = find(window, "exportFormat")
    click(window, combo)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    assert combo.property("currentIndex") == 1
    assert export.dialogOpen and not export.busy and not export.outputDirectory
    QTest.keyClick(window, Qt.Key_Escape)
    assert not export.dialogOpen and len(list(destination.iterdir())) == 1
    assert not warnings, warnings


def test_export_escape_cancels_running_export_before_dismissing(scene, tmp_path, monkeypatch):
    window, app, warnings = scene
    series = load_series(app, tmp_path)
    export = app.seriesExportController
    destination = tmp_path / "exports"
    app.settingsController.setValue("export", "directory", str(destination))
    entered, release = Event(), Event()

    def wait_for_cancel(request, *, cancel, progress):
        entered.set()
        assert release.wait(10)
        return export_series(request, cancel=cancel, progress=progress)

    monkeypatch.setattr("qt_dicom_viewer.ui.controller.series_export_controller.export_series", wait_for_cancel)
    export.openSeries(series.series_instance_uid, False)
    try:
        QTest.keyClick(window, Qt.Key_Return)
        wait_until(entered.is_set)
        assert not find(window, "startExport").isEnabled()
        QTest.keyClick(window, Qt.Key_Escape)
        assert export.busy and export.dialogOpen and export._cancel.is_set()
    finally:
        release.set()
        wait_until(lambda: not export.busy)
    assert not export.outputDirectory and not list(destination.glob("*/*.dcm"))
    QTest.keyClick(window, Qt.Key_Escape)
    assert not export.dialogOpen
    assert not warnings, warnings


def test_feedback_multiline_enter_edits_and_subject_enter_opens_one_draft(scene, monkeypatch):
    window, app, warnings = scene
    urls = []
    monkeypatch.setattr("qt_dicom_viewer.ui.controller.feedback_controller.QDesktopServices.openUrl",
                        lambda url: urls.append(url) or True)
    app.workspaceController.openSettings()
    click(window, find(window, "settingsFeedback"))
    description = find(window, "feedbackDescription")
    type_text(window, description, "Steps")
    QTest.keyClick(window, Qt.Key_Return)
    assert description.property("text") == "Steps\n" and not urls
    type_text(window, find(window, "feedbackSubject"), "Nested field")
    QTest.keyClick(window, Qt.Key_Enter)
    assert len(urls) == 1 and urls[0].host() == "github.com"
    QTest.keyClick(window, Qt.Key_Escape)
    assert not window.findChild(QObject, "feedbackDialog").property("visible")
    assert not warnings, warnings


def test_pacs_form_return_validates_and_keypad_enter_saves_once(scene):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    app.settingsController.selectCategory("sources")
    click(window, find(window, "pacsAddProfile"))
    name = find(window, "pacsProfileName")
    save = find(window, "pacsSaveProfile")
    presses = QSignalSpy(save.clicked)
    type_text(window, name, "Local test")
    validation = QSignalSpy(app.pacsController.stateChanged)
    QTest.keyClick(window, Qt.Key_Return)
    assert validation.count() == 1 and presses.count() == 1
    assert find(window, "pacsProfileMessage").property("text")
    assert not app.pacsController.profiles
    type_text(window, find(window, "pacsProfileUrl"), "http://127.0.0.1:8042/dicom-web")
    QTest.keyClick(window, Qt.Key_Enter)
    assert presses.count() == 2 and len(app.pacsController.profiles) == 1
    assert not save.isVisible()
    assert not warnings, warnings


def test_import_enter_never_cancels_progress_and_escape_requests_cancellation(scene, tmp_path, monkeypatch):
    window, app, warnings = scene
    panel = app.panelController
    entered, release = Event(), Event()
    prepare = panel._import_store.prepare

    def wait_for_cancel(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(panel._import_store, "prepare", wait_for_cancel)
    try:
        assert panel.importUrls([QUrl.fromLocalFile(str(tmp_path))])
        wait_until(entered.is_set)
        dialog = task_dialog(window)
        popup = dialog.findChild(QObject, "importTaskClose").window()
        QTest.keyClick(popup, Qt.Key_Enter)
        assert not panel._scan_thread.isInterruptionRequested()
        QTest.keyClick(popup, Qt.Key_Escape)
        assert panel._scan_thread.isInterruptionRequested() and dialog.property("visible")
    finally:
        release.set()
        wait_until(lambda: not panel.scanning)
    assert not dialog.property("visible") and not panel.importTaskOpen
    assert not warnings, warnings


def test_import_enter_retries_failed_import(scene, tmp_path):
    window, app, warnings = scene
    panel = app.panelController
    series = make_series(tmp_path, 2)
    panel._import_store.limits = ImportLimits(max_files=1)
    assert panel.importUrls([QUrl.fromLocalFile(str(i.path)) for i in series.instances])
    wait_until(lambda: not panel.scanning and panel.importError)
    dialog = task_dialog(window)
    retry = dialog.findChild(QObject, "importTaskRetry")
    assert retry.isVisible() and retry.isEnabled()
    panel._import_store.limits = ImportLimits()
    QTest.keyClick(retry.window(), Qt.Key_Enter)
    wait_until(lambda: not panel.scanning and panel.hasSeries)
    assert not panel.importError
    assert not warnings, warnings


def test_update_enter_checks_escape_cancels_and_available_enter_dismisses(scene):
    window, app, warnings = scene
    updater = app.updateController
    updater._network = Network()
    updater.showDialog.emit()
    dialog = window.findChild(QObject, "applicationUpdateDialog")
    assert dialog.property("visible")
    QTest.keyClick(window, Qt.Key_Return)
    assert updater.state == "checking"
    QTest.keyClick(window, Qt.Key_Enter)
    assert updater.state == "checking" and dialog.property("visible")
    QTest.keyClick(window, Qt.Key_Escape)
    assert updater.state == "idle" and not dialog.property("visible")

    updater._release = parse_release(release_payload(), "1.6.0", "macos")
    updater._set_state("available", "")
    updater.showDialog.emit()
    assert find(window, "applicationUpdateAction").isVisible()
    QTest.keyClick(window, Qt.Key_Enter)
    assert not dialog.property("visible") and updater.state == "available"
    assert app.settingsController.section("updates")["dismissedVersion"] == "1.7.0"
    assert not warnings, warnings


def test_workspace_enter_saves_then_escape_closes(sidebar_scene, tmp_path):
    window, app, _, warnings = sidebar_scene
    manager = app.workspaceDocumentController
    path = tmp_path / "keyboard.voxworkspace"
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    manager.mark_dirty()
    click(window, find(window, "sidebarWorkspace"))
    dialog = window.findChild(QObject, "workspaceDocumentDialog")
    popup = dialog.findChild(QObject, "saveWorkspace").window()
    assert manager.dirty
    QTest.keyClick(popup, Qt.Key_Enter)
    wait_until(lambda: not manager.busy and not manager.dirty)
    assert path.is_file() and not manager.isError
    QTest.keyClick(popup, Qt.Key_Escape)
    assert not dialog.property("visible")
    assert not warnings, warnings


def test_workspace_recovery_enter_dismisses_without_consuming_snapshot(sidebar_scene, tmp_path):
    window, app, _, warnings = sidebar_scene
    manager = app.workspaceDocumentController
    recovery = tmp_path / "recovery.voxworkspace"
    manager._recovery_path = recovery
    recovery.write_bytes(b"previous recovery")
    manager._previous_recovery = True
    manager.changed.emit()
    click(window, find(window, "sidebarWorkspace"))
    dialog = window.findChild(QObject, "workspaceDocumentDialog")
    recover = dialog.findChild(QObject, "recoverWorkspace")
    assert recover.isVisible() and recover.isEnabled()
    QTest.keyClick(recover.window(), Qt.Key_Return)
    assert not dialog.property("visible")
    assert manager.recoveryAvailable and recovery.read_bytes() == b"previous recovery"
    assert not warnings, warnings


def test_compare_default_requires_selection_and_opens_only_once(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    first, partner = (s.series_instance_uid for s in records[:2])
    compare = app.panelController.compareController
    opened = QSignalSpy(compare.openRequested)
    compare.request(first)
    assert not find(window, "confirmCompare").isEnabled()
    QTest.keyClick(window, Qt.Key_Return)
    assert compare.dialogOpen and opened.count() == 0
    click(window, find(window, "compareCandidate-" + partner))
    QTest.keyClick(window, Qt.Key_Enter)
    assert opened.count() == 1 and opened.at(0) == [first, partner]
    assert not compare.dialogOpen
    assert not warnings, warnings


def test_fusion_enter_respects_identity_confirmation(scene, paired_series, tmp_path):
    window, app, warnings = scene
    _, ct, pet = paired_series
    pet = replace(pet, study_instance_uid="1.2.3.99")
    snapshot = DicomFolderScanSnapshot(tmp_path, 2, 2, 0, [ct, pet])
    panel = app.panelController
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    panel.selectSeries(ct.series_instance_uid)
    panel.requestFusionView()
    click(window, find(window, "fusionCandidate-" + pet.series_instance_uid))
    opened = QSignalSpy(panel.fusionCreateRequested)
    assert not find(window, "confirmFusion").isEnabled()
    QTest.keyClick(window, Qt.Key_Return)
    assert panel.fusionDialogOpen and opened.count() == 0
    click(window, find(window, "fusionIdentityConfirmation"))
    QTest.keyClick(window, Qt.Key_Enter)
    assert opened.count() == 1 and opened.at(0) == [ct.series_instance_uid, pet.series_instance_uid]
    assert not panel.fusionDialogOpen
    assert not warnings, warnings
