from pathlib import Path

import pytest
import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from PySide6.QtCore import QObject, Property, QPointF, Qt, QUrl, QMetaObject, Q_ARG, Q_RETURN_ARG
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, make_series, catalog_for, wait_until, rows


class _App(QObject):
    def __init__(self, workspace, panel):
        super().__init__()
        self.workspace = workspace
        self.panel = panel
        from qt_dicom_viewer.ui.controller.feedback_controller import FeedbackController
        from qt_dicom_viewer.ui.controller.update_controller import UpdateController
        self.feedback = FeedbackController(None, self)
        self.updates = UpdateController(None, self)

    feedbackController = Property(QObject, lambda self: self.feedback, constant=True)
    updateController = Property(QObject, lambda self: self.updates, constant=True)

    @Property(QObject, constant=True)
    def workspaceController(self):
        return self.workspace

    @Property(QObject, constant=True)
    def panelController(self):
        return self.panel


def descendants(item):
    for child in item.childItems():
        yield child
        yield from descendants(child)


def find(window, name):
    # Workspace components now incubate asynchronously. Wait for a visible
    # target rather than assuming a fixed sleep has completed page creation.
    def target():
        return next((item for item in descendants(window.contentItem())
                     if item.objectName() == name and item.isVisible()
                     and item.width() > 0 and item.height() > 0), None)
    wait_until(lambda: target() is not None)
    return target()


def click(window, item):
    pos = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(30)


def type_text(window, item, text):
    item.forceActiveFocus()
    QMetaObject.invokeMethod(item, "selectAll")
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in text:
        QTest.keyClick(window, char)
    QTest.qWait(20)


@pytest.fixture
def scene(qt_app, tmp_path):
    series = make_series(tmp_path, 20)
    catalog = catalog_for(series, tmp_path)
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    panel = PanelController(series_catalog=catalog)
    panel.tabCreateRequested.connect(workspace.activeWorkspace)
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 20, 20, 0, [series]))
    app = _App(workspace, panel)
    engine = QQmlApplicationEngine()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    engine.addImageProvider("navigation", SvgIconProvider())
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.addImageProvider("dicom", provider)
    engine.rootContext().setContextProperty("appController", app)
    source = Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/Main.qml"
    engine.load(QUrl.fromLocalFile(str(source)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    QTest.qWait(50)
    try:
        yield window, workspace, series, warnings
    finally:
        window.hide()
        workspace.shutdown()
        delete(engine)


def open_tags(window, workspace, series):
    click(window, find(window, "series-" + series.series_instance_uid))
    click(window, find(window, "openView-tag"))
    wait_until(lambda: workspace.activeTab is not None and not workspace.activeTab.tagController.loading)
    QTest.qWait(50)
    return workspace.activeTab.tagController


def test_real_tag_click_search_paging_expand_and_layout(scene, tmp_path):
    window, workspace, series, warnings = scene
    assert not find(window, "openView-tag").isEnabled()
    controller = open_tags(window, workspace, series)
    assert workspace.activeTabType == "tag"
    assert not any(item.objectName() == "rightPanel" and item.isVisible()
                   for item in descendants(window.contentItem()))
    type_text(window, find(window, "tagSearch"), "nested-needle")
    assert controller.searchText == "nested-needle" and controller.tagModel.matchCount == 1
    assert len(rows(controller.tagModel)) == 3
    click(window, find(window, "tagNext"))
    wait_until(lambda: not controller.loading)
    assert controller.currentPage == 2 and controller.searchText == "nested-needle"
    type_text(window, find(window, "tagPageInput"), "21")
    click(window, find(window, "tagJump"))
    assert controller.currentPage == 2 and controller.pageError
    type_text(window, find(window, "tagPageInput"), "20")
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: not controller.loading)
    assert controller.currentPage == 20 and not controller.pageError
    assert not find(window, "tagNext").isEnabled()
    type_text(window, find(window, "tagSearch"), "")
    assert controller.searchText == ""
    sequence = next(row for row in rows(controller.tagModel) if row["vr"] == "SQ")
    index = next(i for i, row in enumerate(rows(controller.tagModel)) if row["vr"] == "SQ")
    list_view = find(window, "tagList")
    list_view.setProperty("contentY", min(index * 78, list_view.property("contentHeight") - list_view.height()))
    QTest.qWait(50)
    before_expand = list_view.property("contentY")
    click(window, find(window, "tagExpand-" + sequence["nodeId"]))
    assert any(row["isItem"] for row in rows(controller.tagModel))
    assert list_view.property("contentY") == pytest.approx(before_expand)
    click(window, find(window, "tagExpand-" + sequence["nodeId"] + "/item-0"))
    assert any(row["valueText"] == "NESTED-NEEDLE" for row in rows(controller.tagModel))

    # Restore the first page for visual QA of the reference-style header and rows.
    click(window, find(window, "tagPage-1"))
    wait_until(lambda: not controller.loading)
    for width, height, name in [(1400, 760, "default"), (1000, 600, "minimum")]:
        window.resize(width, height)
        QTest.qWait(80)
        for object_name in ["tagSearch", "tagJump", "tagNext", "tagList"]:
            item = find(window, object_name)
            top_left = item.mapToScene(QPointF(0, 0))
            bottom_right = item.mapToScene(QPointF(item.width(), item.height()))
            assert 0 <= top_left.x() < bottom_right.x() <= width
            assert 0 <= top_left.y() < bottom_right.y() <= height
        if width == 1400:
            navigation = find(window, "tagNavigationPanel")
            search_panel = find(window, "tagSearchPanel")
            assert navigation.mapToScene(QPointF(0, 0)).y() == pytest.approx(
                search_panel.mapToScene(QPointF(0, 0)).y())
            assert navigation.height() == pytest.approx(search_panel.height())
            page_input = find(window, "tagPageInput")
            search_input = find(window, "tagSearch")
            assert page_input.mapToScene(QPointF(0, 0)).y() == pytest.approx(
                search_input.mapToScene(QPointF(0, 0)).y())
            assert page_input.height() == pytest.approx(search_input.height())
        screenshot = window.grabWindow()
        assert not screenshot.isNull()
        assert screenshot.save(str(tmp_path / f"tags-{name}.png"))
        assert screenshot.save(str(tmp_path / f"dicom-tags-{name}.png"))
    assert not warnings, "\n".join(warnings)


def reveal_row(window, controller, node_id):
    model_rows = rows(controller.tagModel)
    index = next(i for i, row in enumerate(model_rows) if row["nodeId"] == node_id)
    view = find(window, "tagList")
    QMetaObject.invokeMethod(view, "positionViewAtIndex", Q_ARG(int, index), Q_ARG(int, 1))
    QTest.qWait(30)
    return find(window, "tagIdentity-" + node_id)


def assert_indentation(window, controller, expected):
    positions = []
    for node_id, depth in expected:
        identity = reveal_row(window, controller, node_id)
        vr = find(window, "tagVr-" + node_id)
        assert identity.width() > 0
        assert identity.x() == pytest.approx(38 + depth * 16)
        assert identity.x() + identity.width() < vr.x()
        positions.append(identity.x())
    assert all(right - left == pytest.approx(16) for left, right in zip(positions, positions[1:]))


def test_nested_indentation_survives_expand_search_and_tab_switch(scene, tmp_path):
    window, workspace, series, warnings = scene
    controller = open_tags(window, workspace, series)
    root_id = "dataset/0040A043"
    expected = [
        (root_id, 0), (root_id + "/item-0", 1),
        (root_id + "/item-0/00081110", 2),
        (root_id + "/item-0/00081110/item-0", 3),
        (root_id + "/item-0/00081110/item-0/00100020", 4),
    ]
    for node_id, _ in expected[:-1]:
        reveal_row(window, controller, node_id)
        click(window, find(window, "tagExpand-" + node_id))
    assert_indentation(window, controller, expected)
    before = [(row["nodeId"], row["depth"], row["expanded"]) for row in rows(controller.tagModel)]
    type_text(window, find(window, "tagSearch"), "INNER-PATIENT")
    assert [(row["nodeId"], row["depth"]) for row in rows(controller.tagModel)] == expected
    assert_indentation(window, controller, expected)
    find(window, "tagList").setProperty("contentY", 0)
    QTest.qWait(30)
    assert window.grabWindow().save(str(tmp_path / "dicom-tags-nested.png"))
    type_text(window, find(window, "tagSearch"), "")
    assert [(row["nodeId"], row["depth"], row["expanded"]) for row in rows(controller.tagModel)] == before
    click(window, find(window, "openView-2d"))
    click(window, find(window, "openView-tag"))
    assert_indentation(window, controller, expected)
    assert not warnings, "\n".join(warnings)


def test_deep_indentation_never_flattens_at_narrow_width(scene, tmp_path):
    window, workspace, series, warnings = scene
    path = series.instances[0].path
    dataset = pydicom.dcmread(path)
    parent = dataset
    for _ in range(18):
        child = Dataset()
        parent.ReferencedStudySequence = Sequence([child])
        parent = child
    parent.PatientID = "DEEP-NESTED-END"
    dataset.save_as(path, enforce_file_format=True)
    window.resize(1280, 720)
    QTest.qWait(80)
    controller = open_tags(window, workspace, series)
    type_text(window, find(window, "tagSearch"), "DEEP-NESTED-END")
    expected = [(row["nodeId"], row["depth"]) for row in rows(controller.tagModel)]
    assert [depth for _, depth in expected] == list(range(37))
    assert controller.tagModel.maxVisibleDepth == 36
    assert_indentation(window, controller, expected)
    view = find(window, "tagList")
    assert view.property("contentWidth") > view.width()
    view.setProperty("contentX", 100)
    QTest.qWait(30)
    leaf_vr = find(window, "tagVr-" + expected[-1][0])
    header_vr = find(window, "tagVrHeader")
    assert leaf_vr.mapToScene(QPointF(0, 0)).x() == pytest.approx(
        header_vr.mapToScene(QPointF(0, 0)).x())
    assert window.grabWindow().save(str(tmp_path / "dicom-tags-deep.png"))
    assert not warnings, "\n".join(warnings)


def test_full_value_is_plain_selectable_text(scene):
    window, workspace, series, warnings = scene
    controller = open_tags(window, workspace, series)
    type_text(window, find(window, "tagSearch"), "ImageComments")
    value_row = rows(controller.tagModel)[0]
    row_item = find(window, "tagRow-" + value_row["nodeId"])
    pos = row_item.mapToScene(QPointF(row_item.width() - 80, row_item.height() / 2)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(50)
    value = find(window, "tagFullValue")
    assert value.property("text") == value_row["valueText"]
    assert len(value.property("text")) > 2000
    assert value.property("readOnly") and value.property("selectByMouse")
    displayed_text = QMetaObject.invokeMethod(
        value, "getText", Q_RETURN_ARG(str), Q_ARG(int, 0), Q_ARG(int, 3))
    assert displayed_text == "<b>"  # Markup is displayed literally, never interpreted.
    assert not warnings, "\n".join(warnings)


def test_tag_tab_restores_scroll_query_and_image_toolbar(scene):
    window, workspace, series, warnings = scene
    controller = open_tags(window, workspace, series)
    list_view = find(window, "tagList")
    list_view.setProperty("contentY", 500)
    QTest.qWait(30)
    assert controller.scrollPosition == pytest.approx(500)
    click(window, find(window, "openView-2d"))
    assert workspace.activeTabType == "2d"
    assert find(window, "rightPanel").isVisible()
    click(window, find(window, "openView-tag"))
    QTest.qWait(50)
    assert workspace.activeTab.tagController is controller
    assert find(window, "tagList").property("contentY") == pytest.approx(500)
    assert len(workspace.tabs) == 2
    tab_backgrounds = {
        tab["tabId"]: find(window, "workspaceTabBackground-" + tab["tabId"])
        for tab in workspace.tabs
    }
    active_background = tab_backgrounds[workspace.activeTabId]
    inactive_background = next(
        background for tab_id, background in tab_backgrounds.items()
        if tab_id != workspace.activeTabId
    )
    assert active_background.property("color").name() == "#203b4c"
    assert active_background.property("visualBorderColor").name() == "#758b9d"
    assert inactive_background.property("color").name() == "#14191f"
    assert inactive_background.property("visualBorderColor").name() == "#29313a"
    type_text(window, find(window, "tagSearch"), "PatientName")
    click(window, find(window, "openView-mpr"))
    assert workspace.activeTabType == "mpr" and find(window, "rightPanel").isVisible()
    click(window, find(window, "openView-tag"))
    assert find(window, "tagSearch").property("text") == "PatientName"
    assert controller.tagModel.matchCount == 1
    assert not warnings, "\n".join(warnings)


def test_tag_search_scroll_and_quick_tab_switches_keep_delegates_alive(scene):
    window, workspace, series, warnings = scene
    controller = open_tags(window, workspace, series)
    tag_id = workspace.activeTabId
    click(window, find(window, "openView-2d"))
    image_id = workspace.activeTabId
    for turn in range(16):
        workspace.activateTabId(tag_id)
        view = find(window, "tagList")
        controller.setSearchText("" if turn % 2 == 0 else "Patient")
        view.setProperty("contentY", 300 if turn % 2 == 0 else 0)
        QTest.qWait(1 + turn % 4)
        workspace.activateTabId(image_id)
        QTest.qWait(1 + turn % 3)
    workspace.activateTabId(tag_id)
    assert find(window, "tagSearch").property("text") == "Patient"
    assert controller.tagModel.matchCount > 0
    assert not warnings, "\n".join(warnings)


def test_value_dialog_adapts_to_content_and_copies_plain_text(scene, tmp_path):
    from PySide6.QtGui import QGuiApplication
    window, workspace, series, warnings = scene
    controller = open_tags(window, workspace, series)
    type_text(window, find(window, "tagSearch"), "MediaStorageSOPClassUID")
    row = rows(controller.tagModel)[0]
    item = find(window, "tagRow-" + row["nodeId"])
    pos = item.mapToScene(QPointF(item.width() - 80, item.height() / 2)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    value = find(window, "tagFullValue")
    dialog = window.findChild(QObject, "tagValueDialog")
    panel = find(window, "tagPanel")
    assert dialog.property("visible")
    assert dialog.property("height") < 260
    assert dialog.property("width") <= 640
    assert row["tagNumber"] in panel.property("detailMetadata")
    copy = find(window, "tagCopyValue")
    close = find(window, "tagCloseValue")
    assert copy.width() < 120 and close.width() < 100
    assert close.mapToScene(QPointF()).y() < value.mapToScene(QPointF()).y()
    assert close.mapToScene(QPointF(close.width(), 0)).x() == copy.mapToScene(QPointF(copy.width(), 0)).x()
    assert window.grabWindow().save(str(tmp_path / "tag-detail-short.png"))
    clipboard = QGuiApplication.clipboard()
    previous = clipboard.text()
    try:
        click(window, copy)
        assert clipboard.text() == row["valueText"]
        assert dialog.property("visible")
        # Long lines and multiline values stay selectable and scroll within the
        # available space, even at the minimum workspace size.
        window.resize(1000, 600)
        long_value = ("很长的标签值 <b>plain text</b> " * 50 + "\n") * 15
        panel.setProperty("detailValue", long_value)
        QTest.qWait(60)
        scroll = find(window, "tagValueScroll")
        assert value.property("text") == long_value
        assert value.height() > scroll.height()
        assert dialog.property("height") <= panel.height() - 32
        assert float(scroll.property("contentWidth")) <= scroll.width()
        for target in (scroll, copy, close):
            point = target.mapToScene(QPointF(target.width(), target.height()))
            assert point.x() <= window.width() and point.y() <= window.height()
        assert window.grabWindow().save(str(tmp_path / "tag-detail-long.png"))
        click(window, copy)
        assert clipboard.text() == long_value
        QTest.keyClick(window, Qt.Key_Escape)
        QTest.qWait(60)
        assert not dialog.property("visible")
    finally:
        clipboard.setText(previous)
    assert not warnings, "\n".join(warnings)
