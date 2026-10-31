from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_pacs import pacs_server, STUDY, SERIES
from test_tag_qml import descendants, find, click, type_text


@pytest.fixture
def scene(qt_app, tmp_path):
    provider = DicomImageProvider()
    controller = AppController(provider, settings_path=tmp_path / "settings.json", pacs_config_path=tmp_path / "pacs.json", pacs_import_root=tmp_path / "imports")
    engine = QQmlApplicationEngine()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    engine.addImageProvider("navigation", SvgIconProvider())
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.addImageProvider("dicom", provider)
    engine.rootContext().setContextProperty("appController", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/Main.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    QTest.qWait(50)
    try:
        yield window, controller, warnings
    finally:
        window.hide()
        controller.shutdown()
        # In tests there is no QApplication.exec() between engine lifetimes.
        # Destroy the scene before its context objects and drain deferred Qt
        # deletions before the next parametrized case constructs a new scene.
        delete(window)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        delete(engine)
        delete(controller)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_ui_configure_test_save_query_and_import(scene, pacs_server, tmp_path):
    window, app, warnings = scene
    pacs, workspace = app.pacsController, app.workspaceController
    assert find(window, "homeOpenPacs").isEnabled()
    click(window, find(window, "sidebarSettings"))
    assert workspace.activeTabType == "settings"
    click(window, find(window, "sidebarSettings"))
    assert len(workspace.tabs) == 1
    click(window, find(window, "pacsAddProfile"))
    QTest.qWait(100)
    type_text(window, find(window, "pacsProfileName"), "Orthanc Local")
    type_text(window, find(window, "pacsProfileUrl"), pacs_server.url)
    click(window, find(window, "pacsTestDraft"))
    wait_until(lambda: not pacs.busy)
    assert "连接成功" in pacs.message
    assert not pacs.profiles  # Testing a draft does not save it.
    click(window, find(window, "pacsSaveProfile"))
    QTest.qWait(100)
    assert len(pacs.profiles) == 1 and pacs.defaultName == "Orthanc Local"
    screenshot(window, tmp_path, "settings")
    click(window, find(window, "sidebarPacs"))
    assert workspace.activeTabType == "pacs"
    click(window, find(window, "pacsQueryStudies"))
    wait_until(lambda: not pacs.busy)
    click(window, find(window, "pacsStudy-" + STUDY))
    wait_until(lambda: not pacs.busy)
    click(window, find(window, "pacsSeries-" + SERIES))
    assert pacs.selectedCount == 1
    screenshot(window, tmp_path, "browser")
    for width, height in [(1280, 720), (1440, 900)]:
        window.resize(width, height)
        QTest.qWait(80)
        for name in ("pacsQueryStudies", "pacsStudiesList", "pacsSeriesList", "pacsImportSelected"):
            control = find(window, name)
            p1 = control.mapToScene(QPointF(0, 0))
            p2 = control.mapToScene(QPointF(control.width(), control.height()))
            assert 0 <= p1.x() < p2.x() <= width
            assert 0 <= p1.y() < p2.y() <= height
        screenshot(window, tmp_path, f"browser-{width}")
    click(window, find(window, "pacsImportSelected"))
    wait_until(lambda: not pacs.busy)
    assert not pacs.isError, pacs.message
    assert workspace.activeTabType == "2d"
    assert len(app.panelController.seriesItems) == 1
    assert app.panelController.activeSeriesUid == SERIES
    assert app._series_catalog.get_series(SERIES).dicom_file_count == 3
    # Settings and PACS are real tabs and do not create/render image viewports.
    click(window, find(window, "sidebarSettings"))
    assert workspace.activeViewport is None and workspace.currentTabAllViewports == []
    assert not any(item.objectName() == "rightPanel" and item.isVisible() for item in descendants(window.contentItem()))
    window.resize(1000, 600)
    QTest.qWait(80)
    screenshot(window, tmp_path, "settings-1000")
    workspace.closeTab("workspace-settings")
    workspace.closeTab("workspace-pacs")
    QTest.qWait(80)
    assert workspace.activeTabType == "2d"
    assert not warnings, warnings


def screenshot(window, tmp_path, name):
    QTest.qWait(50)
    shot = window.grabWindow()
    assert not shot.isNull()
    assert shot.save(str(tmp_path / (name + ".png")))


def test_sources_visibility_and_unconfigured_home(scene):
    window, app, warnings = scene
    click(window, find(window, "homeOpenPacs"))
    click(window, find(window, "pacsConfigureEmpty"))
    assert app.workspaceController.activeTabType == "settings"
    click(window, find(window, "sidebarToggle"))
    assert find(window, "compactSidebarImport").isVisible()
    assert find(window, "compactSidebarPacs").isVisible()
    click(window, find(window, "enablePacsSource"))
    assert not any(i.objectName() == "compactSidebarPacs" and i.isVisible() for i in descendants(window.contentItem()))
    assert not app.pacsController.pacsEnabled
    assert not any(item.objectName() == "sidebarPacs" and item.isVisible() for item in descendants(window.contentItem()))
    click(window, find(window, "enableLocalSource"))
    assert app.pacsController.localEnabled  # Last source cannot be disabled.
    assert find(window, "enableLocalSource").property("checked") is True
    click(window, find(window, "enablePacsSource"))
    click(window, find(window, "enableLocalSource"))
    assert not app.pacsController.localEnabled and app.pacsController.pacsEnabled
    assert find(window, "compactSidebarPacs").isVisible()
    assert not any(i.objectName() == "compactSidebarImport" and i.isVisible() for i in descendants(window.contentItem()))
    assert not any(item.objectName() == "sidebarOpenFolder" and item.isVisible() for item in descendants(window.contentItem()))
    assert not warnings, warnings


def test_series_selection_and_status_updates_preserve_scroll(scene, pacs_server):
    from PySide6.QtCore import QMetaObject, Q_ARG
    from test_pacs import element
    window, app, warnings = scene
    pacs = app.pacsController
    pacs_server.series_rows = [{"0020000E": element("UI", SERIES + f".{i}"),
                               "0008103E": element("LO", f"Series {i}"),
                               "00080060": element("CS", "CT"),
                               "00200011": element("IS", i),
                               "00201209": element("IS", 3)} for i in range(30)]
    pacs.saveProfile({"name": "PACS", "url": pacs_server.url})
    app.workspaceController.openPacs()
    pacs.queryStudies({}, 50)
    wait_until(lambda: not pacs.busy)
    pacs.selectStudy(STUDY)
    wait_until(lambda: not pacs.busy)
    QTest.qWait(50)
    view = find(window, "pacsSeriesList")
    QMetaObject.invokeMethod(view, "positionViewAtIndex", Q_ARG(int, 25), Q_ARG(int, 1))
    QTest.qWait(50)
    before = view.property("contentY")
    assert before > 1000
    click(window, find(window, "pacsSeries-" + SERIES + ".25"))
    assert pacs.selectedCount == 1
    assert view.property("contentY") == pytest.approx(before)
    pacs.testProfile(pacs.selectedProfileId)
    wait_until(lambda: not pacs.busy)
    assert view.property("contentY") == pytest.approx(before)
    assert not warnings, warnings


def test_segmented_sources_and_advanced_filter_footer(scene, monkeypatch, tmp_path):
    window, app, warnings = scene
    window.resize(1000, 600)
    folder = find(window, "sidebarOpenFolder")
    pacs = find(window, "sidebarPacs")
    assert folder.property("checked") and not pacs.property("checked")
    assert find(window, "homeOpenPacs").property("iconName") == "nav-pacs"
    click(window, pacs)
    assert app.workspaceController.activeTabType == "pacs"
    assert pacs.property("checked") and not folder.property("checked")
    monkeypatch.setattr("qt_dicom_viewer.ui.controller.panel_controller.select_import_paths", lambda *args: [])
    click(window, folder)
    assert folder.property("checked") and not pacs.property("checked")
    click(window, pacs)
    assert pacs.property("checked") and not folder.property("checked")

    assert app.pacsController.saveProfile({"name": "Demo", "url": "http://127.0.0.1:8042"})
    assert app.pacsController.message == ""
    QTest.qWait(60)
    scroll = find(window, "pacsFilterScroll")
    flick = next(i for i in descendants(scroll) if i.property("contentY") is not None)

    def scroll_bottom():
        # Finish layout before using contentHeight; loaded fonts can change it.
        assert not window.grabWindow().isNull()
        origin = flick.property("originY") or 0
        bottom = origin + max(0, flick.property("contentHeight") - flick.height())
        flick.setProperty("contentY", bottom)
        assert not window.grabWindow().isNull()
        button = find(window, "pacsMoreFilters")
        center = button.mapToItem(scroll, button.boundingRect().center())
        assert 0 <= center.x() < scroll.width() and 0 <= center.y() < scroll.height(), (
            center, scroll.size(), flick.property("contentY"), bottom)

    scroll_bottom()
    click(window, find(window, "pacsMoreFilters"))
    wait_until(lambda: "收起" in find(window, "pacsMoreFilters").property("text"))
    scroll_bottom()
    collapse = find(window, "pacsMoreFilters")
    description = find(window, "pacsStudyDescription")
    assert collapse.mapToScene(QPointF()).y() >= description.mapToScene(QPointF(0, description.height())).y()
    assert collapse.mapToItem(scroll, QPointF(0, collapse.height())).y() <= scroll.height()
    assert window.grabWindow().save(str(tmp_path / "pacs-segmented-expanded.png"))
    click(window, collapse)
    QTest.qWait(150)
    assert not any(i.objectName() == "pacsStudyDescription" and i.isVisible() for i in descendants(scroll))
    assert "更多筛选条件" in find(window, "pacsMoreFilters").property("text")
    assert 0 <= collapse.mapToItem(scroll, QPointF()).y() < scroll.height()
    assert not warnings, warnings


def test_query_enter_uses_button_guard_and_current_inputs(scene, monkeypatch):
    from PySide6.QtCore import Qt, QMetaObject
    window, app, warnings = scene
    pacs = app.pacsController
    pacs.saveProfile({"name": "Test", "url": "http://127.0.0.1:9"})
    calls = []
    monkeypatch.setattr(pacs, "_query_studies", lambda offset: calls.append(dict(pacs._filters)))
    click(window, find(window, "sidebarPacs"))
    field = find(window, "pacsPatientName")
    type_text(window, field, "TEST*")
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(30)
    assert len(calls) == 1 and calls[0]["PatientName"] == "TEST*"
    click(window, find(window, "pacsQueryStudies"))
    assert len(calls) == 2 and calls[0] == calls[1]
    pacs._busy = True
    pacs.stateChanged.emit()
    QTest.qWait(30)
    assert not find(window, "pacsQueryStudies").isEnabled()
    QMetaObject.invokeMethod(field, "accepted")
    assert len(calls) == 2
    pacs._busy = False
    pacs.stateChanged.emit()
    assert not warnings, warnings
