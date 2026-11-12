"""Real tool clicks and pointer drags, with resulting display and MPR state checks."""
import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants, settled_point
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
    viewport = find(window, "imageViewport-" + vp.viewportId)
    rotate = find(window, ("compactTool-" if compact else "primaryTool-") + "rotate")
    if compact:
        rail = find(window, "compactToolRail")
        reveal(window, rail, rotate)
    else:
        click(window, rotate)
    assert vp.activeInteraction == "rotate"
    def pixel_layer():
        return next((item for item in descendants(viewport)
                     if item.objectName() == "dicomPixelLayer" and item.isVisible()
                     and item.width() > 0 and item.height() > 0 and _owner(item) is vp), None)
    wait_until(lambda: pixel_layer() is not None)
    layer = pixel_layer()
    settled_point(layer)
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


@pytest.mark.parametrize('tab_type',['2d','mpr'])
def test_existing_measurement_follows_mirror_and_toolbar_reset(sidebar_scene,tab_type,tmp_path):
    from test_measurement_qml import _click_points, _scene
    window,app,records,warnings=sidebar_scene
    ws=app.workspaceController
    ws.createTab(records[0].series_instance_uid,'Mirror reset',tab_type)
    wait_until(lambda:ws.activeViewport.loadState=='ready')
    vp=ws.activeViewport
    viewport=find(window,'imageViewport-'+vp.viewportId)
    pixel=lambda:next((i for i in descendants(viewport) if i.objectName()=='dicomPixelLayer' and i.width()>0 and _owner(i) is vp),None)
    wait_until(lambda:pixel() is not None)
    layer=pixel();settled_point(layer)
    vp._tool_controller.selectInteraction('measure:length')
    _click_points(window,_scene(layer,layer.width()*.25,layer.height()*.3),_scene(layer,layer.width()*.65,layer.height()*.55))
    original=vp.measurementController.measurementItems[0]
    for action in ['rotate:mirror-h','rotate:cw90','rotate:mirror-v','reset']:
        if action=='reset':
            # Exercise the actual scoped Reset button after selecting Rotate.
            click(window,find(window,'primaryTool-rotate'))
            click(window,find(window,'activeToolReset'))
        else:vp.applyTransformAction(action)
        QTest.qWait(40)
        item=next(i for i in descendants(viewport) if i.objectName()=='measurementItem' and not i.property('isDraft'))
        actual=item.property('mappedPoints').toVariant()
        for a,p in zip(actual,original['points']):
            expected=layer.mapToItem(item,QPointF(p['column']+.5,p['row']+.5))
            assert a.x()==pytest.approx(expected.x(),abs=.01)
            assert a.y()==pytest.approx(expected.y(),abs=.01)
        assert vp.measurementController.measurementItems[0]['points']==original['points']
        if action=='reset':
            assert not vp.horizontalFlip and not vp.verticalFlip and vp.rotationDegrees==0
    assert window.grabWindow().save(str(tmp_path/f'mirror-reset-{tab_type}.png'))
    assert not warnings,warnings
