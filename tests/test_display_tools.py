from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QSize

from qt_dicom_viewer.core.pseudocolor import (
    COLOR_MAP_SPECS,
    apply_color_map,
    color_map_options,
)
from qt_dicom_viewer.model import ToolType, ViewportDisplaySettings
from qt_dicom_viewer.ui.controller.viewport.controller.text_annotation_controller import (
    TextAnnotationController,
)
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_viewport_transform import _controller, _render_result


def test_all_reference_color_maps_have_renderable_luts() -> None:
    pixels = np.array([[0, 64, 128, 255]], dtype=np.uint8)
    options = color_map_options()

    assert [option["label"] for option in options[:8]] == [
        "BW", "BW Inverse (1)", "Black Body (1)", "Cardiac",
        "Flow", "French", "GrayRainbow", "HotGreen",
    ]
    assert {option["colorMap"] for option in options} == set(COLOR_MAP_SPECS)

    for option in options:
        rendered = apply_color_map(pixels, option["colorMap"])
        expected_shape = pixels.shape if option["colorMap"].startswith("grayscale") else (1, 4, 3)
        assert rendered.shape == expected_shape
        assert rendered.dtype == np.uint8
        assert option["stops"][0]["position"] == 0.0
        assert option["stops"][-1]["position"] == 1.0

    assert np.array_equal(apply_color_map(pixels, "grayscale"), pixels)
    assert np.array_equal(
        apply_color_map(pixels, "grayscale-inverted"),
        255 - pixels,
    )
    with pytest.raises(ValueError, match="Unknown color map"):
        apply_color_map(pixels, "missing")


def test_image_provider_accepts_rgb_pseudocolor() -> None:
    provider = DicomImageProvider()
    rgb = np.zeros((3, 5, 3), dtype=np.uint8)
    rgb[:, :, 1] = 127
    provider.set_array("viewport", rgb)

    size = QSize()
    image = provider.requestImage("viewport/1", size, QSize())

    assert (size.width(), size.height()) == (5, 3)
    assert image.width() == 5
    assert image.height() == 3
    assert image.pixelColor(0, 0).green() == 127


def test_arrow_annotations_are_slice_scoped_selectable_and_editable() -> None:
    controller = TextAnnotationController()
    viewport = _controller()
    frame = replace(_render_result(viewport).frame_meta, slice_index=2)
    controller.set_frame("series-1", frame)
    controller.setAnnotationText("病灶 A")
    controller.setAnnotationColor("#66d0ff")
    controller.setAnnotationFontSize(24)
    controller.addAnnotation(12.5, 30.25, 52.5, 10.25)

    assert len(controller.annotationItems) == 1
    item = controller.annotationItems[0]
    assert item["text"] == "病灶 A"
    assert item["color"] == "#66d0ff"
    assert item["fontSize"] == 24
    assert item["tailColumn"] == 12.5
    assert item["tailRow"] == 30.25
    assert item["headColumn"] == 52.5
    assert item["headRow"] == 10.25
    assert controller.hasSelection

    controller.setAnnotationText("已编辑")
    assert controller.annotationItems[0]["text"] == "已编辑"

    controller.set_current_slice(3)
    assert controller.annotationItems == []
    assert not controller.hasSelection
    controller.set_current_slice(2)
    assert controller.annotationItems[0]["text"] == "已编辑"

    controller.clearSelection()
    controller.selectAnnotationAt(32.5, 20.25, 2)
    assert controller.selectedAnnotationId == item["annotationId"]
    controller.selectAnnotationAt(80, 80, 2)
    assert not controller.hasSelection

    shifted = replace(
        frame,
        geometry=replace(
            frame.geometry,
            image_position_patient=(1.0, 0.0, 0.0),
        ),
    )
    controller.set_frame("series-1", shifted)
    assert controller.annotationItems == []
    controller.set_frame("series-1", frame)
    assert controller.annotationItems[0]["text"] == "已编辑"

    controller.selectAnnotation(item["annotationId"])
    controller.deleteSelected()
    assert controller.annotationItems == []


def test_arrow_annotation_draft_becomes_completed_on_finish() -> None:
    controller = TextAnnotationController()
    viewport = _controller()
    frame = _render_result(viewport).frame_meta
    controller.set_frame("series-1", frame)

    assert controller.beginAnnotation(10, 20)
    assert controller.annotationItems[0]["draft"]
    assert controller.annotationItems[0]["headColumn"] == 10
    assert controller.annotationItems[0]["headRow"] == 20

    controller.updateAnnotation(45, 55)
    assert controller.annotationItems[0]["draft"]
    assert controller.annotationItems[0]["headColumn"] == 45
    assert controller.annotationItems[0]["headRow"] == 55

    controller.finishAnnotation(50, 60)
    assert not controller.annotationItems[0]["draft"]
    assert controller.annotationItems[0]["headColumn"] == 50
    assert controller.annotationItems[0]["headRow"] == 60


def test_viewport_applies_color_map_settings_and_annotation_reset() -> None:
    viewport = _controller()
    viewport.handleRenderResult(_render_result(viewport))
    requests = []
    viewport.renderRequested.connect(requests.append)

    viewport.applyColorMap("blackbody")
    assert viewport.activeColorMap == "blackbody"
    assert requests[-1].color_map == "blackbody"
    assert len(viewport.activeColorMapStops) >= 2

    viewport.setViewportSetting("window-annotations", False)
    viewport.setViewportSetting("hide-sensitive-info", True)
    viewport.setViewportSetting("scale-bar", True)
    viewport.setViewportSetting("color-bar", True)
    viewport.setViewportSetting("dicom-overlay", False)
    viewport.setViewportSetting("localizer", False)
    viewport.setViewportSetting("fit-to-window", False)
    assert not viewport.showWindowAnnotations
    assert viewport.hideSensitiveInfo
    assert viewport.showScaleBar
    assert viewport.showColorBar
    assert not viewport.showDicomOverlay
    assert not viewport.showLocalizer
    assert not viewport.fitToWindow

    tools = viewport._tool_controller
    tools.activateTool("annotate")
    viewport.setAnnotationMode(True)
    viewport.textAnnotationController.setAnnotationText("重点")
    viewport.beginInteraction(50, 60, 1, True, 20, 25, 8, 6)
    viewport.updateInteraction(
        QPointF(50, 60),
        QPointF(100, 90),
        QPointF(50, 30),
        QPointF(50, 30),
        True,
        70,
        55,
    )
    viewport.endInteraction(100, 90, True, 70, 55)
    assert len(viewport.textAnnotationController.annotationItems) == 1

    viewport.reset_tool_state(ToolType.ANNOTATE)
    assert viewport.textAnnotationController.annotationItems == []
    viewport.reset_tool_state(ToolType.PSEUDOCOLOR)
    assert viewport.activeColorMap == "grayscale"
    viewport.reset_tool_state(ToolType.VIEWPORT_SETTINGS)
    assert viewport.viewport_state.display_settings == ViewportDisplaySettings()


def test_palette_display_changes_preserve_every_persisted_id_and_lut():
    import hashlib
    from qt_dicom_viewer.core.pseudocolor import color_lut
    from qt_dicom_viewer.core.color_maps import COLOR_MAPS
    expected = {'grayscale': '72432263dbfe17abc40ed269f24c7a344e077e3671007dfc8a2f3851f8193dc2',
     'grayscale-inverted': '346f6a25ad11ec5b45a83392366f269058ba209d2877491634a2405f86beb3db',
     'blackbody': 'ee5b6f9b99b522130653f800bb60c51f774172fd8efbf14a7f1853f635cc39ff',
     'cardiac': '65b6e2d696dd640fa90ad83fdb61dc29395b53de3341041fb0ad6311d1355c92',
     'flow': 'ed5006283adaf048886852342f318a21a3a5f07ee5a26a05b1856fd3dd3daef6',
     'french': '16a315d3167716f0b74e7fb203c51979f0016affaf90781249e953623ad580e4',
     'gray-rainbow': 'a90250d3756fdcd3e86fc55ef1f7fced907550f9269488114488ec1ec85f9475',
     'hot-green': 'd11e6bd139463f91b73b9582165da0dbe0670ad8260c70b037cd0492081eabea',
     'hot-iron': 'a36d6e35c477b59171f953a6783ff86e357b978f9e70a2fdc1855fae04ec5444',
     'rainbow': 'a78ac3c0dd47659101c55c6be6d97e8f1010c014b323329aafb83bbd9c4ee49f',
     'bwInverse': '346f6a25ad11ec5b45a83392366f269058ba209d2877491634a2405f86beb3db',
     'blackBody': '43dd16b22a010a4c1c80c77cdb38145a31e4f4c4162f2cd9eec5ea7f67f69a53',
     'hotIron': 'd0b49d2e7df508618025ff33d491a83767144b2368cd054a5b707834a12c016f',
     'hotMetal': 'e97edba93c29700451f89c7f4e2ec36beba424bf9118d21ae77887738ae30ea8',
     'pet': '1dedd9dbef666f0ff0435582b3493328d18ca93de17e28b67c9d3055071ca381'}
    assert set(COLOR_MAP_SPECS) == set(expected)
    assert {key: hashlib.sha256(color_lut(key).tobytes()).hexdigest()
            for key in COLOR_MAP_SPECS} == expected
    options = color_map_options()
    assert len({option["label"] for option in options}) == len(options)
    assert {option["colorMap"]: option["label"] for option in options} == {
        key: label for key, (label, _) in COLOR_MAPS.items()}
