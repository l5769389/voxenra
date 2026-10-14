"""PACS keyboard workflows and the names/colors presented by the rendered UI."""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QAccessible, QAccessibleActionInterface
from PySide6.QtTest import QTest
import pytest

from test_dicom_tags import qt_app, wait_until
from test_pacs import pacs_server, STUDY, SERIES, element
from test_pacs_qml import scene
from test_tag_qml import find, click, descendants


@pytest.fixture(autouse=True)
def all_controls_keyboard_navigation(qt_app):
    hints = qt_app.styleHints()
    previous = hints.tabFocusBehavior()
    hints.setTabFocusBehavior(Qt.TabFocusAllControls)
    try:
        yield
    finally:
        hints.setTabFocusBehavior(previous)


def query_studies(window, app, server, count=1):
    if count > 1:
        server.study_rows = [
            {**server.study_rows[0], "0020000D": element("UI", STUDY + f".{i}"),
             "00081030": element("LO", f"Synthetic study {i}")}
            for i in range(count)
        ]
    pacs = app.pacsController
    assert pacs.saveProfile({"name": "Synthetic PACS", "url": server.url})
    app.workspaceController.openPacs()
    click(window, find(window, "pacsQueryStudies"))
    wait_until(lambda: not pacs.busy and len(pacs.studies) == count)
    find(window, "pacsQueryStudies").forceActiveFocus(Qt.TabFocusReason)
    QTest.keyClick(window, Qt.Key_Tab)
    QTest.qWait(50)
    return pacs


@pytest.mark.parametrize("activation", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space])
def test_tab_study_activation_continues_to_series(scene, pacs_server, activation):
    window, app, warnings = scene
    pacs = query_studies(window, app, pacs_server)
    assert window.activeFocusItem().objectName() == "pacsStudy-" + STUDY
    QTest.keyClick(window, activation)
    wait_until(lambda: not pacs.busy and len(pacs.series) == 1)
    assert pacs.selectedStudyUid == STUDY
    assert find(window, "pacsStudy-" + STUDY).property("checked")
    QTest.keyClick(window, Qt.Key_Tab)
    assert window.activeFocusItem().objectName() == "pacsSelectAll"
    QTest.keyClick(window, Qt.Key_Tab)
    assert window.activeFocusItem().objectName() == "pacsSeries-" + SERIES
    QTest.keyClick(window, Qt.Key_Space)
    assert pacs.selectedCount == 1
    QTest.keyClick(window, Qt.Key_Tab)
    assert window.activeFocusItem().objectName() == "pacsImportSelected"
    assert not warnings, warnings


def test_keyboard_study_navigation_scrolls_and_keeps_one_tab_stop(scene, pacs_server, tmp_path):
    window, app, warnings = scene
    window.resize(1000, 600)
    pacs = query_studies(window, app, pacs_server, count=20)
    assert window.activeFocusItem().objectName() == "pacsStudy-" + STUDY + ".0"
    QTest.keyClick(window, Qt.Key_End)
    QTest.qWait(80)
    row = window.activeFocusItem()
    assert row.objectName() == "pacsStudy-" + STUDY + ".19"
    view = find(window, "pacsStudiesList")
    top = row.mapToItem(view, QPointF()).y()
    assert 0 <= top and top + row.height() <= view.height() + 1
    assert view.property("contentY") > 0
    assert row.property("visualFocus")
    assert window.grabWindow().save(str(tmp_path / "pacs-study-keyboard-end.png"))
    QTest.keyClick(window, Qt.Key_Up)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: not pacs.busy and len(pacs.series) == 1)
    assert pacs.selectedStudyUid == STUDY + ".18"
    QTest.keyClick(window, Qt.Key_Down)
    assert window.activeFocusItem().objectName() == "pacsStudy-" + STUDY + ".19"
    QTest.keyClick(window, Qt.Key_Tab)
    assert window.activeFocusItem().objectName() == "pacsSelectAll"
    QTest.keyClick(window, Qt.Key_Backtab)
    assert window.activeFocusItem().objectName() == "pacsStudy-" + STUDY + ".19"
    QTest.keyClick(window, Qt.Key_Home)
    assert window.activeFocusItem().objectName() == "pacsStudy-" + STUDY + ".0"
    assert not warnings, warnings


def test_study_accessible_press_and_pointer_share_selection_and_busy_guard(scene, pacs_server):
    window, app, warnings = scene
    pacs = query_studies(window, app, pacs_server, count=2)
    first = find(window, "pacsStudy-" + STUDY + ".0")
    second = find(window, "pacsStudy-" + STUDY + ".1")
    accessible = QAccessible.queryAccessibleInterface(first)
    assert accessible is not None
    name = accessible.text(QAccessible.Name)
    assert "DEMO PATIENT" in name and "PACS-DEMO" in name and "Synthetic study 0" in name
    assert QAccessibleActionInterface.pressAction() in accessible.actionInterface().actionNames()
    pacs_server.delay = True
    accessible.actionInterface().doAction(QAccessibleActionInterface.pressAction())
    wait_until(lambda: pacs.busy and pacs_server.entered.is_set())
    assert pacs.selectedStudyUid == STUDY + ".0"
    assert QAccessible.queryAccessibleInterface(second).state().disabled
    click(window, second)
    assert pacs.selectedStudyUid == STUDY + ".0"
    pacs_server.release.set()
    wait_until(lambda: not pacs.busy)
    pacs_server.delay = False
    click(window, second)
    wait_until(lambda: not pacs.busy and len(pacs.series) == 1)
    assert pacs.selectedStudyUid == STUDY + ".1"
    assert not warnings, warnings


def contrast(foreground, background):
    def luminance(color):
        values = [getattr(color, channel)() for channel in ("redF", "greenF", "blueF")]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    a, b = sorted((luminance(foreground), luminance(background)))
    return (b + 0.05) / (a + 0.05)


def verify_primary_render(window, button, palette, tmp_path):
    label = next(item for item in descendants(button)
                 if item.property("text") == button.property("text") and item.property("color") is not None)
    center = button.mapToScene(button.boundingRect().center()).toPoint()
    for state, token in (("normal", "primaryButtonBackground"), ("hover", "primaryButtonHover"),
                         ("pressed", "primaryButtonPressed"), ("disabled", "primaryButtonDisabled")):
        QTest.mouseMove(window, QPoint(1, 1))
        if state in ("hover", "pressed"):
            QTest.mouseMove(window, center)
        if state == "pressed":
            QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
        if state == "disabled":
            button.setProperty("enabled", False)
        QTest.qWait(120)
        background = button.property("background").property("color")
        foreground = label.property("color")
        assert background.name() == palette[token], (button.objectName(), state, background.name())
        assert foreground.name() == palette["textDisabled" if state == "disabled" else "textOnPrimary"]
        if state != "disabled":
            assert contrast(foreground, background) >= 4.5
        image = window.grabWindow()
        sample = button.mapToScene(QPointF(6, button.height() / 2))
        pixel = image.pixelColor(round(sample.x() * image.devicePixelRatio()),
                                 round(sample.y() * image.devicePixelRatio()))
        assert pixel.name() == background.name(), (state, pixel.name(), background.name())
        assert image.save(str(tmp_path / f"{button.objectName()}-{state}.png"))
        if state == "pressed":
            QTest.mouseMove(window, QPoint(1, 1))
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
        if state == "disabled":
            button.setProperty("enabled", True)


@pytest.mark.parametrize("theme", ["dark", "light", "graphite"])
def test_pacs_primary_actions_render_legible_shared_states(scene, pacs_server, tmp_path, theme):
    window, app, warnings = scene
    app.settingsController.setValue("appearance", "theme", theme)
    app.workspaceController.openPacs()
    verify_primary_render(window, find(window, "pacsConfigureEmpty"), app.appearanceController.colors, tmp_path)
    pacs = query_studies(window, app, pacs_server)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: not pacs.busy and len(pacs.series) == 1)
    click(window, find(window, "pacsSelectAll"))
    for name in ("pacsQueryStudies", "pacsImportSelected"):
        verify_primary_render(window, find(window, name), app.appearanceController.colors, tmp_path)
    assert not warnings, warnings


def test_profile_names_follow_visible_labels_and_language(scene, tmp_path):
    from PySide6.QtQml import QQmlEngine
    window, app, warnings = scene
    app.languageController.attach_engine(QQmlEngine.contextForObject(window).engine())
    app.workspaceController.openDataSources()
    click(window, find(window, "pacsAddProfile"))
    auth = find(window, "pacsProfileAuth")
    auth.setProperty("currentIndex", 1)
    expected = {
        "en-US": ["Connection name", "DICOMweb base URL", "Authentication", "Username", "Password", "Network timeout (seconds)"],
        "zh-CN": ["配置名称", "DICOMweb 根地址", "认证方式", "用户名", "密码", "网络超时（秒）"],
    }
    names = ["pacsProfileName", "pacsProfileUrl", "pacsProfileAuth", "pacsProfileUsername", "pacsProfileSecret", "pacsProfileTimeout"]
    for locale, labels in expected.items():
        app.languageController.selectLanguage(locale)
        auth.setProperty("currentIndex", 1)
        QTest.qWait(100)
        for object_name, label in zip(names, labels):
            accessible = QAccessible.queryAccessibleInterface(find(window, object_name))
            assert accessible.text(QAccessible.Name) == label
        assert window.grabWindow().save(str(tmp_path / f"pacs-profile-{locale}.png"))
        auth.setProperty("currentIndex", 2)
        secret = QAccessible.queryAccessibleInterface(find(window, "pacsProfileSecret"))
        assert secret.text(QAccessible.Name) == ("Access token" if locale == "en-US" else "访问令牌")
        auth.setProperty("currentIndex", 1)
    assert not warnings, warnings
