"""Mouse feedback on real navigation and viewport controls, without layout shifts."""
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import scene as navigation_scene, find, click
from test_display_tools_qml import display_panel, _find, _click, _visual_children
from test_series_sidebar import sidebar_scene
from qt_pointer import move_pointer


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_hover_fade_has_no_intermediate_flash(sidebar_scene, theme):
    """Compare actual composited pixels throughout the transition, not just its ends."""
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    app.workspaceController.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
    outside = QPoint(window.width() // 2, window.height() - 10)

    for name, selected in (('primaryTool-pan', False), ('primaryTool-zoom', False),
                           ('primaryTool-reset', False), ('openView-mpr', False),
                           ('primaryTool-pan', True)):
        button = find(window, name)
        if selected:
            click(window, button)
            assert button.property('checked')
        center = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        probe = button.mapToScene(QPointF(5, button.height() / 2))
        bounds = button.mapToScene(QPointF()), button.width(), button.height()

        def pixel():
            frame = window.grabWindow()
            color = frame.pixelColor(round(probe.x() * frame.width() / window.width()),
                                     round(probe.y() * frame.height() / window.height()))
            return color.red(), color.green(), color.blue()

        move_pointer(window, outside)
        QTest.qWait(150)
        idle = pixel()
        move_pointer(window, center)
        samples = []
        for _ in range(16):
            QTest.qWait(8)
            samples.append(pixel())
        hovered = samples[-1]
        assert button.property("hovered")
        if not selected:
            assert idle != hovered, (theme, name, idle, hovered)
        move_pointer(window, outside)
        for _ in range(16):
            QTest.qWait(8)
            samples.append(pixel())
        assert samples[-1] == idle
        # Reversing direction during the fade must also stay between the two states.
        for target in (center, outside, center, outside):
            move_pointer(window, target)
            for _ in range(4):
                QTest.qWait(8)
                samples.append(pixel())
        for sample in samples:
            assert all(min(a, b) - 2 <= value <= max(a, b) + 2
                       for value, a, b in zip(sample, idle, hovered)), (theme, name, idle, hovered, samples)
        assert bounds == (button.mapToScene(QPointF()), button.width(), button.height())
    assert not warnings, warnings


def feedback(window, button, *, disabled=False):
    outside = QPoint(2, window.height() - 2)
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    bounds = (button.mapToScene(QPointF()), button.width(), button.height())
    background = button.property("background")
    move_pointer(window, outside)
    QTest.qWait(120)
    idle = background.property("color")
    move_pointer(window, point)
    QTest.qWait(120)
    hover = background.property("color")
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(120)
    pressed = background.property("color")
    if disabled:
        assert idle != hover and hover == pressed
        assert not button.property("down")
    else:
        assert button.property("hovered") and button.property("down")
        assert len({c.name(c.NameFormat.HexArgb) for c in (idle, hover, pressed)}) == 3
    # Release outside cancels the command; it must restore the previous state.
    move_pointer(window, outside)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, outside)
    QTest.qWait(120)
    assert not button.property("down")
    assert background.property("color") == idle
    assert bounds == (button.mapToScene(QPointF()), button.width(), button.height())


def test_view_navigation_feedback_and_disabled_state(navigation_scene):
    window, workspace, series, warnings = navigation_scene
    feedback(window, find(window, "openView-2d"), disabled=True)
    click(window, find(window, "series-" + series.series_instance_uid))
    for name in ("openView-2d", "openView-mpr", "openView-3d", "openView-montage"):
        feedback(window, find(window, name))
    assert not workspace.tabs  # Canceled presses must not open any view.
    click(window, find(window, "openView-2d"))
    feedback(window, find(window, "openView-2d"))
    assert workspace.activeTabType == "2d" and len(workspace.tabs) == 1
    assert not warnings, "\n".join(warnings)


def test_primary_and_secondary_tools_feedback(display_panel, tmp_path):
    view, controller, warnings = display_panel
    root = view.rootObject()
    for name in ("primaryTool-pan", "primaryTool-zoom", "primaryTool-reset"):
        feedback(view, _find(root, name))
    _click(view, _find(root, "primaryTool-pan"))
    feedback(view, _find(root, "primaryTool-pan"))
    assert controller._tool_controller.activeTool == "pan"
    _click(view, _find(root, "primaryTool-window"))
    preset = next(i for i in _visual_children(root)
                  if i.objectName().startswith("windowPreset-") and i.isVisible())
    feedback(view, preset)
    _click(view, preset)
    feedback(view, preset)
    _click(view, _find(root, "primaryTool-pseudocolor"))
    feedback(view, _find(root, "colorMap-blackbody"))
    _click(view, _find(root, "colorMap-blackbody"))
    feedback(view, _find(root, "colorMap-blackbody"))
    assert controller.activeColorMap == "blackbody"
    assert view.grabWindow().save(str(tmp_path / "button-feedback.png"))
    assert not warnings, "\n".join(warnings)


def test_grouped_source_actions_have_no_nested_hover_outline(navigation_scene, tmp_path):
    from PySide6.QtQml import QQmlProperty
    window, workspace, series, warnings = navigation_scene
    from PySide6.QtCore import QObject, Property
    class Sources(QObject):
        localEnabled = Property(bool, lambda self: True, constant=True)
        pacsEnabled = Property(bool, lambda self: True, constant=True)
    sources = Sources()
    find(window, "leftPanel").setProperty("pacsController", sources)
    QTest.qWait(50)
    for name in ("sidebarOpenFolder", "sidebarPacs"):
        button = find(window, name)
        feedback(window, button)
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseMove(window, point)
        QTest.qWait(120)
        background = button.property("background")
        assert QQmlProperty.read(background, "border.width") == 0 or QQmlProperty.read(
            background, "border.color").alpha() == 0
        assert window.grabWindow().save(str(tmp_path / (name + "-hover.png")))
    # Keyboard focus still has an explicit, visible focus indication.
    button.forceActiveFocus(Qt.TabFocusReason)
    QTest.qWait(120)
    assert QQmlProperty.read(background, "border.width") == 2
    assert QQmlProperty.read(background, "border.color").alpha() > 0
    assert not warnings, "\n".join(warnings)
