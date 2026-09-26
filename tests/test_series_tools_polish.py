"""Sidebar stability and the revised live tool interactions."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.service.thumbnail_service import ThumbnailRequest
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene, right_click, drag_width
from test_tag_qml import find, click, type_text, descendants
from test_display_tools_qml import display_panel, _find, _click


@pytest.mark.parametrize("height", [600, 900])
def test_thumbnail_refresh_preserves_visible_rows_and_fixed_chrome(sidebar_scene, height, tmp_path):
    window, app, records, warnings = sidebar_scene
    panel = app.panelController
    many = [replace(records[0], series_instance_uid=f"1.4.{i + 1}", series_number=i + 1,
                    patient_id=f"P{i // 20}", study_instance_uid=f"1.5.{i // 8}") for i in range(100)]
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 100, 100, 0, many))
    panel._thumbnail_timer.stop()
    window.resize(1000, height)
    drag_width(window, 200)
    QTest.qWait(50)
    listing = find(window, "sidebarSeriesList")
    search = find(window, "sidebarPatientSearch")
    footer = find(window, "sidebarSettingsFooter")
    chrome = [(item.y(), item.height()) for item in (search, footer)]
    listing.setProperty("contentY", 1800)
    QTest.qWait(40)
    anchor = next(item for item in descendants(window.contentItem())
                  if item.objectName().startswith("series-")
                  and 0 <= item.mapToItem(listing, QPointF()).y() < listing.height() - 58)
    anchor_name = anchor.objectName()
    y = anchor.mapToItem(listing, QPointF()).y()
    offset = listing.property("contentY")
    changed, resets = [], []
    panel.sidebarModel.dataChanged.connect(lambda *args: changed.append(args))
    panel.sidebarModel.modelReset.connect(lambda: resets.append(True))
    image = QImage(12, 12, QImage.Format_Grayscale8)
    image.fill(180)
    for record in many[:20]:
        panel._accept_thumbnail(ThumbnailRequest(record.series_instance_uid, record.instances[1].path), image)
        QTest.qWait(5)
        assert find(window, anchor_name) is anchor
        assert anchor.mapToItem(listing, QPointF()).y() == pytest.approx(y, abs=1)
        assert listing.property("contentY") == pytest.approx(offset, abs=1)
    assert len(changed) == 20 and not resets
    # A new patient inserted above the viewport retains the visible row anchor.
    added = replace(records[0], patient_name="AAA", patient_id="first", series_instance_uid="1.9.1")
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 1, 1, 0, [added]))
    panel._thumbnail_timer.stop()
    QTest.qWait(50)
    assert find(window, anchor_name).mapToItem(listing, QPointF()).y() == pytest.approx(y, abs=1)
    assert [(item.y(), item.height()) for item in (search, footer)] == chrome
    panel.setPatientSearch("P0")
    QTest.qWait(40)
    assert listing.property("contentY") == listing.property("originY")
    assert window.grabWindow().save(str(tmp_path / f"sidebar-stable-{height}.png"))
    assert not warnings, warnings


def test_batch_delete_keeps_checked_hidden_items_tabs_and_source_files(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    panel, ws = app.panelController, app.workspaceController
    uids = [record.series_instance_uid for record in records]
    panel.openSeriesView(uids[0], "tag")
    wait_until(lambda: ws.activeTab is not None and not ws.activeTab.tagController.loading)
    original_tab = ws.activeTab
    panel.selectSeries(uids[0])
    panel.selectSeriesWithModifiers(uids[2], True)
    panel.setPatientSearch("DEMO-A")
    QTest.qWait(40)
    right_click(window, find(window, "series-" + uids[1]))
    assert panel.selectedSeriesUids == [uids[0], uids[2]]
    updates = []
    panel.seriesItemsChanged.connect(lambda: updates.append(True))
    assert not any(i.objectName() == "seriesContextAction-remove-selected" for i in descendants(window.contentItem()))
    QTest.keyClick(window, Qt.Key_Escape)
    panel.removeSelectedSeries()
    assert [item["seriesInstanceUid"] for item in panel.seriesItems] == [uids[1]]
    assert updates == [True] and panel.selectedSeriesUids == []
    assert ws.activeTab is original_tab
    assert all(record.first_file.exists() for record in records)
    assert all(app._series_catalog.get_series(uid) is not None for uid in uids)
    panel.setPatientSearch("no match")
    QTest.qWait(30)
    clear = find(window, "sidebarClear")
    assert clear.isEnabled()
    panel._set_scanning(True)
    assert not clear.isEnabled()
    panel.clearSeries()
    panel.removeSelectedSeries()
    assert panel.hasSeries
    panel._set_scanning(False)
    click(window, clear)
    assert not panel.hasSeries and panel.patientSearch == "" and not panel._collapsed_groups
    assert not clear.isEnabled() and ws.activeTab is original_tab
    panel._update_series_record(DicomFolderScanSnapshot(records[0].first_file.parent, 9, 9, 0, records))
    assert not panel.hasSeries
    panel._start_import([str(records[0].first_file.parent)])
    wait_until(lambda: not panel.scanning and panel.hasSeries)
    assert len(panel.seriesItems) == 3
    assert not warnings, warnings


def test_numeric_window_apply_template_validation_persistence_and_delete(display_panel, tmp_path):
    view, controller, warnings = display_panel
    root = view.rootObject()
    settings = controller.settingsController
    settings._path = tmp_path / "preferences.json"
    settings._window_path = tmp_path / "window-presets.json"
    from qt_dicom_viewer.settings.window_presets import write_document
    settings._window_revision = write_document(settings._window_path, settings._window_entries)
    _click(view, _find(root, "primaryTool-window"))
    width, center = _find(root, "windowWidthInput"), _find(root, "windowCenterInput")
    initial = controller.current_window
    type_text(view, width, "1234.5")
    type_text(view, center, "-123.25")
    assert controller.current_window == initial
    QTest.keyClick(view, Qt.Key_Return)
    assert controller.windowWidth == 1234.5 and controller.windowCenter == -123.2
    type_text(view, width, "0")
    _click(view, _find(root, "applyWindowValues"))
    assert controller.windowWidth == 1234.5
    assert _find(root, "windowInputError").property("text")
    type_text(view, width, "999.75")
    _click(view, _find(root, "applyWindowValues"))
    assert controller.windowWidth == 999.8
    type_text(view, width, "999.8497")
    _click(view, _find(root, "beginSaveWindowTemplate"))
    name = _find(root, "quickWindowTemplateName")
    type_text(view, name, "Review window")
    _click(view, _find(root, "quickSaveWindowTemplate"))
    custom = settings.values["window"]["custom"]
    assert width.property("text") == "999.8" and center.property("text") == "-123.2"
    assert len(custom) == 1 and custom[0]["width"] == 999.8
    identifier = custom[0]["presetId"]
    reloaded = SettingsController(path=settings._path)
    assert reloaded.values["window"]["custom"] == custom
    _click(view, _find(root, "beginSaveWindowTemplate"))
    type_text(view, _find(root, "quickWindowTemplateName"), "Review window")
    _click(view, _find(root, "quickSaveWindowTemplate"))
    assert "重复" in _find(root, "windowInputError").property("text")
    assert len(settings.values["window"]["custom"]) == 1
    # Scroll the shared outer area to the last template before clicking delete.
    flick = _find(root, "toolDetailFlickable")
    flick.setProperty("contentY", max(0, flick.property("contentHeight") - flick.height()))
    QTest.qWait(40)
    _click(view, _find(root, "quickDeleteWindowTemplate-" + identifier))
    assert settings.values["window"]["custom"] == []
    assert controller.windowWidth == 999.8 and controller.windowCenter == -123.2
    assert SettingsController(path=settings._path).values["window"]["custom"] == []
    assert not warnings, warnings


def test_annotation_controls_and_delete_route_to_the_selected_kind(display_panel):
    from test_measurement_controller import _position, _drag
    view, controller, warnings = display_panel
    root = view.rootObject()
    _click(view, _find(root, "primaryTool-annotate"))
    assert not _find(root, "annotationTextEditor", visible=False).isVisible()
    assert not _find(root, "annotationFontSize", visible=False).isVisible()
    button = _find(root, "deleteSelectedAnnotation")
    assert not button.isEnabled()
    start, end = _position(10, 10), _position(30, 10)
    measurement = controller.measurementController
    measurement.begin(start, controller._measurement_context(3, 2))
    measurement.update(_drag(start, end))
    measurement.end(end)
    assert measurement.measurementItems[0]["type"] == "arrow"
    assert button.isEnabled()
    _click(view, button)
    assert measurement.measurementItems == [] and not button.isEnabled()
    _click(view, _find(root, "annotateTextMode"))
    assert _find(root, "annotationTextEditor").isVisible()
    assert _find(root, "annotationFontSize").isVisible()
    controller.textAnnotationController.addAnnotation(10, 10, 30, 20)
    flick = _find(root, "toolDetailFlickable")
    flick.setProperty("contentY", max(0, flick.property("contentHeight") - flick.height()))
    QTest.qWait(60)
    assert button.isEnabled()
    _click(view, button)
    assert controller.textAnnotationController.annotationItems == []
    assert not button.isEnabled()
    assert not any(item.objectName().startswith(("annotationListItem-", "clearAllAnnotations"))
                   for item in descendants(root))
    assert not warnings, warnings


def test_water_qa_manual_roundtrip_retains_result(sidebar_scene, tmp_path, qt_app):
    from manual.smoke_water_qa import make_water_series
    from test_water_qa_controller import wait_qa
    window, app, records, warnings = sidebar_scene
    series, _ = make_water_series(tmp_path)
    snapshot = DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [series])
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    app.panelController.openSeriesView(series.series_instance_uid, "2d")
    workspace = app.workspaceController
    view, tab_id = workspace.activeViewport, workspace.activeTabId
    wait_until(lambda: view._modality_pixel is not None)
    click(window, find(window, "primaryTool-service"))
    click(window, find(window, "serviceEntry-qa"))
    wait_qa(qt_app, view.qaController)
    result = view.qaController.currentResult
    click(window, find(window, "waterQaManualButton"))
    assert workspace.activeTabType == "manual"
    assert workspace.manualController.chapterId == "water-qa"
    workspace.activateTabId(tab_id)
    QTest.qWait(80)
    assert workspace.activeViewport is view and view.qaController.currentResult == result
    assert len(view.qaController.roiItems) == 5
    assert not warnings, warnings


@pytest.mark.parametrize("text_mode", [False, True])
def test_annotation_style_controls_update_both_modes(display_panel, text_mode):
    view, controller, warnings = display_panel
    root = view.rootObject()
    controller._tool_controller.activateTool("annotate")
    controller.setAnnotationMode(text_mode)
    QTest.qWait(50)
    for name, setting, increment in [("annotationLineWidth", "lineWidth", 0.5),
                                      ("annotationArrowSize", "annotationSize", 1)]:
        slider = _find(root, name)
        before = controller.settingsController.values["measurement"][setting]
        slider.forceActiveFocus()
        QTest.keyClick(view, Qt.Key_Right)
        assert controller.settingsController.values["measurement"][setting] == before + increment
    _click(view, _find(root, "annotationColor-ef7777"))
    if text_mode:
        controller.textAnnotationController.addAnnotation(10, 10, 30, 20)
        assert controller.textAnnotationController.annotationItems[0]["color"] == "#ef7777"
    else:
        assert controller.settingsController.values["measurement"]["annotationColor"] == "#ef7777"
    # Changing modes retains the shared style, including live keyboard edits.
    controller.setAnnotationMode(not text_mode)
    assert _find(root, "annotationLineWidth").property("value") == 2
    assert _find(root, "annotationArrowSize").property("value") == 15
    assert not warnings, warnings


@pytest.mark.parametrize("width", [220, 250, 330])
def test_window_preset_content_is_centered_and_actions_remain_distinct(display_panel, tmp_path, width):
    view, controller, warnings = display_panel
    view.resize(width, 850)
    root = view.rootObject()
    controller.settingsController.saveWindowTemplate("", "自定义模板", 1200, -100)
    controller._tool_controller.activateTool("window")
    QTest.qWait(80)
    primary = _find(root, "applyWindowValues")
    secondary = _find(root, "beginSaveWindowTemplate")
    assert primary.property("normalColor") != secondary.property("normalColor")
    assert secondary.property("baseBorderWidth") == 1
    _click(view, secondary)
    cancel = _find(root, "cancelSaveWindowTemplate")
    save = _find(root, "quickSaveWindowTemplate")
    assert cancel.property("normalColor") != save.property("normalColor")
    assert cancel.property("hoverColor") != save.property("hoverColor")
    assert cancel.property("pressedColor") != save.property("pressedColor")
    assert cancel.property("baseBorderWidth") == 0
    QTest.qWait(80)
    cancel_position = cancel.mapToScene(QPointF())
    save_position = save.mapToScene(QPointF())
    assert cancel_position.y() == pytest.approx(save_position.y(), abs=0.5)
    assert cancel_position.x() + cancel.width() < save_position.x()
    rows = [item for item in descendants(root) if item.objectName().startswith("windowPreset-")]
    assert rows
    for row in rows:
        labels = [item for item in descendants(row)
                  if item.metaObject().className().startswith("QQuickText") and item.isVisible()]
        assert len(labels) == 3
        for label in labels:
            center = label.mapToItem(row, QPointF(0, label.height() / 2)).y()
            assert center == pytest.approx(row.height() / 2, abs=0.5)
        delete_buttons = [item for item in descendants(row)
                          if item.objectName().startswith("quickDeleteWindowTemplate-") and item.isVisible()]
        for button in delete_buttons:
            center = button.mapToItem(row, QPointF(0, button.height() / 2)).y()
            assert center == pytest.approx(row.height() / 2, abs=0.5)
    assert view.grabWindow().save(str(tmp_path / f"window-controls-{width}.png"))
    assert not warnings, warnings


@pytest.mark.parametrize("panel_width", [220, 250, 420])
def test_window_inputs_keep_equal_fixed_size_through_edits_and_updates(display_panel, panel_width):
    view, controller, warnings = display_panel
    view.resize(panel_width, 820)
    QTest.qWait(30)
    width, center = (_find(view.rootObject(), n) for n in ("windowWidthInput", "windowCenterInput"))
    def geometry():
        return [(i.mapToScene(QPointF()).x(), i.width(), i.height()) for i in (width, center)]
    initial = geometry()
    assert width.width() == pytest.approx(center.width(), abs=1)
    for ww, wl in [(1, 0), (320.39, -173.02), (1000000, -1000000), (80, 40)]:
        controller.applyWindowPreset(wl, ww)
        QTest.qWait(30)
        assert geometry() == initial
        type_text(view, width, str(ww) + "0000")
        type_text(view, center, str(wl) + ".12345678")
        QTest.qWait(30)
        assert geometry() == initial
        QTest.keyClick(view, Qt.Key_Escape)
    assert not warnings, warnings


def test_window_values_show_at_most_one_decimal_after_live_updates(display_panel):
    view, controller, warnings = display_panel
    root = view.rootObject()
    width, center = _find(root, "windowWidthInput"), _find(root, "windowCenterInput")
    for ww, wl, expected in [(167.23147, 56.995304, ("167.2", "57")),
                              (320.39, -173.02, ("320.4", "-173")),
                              (80, 40, ("80", "40"))]:
        controller.applyWindowPreset(wl, ww)
        assert (width.property("text"), center.property("text")) == expected
    type_text(view, width, "167.23147")
    type_text(view, center, "56.995304")
    QTest.keyClick(view, Qt.Key_Return)
    assert controller.windowWidth == 167.2 and controller.windowCenter == 57
    assert (width.property("text"), center.property("text")) == ("167.2", "57")
    assert not warnings, warnings
