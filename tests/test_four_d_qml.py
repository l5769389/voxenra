"""Exercise the 4D playback controls through a real offscreen QML view."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import SeriesDisplayMeta, TabConfig, TabType
from qt_dicom_viewer.ui.controller.tab.tab_controller import TabController
from test_measurement_qml import _visual_children, qt_app


def _controller(tab_type: TabType = TabType.FOUR_D) -> TabController:
    meta = SeriesDisplayMeta(
        patient_name="4D Example",
        patient_id="P4D",
        study_description="Perfusion",
        series_description="Dynamic CT",
        modality="CT",
        series_uid="series-4d",
        phase_identifiers=(1, 2, 3, 4, 5, 6),
        supports_four_d=True,
    )
    return TabController(
        TabConfig("test-tab", tab_type.value, tab_type, (meta,))
    )


@pytest.fixture
def four_d_panel(qt_app, request):
    controller = _controller()
    if getattr(request, "param", True):
        from qt_dicom_viewer.model import MprFrame
        from test_four_d import _finish_requests
        requests = []
        controller.renderRequested.connect(requests.append)
        controller.init_render()
        _finish_requests(controller, requests, MprFrame.standard_lps((10., 20., 30.)))
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(280, 760)
    warnings = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "toolController": controller.toolController,
        "toolVisible": True,
        "viewportController": controller.activeViewport,
        "tabController": controller,
    })
    source = (
        Path(__file__).resolve().parents[1]
        / "src/qt_dicom_viewer/qml/sections/RightPanel.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [
        error.toString() for error in view.errors()
    ]
    view.show()
    QTest.qWait(100)
    try:
        yield view, controller, warnings
    finally:
        controller.pausePlayback()
        view.hide()
        delete(view)


def _find(view: QQuickView, name: str):
    from toolbar_navigation import reveal_primary_tool
    reveal_primary_tool(view.rootObject(), name)
    return next(
        item
        for item in _visual_children(view.rootObject())
        if item.objectName() == name and item.isVisible()
    )


def _click(view: QQuickView, item) -> None:
    center = item.mapToScene(
        QPointF(item.width() / 2, item.height() / 2)
    ).toPoint()
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, center)
    QTest.qWait(40)


def test_play_tool_opens_secondary_panel_and_controls_playback(
    four_d_panel,
    tmp_path,
) -> None:
    view, controller, warnings = four_d_panel
    play_tool = _find(view, "primaryTool-play")
    window_tool = _find(view, "primaryTool-window")

    assert not any(
        item.objectName() == "fourDPlaybackPanel" and item.isVisible()
        for item in _visual_children(view.rootObject())
    )
    _click(view, play_tool)

    panel = _find(view, "fourDPlaybackPanel")
    play_button = _find(view, "phasePlaybackButton")

    assert controller.toolController.activePanel == "play"
    assert panel.mapToScene(QPointF()).y() > play_tool.mapToScene(QPointF()).y()
    assert 44 <= play_button.width() <= 48
    assert play_button.height() <= play_button.parentItem().height()
    grid = _find(view, "phaseGrid")
    last_phase = _find(view, "phaseButton-5")
    last_y = last_phase.mapToItem(grid, QPointF()).y()
    assert last_y + last_phase.height() <= grid.height()
    assert play_button.property("checked")
    assert controller.playing
    assert play_button.property("checked")
    assert play_tool.property("enabled")
    assert not window_tool.property("enabled")
    _click(view, window_tool)
    assert controller.toolController.activePanel == "play"
    _click(view, play_tool)
    assert not controller.playing
    assert window_tool.property("enabled")

    screenshot = view.grabWindow()
    assert not screenshot.isNull()
    output = tmp_path / "four-d-panel.png"
    assert screenshot.save(str(output))
    print(f"QML preview: {output}")
    assert not warnings, warnings


def test_four_d_panel_updates_fps_and_accepts_phase_click(
    four_d_panel,
) -> None:
    view, controller, warnings = four_d_panel
    _click(view, _find(view, "primaryTool-play"))
    fps_slider = _find(view, "fpsSlider")
    fps_value = _find(view, "fpsValue")
    first_phase_button = _find(view, "phaseButton-0")
    phase_button = _find(view, "phaseButton-1")
    fifth_phase_button = _find(view, "phaseButton-4")
    sixth_phase_button = _find(view, "phaseButton-5")

    assert fps_slider.property("from") == 1.0
    assert fps_slider.property("to") == 15.0
    assert fps_slider.property("value") == 2.0
    controller.setFps(13)
    QTest.qWait(20)
    assert fps_slider.property("value") == 13.0
    assert fps_value.property("text") == "13"
    assert first_phase_button.property("checked")
    assert fifth_phase_button.mapToScene(QPointF()).y() == pytest.approx(
        first_phase_button.mapToScene(QPointF()).y()
    )
    assert sixth_phase_button.mapToScene(QPointF()).y() > (
        first_phase_button.mapToScene(QPointF()).y()
    )

    controller._phase_timer.stop()
    _click(view, phase_button)
    assert controller._rendering_phase_index == 1
    assert not warnings, warnings


def test_mpr_right_panel_offers_slice_playback_after_loading(qt_app) -> None:
    controller = _controller(TabType.MPR)
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(280, 640)
    warnings = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "toolController": controller.toolController,
        "toolVisible": True,
        "viewportController": controller.activeViewport,
        "tabController": controller,
    })
    source = (
        Path(__file__).resolve().parents[1]
        / "src/qt_dicom_viewer/qml/sections/RightPanel.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(40)
    try:
        _find(view, "primaryTool-play")
        assert any(
            item.objectName() == "primaryTool-play" and item.isVisible()
            for item in _visual_children(view.rootObject())
        )
        assert not any(
            item.objectName() == "fourDPlaybackPanel" and item.isVisible()
            for item in _visual_children(view.rootObject())
        )
        assert not warnings, warnings
    finally:
        view.hide()
        delete(view)


def test_collapsed_four_d_play_button_toggles_stop_and_blocks_other_tools(four_d_panel):
    view, controller, warnings = four_d_panel
    view.rootObject().setProperty('collapsed', True)
    view.resize(52, 760)
    QTest.qWait(40)
    play = _find(view, 'compactTool-play')
    assert play.parentItem().property('iconName') == 'cine-4d-play'
    _click(view, play)
    assert controller.playing
    assert play.property('checked')
    assert play.parentItem().property('iconName') == 'cine-4d-stop'
    assert not _find(view, 'compactTool-window').property('enabled')
    view.rootObject().setProperty('collapsed', False)
    view.resize(280, 760)
    QTest.qWait(40)
    assert controller.playing
    assert _find(view, 'primaryTool-play').parentItem().property('iconName') == 'cine-4d-stop'
    _click(view, _find(view, 'primaryTool-play'))
    assert not controller.playing
    assert not warnings, warnings


def test_four_d_playback_controls_remain_when_reference_volume_is_selected(four_d_panel):
    view, controller, warnings = four_d_panel
    controller.mprLayout.setLayout('quad')
    controller.mprLayout.activate()
    view.rootObject().setProperty('toolController', controller.activeToolController)
    view.rootObject().setProperty('viewportController', controller.activeViewport)
    QTest.qWait(40)
    _click(view, _find(view, 'primaryTool-play'))
    assert controller.playing
    _find(view, 'fourDPlaybackPanel')
    _click(view, _find(view, 'phasePlaybackButton'))
    assert not controller.playing
    view.rootObject().setProperty('collapsed', True)
    view.resize(52, 760)
    QTest.qWait(40)
    play = _find(view, 'compactTool-play')
    _click(view, play)
    assert controller.playing
    assert play.parentItem().property('iconName') == 'cine-4d-stop'
    _click(view, play)
    assert not controller.playing
    assert not warnings, warnings


@pytest.mark.parametrize('four_d_panel', [False], indirect=True)
def test_unloaded_four_d_play_buttons_are_disabled(four_d_panel):
    view, controller, warnings = four_d_panel
    assert not _find(view, 'primaryTool-play').isEnabled()
    assert not _find(view, 'primaryTool-slice-play').isEnabled()
    view.rootObject().setProperty('collapsed', True)
    view.resize(52, 760)
    QTest.qWait(40)
    assert not _find(view, 'compactTool-play').isEnabled()
    assert not _find(view, 'compactTool-slice-play').isEnabled()
    assert not controller.playing and not warnings
