from pathlib import Path

import pydicom
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.model import DicomFolderScanSnapshot
from test_dicom_tags import qt_app, make_series, wait_until
from test_pacs_qml import scene
from test_series_sidebar import right_click
from test_tag_qml import find, click, type_text


def load_series(app, tmp_path):
    series = make_series(tmp_path, 2)
    snapshot = DicomFolderScanSnapshot(tmp_path, 2, 2, 0, [series])
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    app.panelController.selectSeries(series.series_instance_uid)
    return series


def test_export_dialog_defaults_formats_and_right_click_whole_series(scene, tmp_path, monkeypatch):
    window, app, warnings = scene
    assert not find(window, "sidebarExport").isEnabled()
    series = load_series(app, tmp_path)
    app.settingsController.setValue("export", "directory", str(tmp_path / "exports"))
    click(window, find(window, "sidebarExport"))
    assert app.seriesExportController.dialogOpen
    checkbox = find(window, "exportAnonymous")
    assert checkbox.property("checked") and checkbox.isEnabled()
    click(window, checkbox)
    assert not checkbox.property("checked")
    click(window, find(window, "startExport"))
    wait_until(lambda: not app.seriesExportController.busy)
    output = Path(app.seriesExportController.outputDirectory)
    assert len(list(output.glob("*.dcm"))) == 2
    revealed = []
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.series_export_controller.reveal_path', lambda path: revealed.append(path) or True)
    QTest.qWait(30)
    link = find(window, 'exportOutputDirectory')
    assert link.property('text') == str(output)
    click(window, link)
    assert revealed == [str(output)]
    assert pydicom.dcmread(next(output.iterdir())).PatientName != "ANONYMOUS"
    click(window, find(window, "cancelExport"))
    QTest.qWait(100)
    right_click(window, find(window, "series-" + series.series_instance_uid))
    click(window, find(window, "seriesContextAction-deidentify"))
    assert app.seriesExportController.dialogOpen and app.seriesExportController.anonymousLocked
    assert checkbox.property("checked") and not checkbox.isEnabled()
    combo = find(window, "exportFormat")
    click(window, combo)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    assert combo.property("currentIndex") == 1
    window.resize(1000, 600)
    QTest.qWait(80)
    for name in ("exportFormat", "exportAnonymous", "cancelExport", "startExport"):
        item = find(window, name)
        top = item.mapToScene(QPointF(0, 0))
        bottom = item.mapToScene(QPointF(item.width(), item.height()))
        assert 0 <= top.x() < bottom.x() <= window.width()
        assert 0 <= top.y() < bottom.y() <= window.height()
    assert window.grabWindow().save(str(tmp_path / "dicom-export-dialog.png"))
    click(window, find(window, "startExport"))
    wait_until(lambda: not app.seriesExportController.busy)
    assert app.seriesExportController.outputDirectory
    output = Path(app.seriesExportController.outputDirectory)
    assert len(list(output.glob("*.png"))) == 4
    assert app.seriesExportController.completedCount == app.seriesExportController.totalCount == 4
    QTest.qWait(50)
    assert window.grabWindow().save(str(tmp_path / "dicom-export-complete.png"))
    click(window, find(window, "cancelExport"))
    QTest.qWait(100)
    click(window, find(window, "sidebarExport"))
    assert checkbox.property("checked") and checkbox.isEnabled()
    click(window, find(window, 'seriesExportManualLink'))
    wait_until(lambda: app.workspaceController.activeTabType == 'manual')
    assert not app.seriesExportController.dialogOpen
    assert app.workspaceController.manualController.chapterId == 'export'
    assert not warnings, warnings


def test_export_settings_ui_saves_destination_and_restores_default(scene, tmp_path):
    window, app, warnings = scene
    app.workspaceController.openSettings()
    QTest.qWait(50)
    click(window, find(window, "settingsCategory-export"))
    field = find(window, "exportDirectoryField")
    path = str(tmp_path / "new-export-location")
    type_text(window, field, path)
    QTest.keyClick(window, Qt.Key_Tab)
    assert app.settingsController.exportDirectory == path
    assert field.property("text") == path
    window.resize(1000, 600)
    QTest.qWait(50)
    assert window.grabWindow().save(str(tmp_path / "dicom-export-settings.png"))
    click(window, find(window, "resetDisplaySettings"))
    click(window, find(window, 'confirmSettingsReset'))
    assert field.property("text") == app.settingsController.defaultExportDirectory
    assert not warnings, warnings
