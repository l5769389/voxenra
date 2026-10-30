"""Real tool clicks and pointer drags, with resulting display and MPR state checks."""
import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_sidebar_style_polish import reveal
from test_measurement_qml import _mouse_drag
from test_mpr_voi_qml import _owner


@pytest.mark.parametrize("tab_type", ["2d", "mpr"])
@pytest.mark.parametrize("compact", [False, True])
def test_toolbar_rotation_is_continuous_and_children_are_one_shot(sidebar_scene, tmp_path, tab_type, compact):
    window, app, records, warnings = sidebar_scene
    settings = app.settingsController
    settings.setValue("appearance", "toolLabels", True)
    settings.setValue("layout", "rightPanelCollapsed", compact)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, "Rotation check", tab_type)
    wait_until(lambda: ws.activeViewport.loadState == "ready")
    vp = ws.activeViewport
    QTest.qWait(100)
    rotate = find(window, ("compactTool-" if compact else "primaryTool-") + "rotate")
    if compact:
        rail = find(window, "compactToolRail")
        reveal(window, rail, rotate)
    else:
        click(window, rotate)
    assert vp.activeInteraction == "rotate"
    layer = next(item for item in descendants(window.contentItem())
                 if item.objectName() == "dicomPixelLayer" and item.isVisible()
                 and _owner(item) is vp)
    # The right-hand point on the initial MPR crosshair is deliberately used:
    # this must roll the display, not rotate a reconstruction plane.
    pivot = layer.mapToScene(QPointF(layer.width() / 2, layer.height() / 2))
    start = pivot + QPointF(70, 0)
    end = pivot + QPointF(70, 70)
    geometry = vp._frame_meta.geometry
    mpr = getattr(vp, "_mpr_state", None)
    others = {key: (v.rotationDegrees, getattr(v, "_mpr_state", None))
              for key, v in ws.activeTab.viewports_by_id.items() if v is not vp}
    _mouse_drag(window, start.toPoint(), end.toPoint())
    assert vp.rotationDegrees == pytest.approx(45, abs=1)
    assert getattr(vp, "_mpr_state", None) == mpr
    assert vp._frame_meta.geometry == geometry
    assert {key: (v.rotationDegrees, getattr(v, "_mpr_state", None))
            for key, v in ws.activeTab.viewports_by_id.items() if v is not vp} == others
    vector = layer.mapToScene(QPointF(1, 0)) - layer.mapToScene(QPointF(0, 0))
    assert math.degrees(math.atan2(vector.y(), vector.x())) == pytest.approx(45, abs=1)
    if tab_type == "mpr":
        crosshair = next(item for item in descendants(window.contentItem())
                         if item.objectName() == "mprCrosshairLayer" and _owner(item) is vp)
        assert crosshair.property("rotationDegrees") % 180 == pytest.approx(45, abs=1)
    before = vp.rotationDegrees
    prefix = "compactAction-" if compact else "rotateAction-"
    child = find(window, prefix + "rotate:cw90")
    if compact:
        reveal(window, rail, child)
    else:
        click(window, child)
    assert vp.rotationDegrees == pytest.approx(before + 90)
    assert vp.activeInteraction == "rotate"
    assert not child.property("checked")
    QTest.qWait(100)
    assert vp.rotationDegrees == pytest.approx(before + 90)
    assert window.grabWindow().save(str(tmp_path / f"rotation-{tab_type}-{compact}.png"))
    assert not warnings, warnings
