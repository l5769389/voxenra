"""Actual dialog geometry, action semantics and closure across content states."""
import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app
from test_pacs_qml import scene
from test_tag_qml import find, click
from test_export_qml import load_series


def bounds(item):
    return (item.mapToScene(QPointF()), item.mapToScene(QPointF(item.width(), item.height())))


def dialog_controls(window, name, close_name, cancel_name=None, primary_name=None):
    dialog = window.findChild(QObject, name)
    close = find(window, close_name)
    background = dialog.property("background")
    top, bottom = bounds(background)
    ctop, cbottom = bounds(close)
    assert ctop.y() == pytest.approx(top.y() + 16)
    assert cbottom.x() == pytest.approx(bottom.x() - 16)
    if primary_name:
        primary = find(window, primary_name)
        ptop, pbottom = bounds(primary)
        assert pbottom.x() == pytest.approx(bottom.x() - 16)
        assert pbottom.y() == pytest.approx(bottom.y() - 16)
        if cancel_name:
            cancel = find(window, cancel_name)
            ltop, lbottom = bounds(cancel)
            assert ltop.y() == pytest.approx(ptop.y())
            assert lbottom.x() + 8 == pytest.approx(ptop.x())
            assert cancel.property("normalColor") != primary.property("normalColor")
    return dialog, close


@pytest.mark.parametrize("size", [(1000, 600), (1400, 900)])
def test_export_footer_fixed_for_long_messages_and_close_does_not_cancel_busy_task(scene, tmp_path, size):
    window, app, warnings = scene
    window.resize(*size)
    load_series(app, tmp_path)
    click(window, find(window, "sidebarExport"))
    export = app.seriesExportController
    dialog, close = dialog_controls(window, "exportDialog", "exportDialogClose", "cancelExport", "startExport")
    buttons = [find(window, name) for name in ("cancelExport", "startExport")]
    original = [bounds(item) for item in buttons]
    try:
        app.settingsController.setValue("export", "directory", "/".join(["很长的导出目录"] * 60))
        export._message = "无法导出：" + "说明内容 " * 300
        export.changed.emit()
        QTest.qWait(80)
        assert [bounds(item) for item in buttons] == original
        export._busy = True
        export.changed.emit()
        QTest.qWait(30)
        assert not close.isEnabled() and not buttons[1].isEnabled()
        click(window, close)
        assert dialog.property("visible") and not export._cancel.is_set()
        click(window, buttons[0])
        assert export._cancel.is_set() and dialog.property("visible")
        export._busy = False
        export.changed.emit()
        QTest.qWait(30)
        assert [bounds(item) for item in buttons] == original
        assert window.grabWindow().save(str(tmp_path / "export-fixed-actions.png"))
        click(window, close)
        assert not export.dialogOpen
    finally:
        export._busy = False
        export.changed.emit()
    assert not warnings, warnings


def test_pacs_profile_footer_and_destructive_confirmation(scene, tmp_path):
    window, app, warnings = scene
    window.resize(1000, 600)
    app.workspaceController.openSettings()
    click(window, find(window, "pacsAddProfile"))
    dialog, close = dialog_controls(window, "pacsProfileDialog", "pacsProfileDialogClose", "pacsCancelProfile", "pacsSaveProfile")
    save = find(window, "pacsSaveProfile")
    original = bounds(save)
    click(window, save)  # Invalid input displays an error without moving actions.
    assert dialog.property("visible") and not app.pacsController.profiles
    assert bounds(save) == original
    assert window.grabWindow().save(str(tmp_path / "pacs-profile-actions.png"))
    click(window, close)
    assert not dialog.property("visible")

    assert app.pacsController.saveProfile({"name": "Local test", "url": "http://127.0.0.1:8042"})
    profile_id = app.pacsController.profiles[0]["id"]
    click(window, find(window, "pacsDelete-" + profile_id))
    dialog, close = dialog_controls(window, "deletePacsDialog", "deletePacsDialogClose", "cancelDeletePacs", "confirmDeletePacs")
    assert find(window, "confirmDeletePacs").property("actionRole") == "danger"
    assert window.grabWindow().save(str(tmp_path / "pacs-delete-actions.png"))
    click(window, close)
    assert len(app.pacsController.profiles) == 1
    click(window, find(window, "pacsDelete-" + profile_id))
    QTest.keyClick(window, Qt.Key_Escape)
    assert len(app.pacsController.profiles) == 1 and not dialog.property("visible")
    click(window, find(window, "pacsDelete-" + profile_id))
    QTest.keyClick(window, Qt.Key_Return)
    assert not app.pacsController.profiles and not dialog.property("visible")
    assert not warnings, warnings
