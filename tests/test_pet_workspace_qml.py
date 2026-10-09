from pathlib import Path
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QUrl, Qt, QPoint, QPointF, QMetaObject
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_pet_fusion import paired_series
from test_measurement_qml import qt_app, _visual_children, _scene, _mouse_drag
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.core.pet_reconstruction import PetReconstructor
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.service.render_serivce import RenderService
from test_dicom_tags import wait_until


@pytest.mark.parametrize("fusion", [False, True])
def test_real_pet_workspace(qt_app, paired_series, tmp_path, fusion):
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    panel = PanelController(series_catalog=catalog)
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 2, 2, 0, [ct, pet]))
    service = RenderService(catalog, VolumeManager())
    workspace.renderRequested.connect(service.submit)
    service.rendered.connect(workspace.handleRenderResult)
    service.failed.connect(workspace.handleRenderFailure)
    if fusion:
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    else:
        workspace.createTab(pet.series_instance_uid, "PET MPR", "mpr")
    tab = next(iter(workspace._tab_dict.values()))
    wait_until(lambda: tab.ready)
    tab.toolController.selectInteraction("window")
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1540, 1000)
    view.engine().addImageProvider("dicom", provider)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties({"workspace": workspace, "panel": panel})
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/PetWorkspace.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(80)
    try:
        items = list(_visual_children(view.rootObject()))
        layers = [x for x in items if x.objectName() == "dicomPixelLayer"]
        assert len(layers) == (4 if fusion else 3)
        assert any(x.objectName() == ("fusionCtWindowPanel" if fusion else "petWorkspacePanel") and x.isVisible() for x in items)
        assert not any(x.objectName() == "petRegistrationPanel" and x.isVisible() for x in items)
        crosshairs = [x for x in items if x.objectName() == "mprCrosshairLayer"]
        assert len(crosshairs) == (4 if fusion else 3)
        assert all(x.property("armLength") == 8 for x in crosshairs)
        assert not any(x.objectName() in ("petColorMap", "fusionColorMap", "fusionOpacity") for x in items)
        if fusion:
            # Hit the visible arm, even while another tool is selected. The
            # real PointerHandler must latch the decision before DragHandler.
            locator_view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "fusion")
            original_center = tab._target_mpr_state.frame.center_patient
            original_matrix = tab.matrix.copy()
            for tool in ("window", "measure:rect", "annotate:text", "registration"):
                if tool == "registration":
                    tab.setRegistrationActive(True)
                else:
                    tab.toolController.selectInteraction(tool)
                QTest.qWait(20)
                center = locator_view._crosshair_image_position
                press = _scene(layers[2], center.column, center.row) + QPoint(12, 0)
                before_window = locator_view.current_window
                QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, press)
                assert locator_view._locator_press is not None, tool
                QTest.mouseMove(view, press + QPoint(24, 18), 20)
                assert locator_view._locator_drag is not None, tool
                QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, press + QPoint(35, 23))
                wait_until(lambda: tab._requested == tab._committed_request)
                assert not np.allclose(tab._target_mpr_state.frame.center_patient, original_center), tool
                np.testing.assert_array_equal(tab.matrix, original_matrix)
                assert locator_view.current_window == before_window
                assert not locator_view.measurementController.measurementItems
                assert not locator_view._annotation_drag_active
                tab.move_center(original_center)
                wait_until(lambda: tab._requested == tab._committed_request)
            tab.toolController.selectInteraction("window")
            QTest.qWait(20)
            mip_view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "mip")
            mip_result, center = mip_view._mip_result, mip_view.crosshairImagePosition
            row, col = np.unravel_index(np.nanargmax(mip_result.modality_pixel), mip_result.modality_pixel.shape)
            press = _scene(layers[3], center.x(), center.y()) + QPoint(12, 0)
            target = _scene(layers[3], col, row) + QPoint(12, 0)
            QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, press)
            assert mip_view._locator_press is not None
            QTest.mouseMove(view, target, 20)
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, target)
            wait_until(lambda: tab._requested == tab._committed_request)
            np.testing.assert_allclose(tab._target_mpr_state.frame.center_patient, mip_result.peak_positions[row, col])
            tab.move_center(original_center)
            wait_until(lambda: tab._requested == tab._committed_request)
            # Direction is one linked workspace choice; duplicate pane bars are gone.
            items = list(_visual_children(view.rootObject()))
            assert not any(x.objectName().startswith("viewportPlane-") or x.objectName() == "fusionLinkedPlanes" for x in items)
            volume_button = next(x for x in items if x.objectName() == "openFusion3D")
            assert volume_button.isVisible() and volume_button.x() < 400
            tab.setPlane("coronal")
            wait_until(lambda: tab._requested == tab._committed_request)
            assert {v.viewportType for v in tab.viewports_by_id.values() if v.viewportRole != "mip"} == {"coronal"}
            tab.setPlane("axial")
            wait_until(lambda: tab._requested == tab._committed_request)
            # Each unbroken field elides on one line inside its half-view.
            configs = {v.viewportId: v.viewport_config for v in tab.viewports_by_id.values()}
            for v in tab.viewports_by_id.values():
                v.viewport_config = replace(v.viewport_config, series_meta=replace(
                    v.viewport_config.series_meta, patient_name="LongUnbrokenPatientName" * 20,
                    patient_id="HiddenPatientIdentifier", series_description="长序列说明" * 40))
                v.overlayChanged.emit()
            settings = tab.toolController.settingsController
            corners = {c: settings.values["corners"][c] for c in ("topLeft", "topRight", "bottomLeft", "bottomRight")}
            tab.setCompactOverlay(False)
            for corner in corners:
                settings.setValue("corners", corner, ["patientName", "patientId", "seriesDescription", "window"])
            view.resize(1150, 780)
            QTest.qWait(80)
            corner_items = [x for x in _visual_children(view.rootObject()) if x.objectName().startswith("overlay-")]
            assert len(corner_items) == 16
            for item in corner_items:
                assert "ID:" not in item.property("text") and "HiddenPatientIdentifier" not in item.property("text")
                assert 0 < item.width() < item.parentItem().width()/2
                assert item.height() < item.parentItem().height()/2
                rows = [x for x in _visual_children(item) if x.objectName() == "cornerInformationLine"]
                assert rows and any(row.property("truncated") for row in rows)
                assert all(row.property("lineCount") == 1 for row in rows)
            assert view.grabWindow().save(str(tmp_path / "petct-long-overlays.png"))
            for v in tab.viewports_by_id.values():
                v.viewport_config = configs[v.viewportId]
                v.overlayChanged.emit()
            for corner, fields in corners.items():
                settings.setValue("corners", corner, fields)
            tab.setCompactOverlay(True)
            view.resize(1540, 1000)
            QTest.qWait(50)
        def click_named(name):
            from toolbar_navigation import reveal_primary_tool
            reveal_primary_tool(view.rootObject(), name)
            item = next(x for x in _visual_children(view.rootObject()) if x.objectName() == name and x.isVisible())
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                            item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint())
            QTest.qWait(20)
        if fusion:
            click_named("primaryTool-viewport-settings")
            def named(name):
                return next(x for x in _visual_children(view.rootObject()) if x.objectName() == name and x.isVisible())
            assert named("petLocator-compact").property("checked")
            assert named("petInfo-compact").property("checked")
            click_named("petLocator-lines")
            assert not tab.compactCrosshair and named("petLocator-lines").property("checked")
            assert all(x.property("armLength") > 100 for x in crosshairs), [(x.property("armLength"), x.property("crosshairStyle")) for x in crosshairs]
            assert not named("petLocator-compact").property("checked")
            click_named("petLocator-lines")
            assert named("petLocator-lines").property("checked")  # cannot uncheck both
            detail = named("petInfo-detail")
            assert detail.property("baseBorderWidth") == 1 and detail.property("hoverEnabled")
            detail.forceActiveFocus(Qt.TabFocusReason)
            assert detail.property("visualFocus")
            QTest.keyClick(view, Qt.Key_Space)
            assert not tab.compactOverlay and detail.property("checked")
            assert all(not v.overlayInfo["compactOverlay"] for v in tab.viewports_by_id.values())
            # Check the rendered bindings too: a derived Python property can
            # report the new mode while QML still listens to its base notifier.
            def source_count_labels():
                return [x for x in _visual_children(view.rootObject())
                        if x.objectName().startswith("overlay-")
                        and "Source images: " in x.property("text")]
            assert len(source_count_labels()) == 3
            assert view.grabWindow().save(str(tmp_path / "petct-viewport-settings.png"))
            click_named("petLocator-compact")
            assert all(x.property("armLength") == 8 for x in crosshairs)
            click_named("petInfo-compact")
            assert not source_count_labels()
            click_named("primaryTool-ct-window")
            assert named("fusionCtWindowPanel") and named("primaryTool-ct-window").property("checked")
            assert not any(x.objectName() == "petControlUpperInput" for x in _visual_children(view.rootObject()))
            assert view.grabWindow().save(str(tmp_path / "petct-ct-window.png"))
            click_named("primaryTool-pet-window")
            assert named("petWorkspacePanel") and named("primaryTool-pet-window").property("checked")
            assert not any(x.objectName() == "fusionCtCenter" for x in _visual_children(view.rootObject()))
            assert view.grabWindow().save(str(tmp_path / "petct-pet-window.png"))
            # Actual QML mouse drags and reset buttons: the selected modality
            # owns the gesture in the fused pane; ineligible panes ignore it.
            for tool, eligible in (("ct-window", {0, 2}), ("pet-window", {1, 2, 3})):
                click_named("primaryTool-" + tool)
                for index, layer in enumerate(layers):
                    ct_before, pet_before = tab._ct_window, tab.pet_display.target
                    _mouse_drag(view, _scene(layer, .2, .2), _scene(layer, .65, .4))
                    wait_until(lambda: tab._requested == tab._committed_request)
                    assert (tab._ct_window != ct_before) == (tool == "ct-window" and index in eligible)
                    assert (tab.pet_display.target != pet_before) == (tool == "pet-window" and index in eligible)
                other = tab.pet_display.target if tool == "ct-window" else tab._ct_window
                click_named("activeToolReset")
                wait_until(lambda: tab._requested == tab._committed_request)
                assert (tab.pet_display.target if tool == "ct-window" else tab._ct_window) == other
        click_named("primaryTool-pseudocolor")
        click_named("paletteTarget-pet")
        tab.toolController.settingsController.setValue("colormap", "pet", "cardiac")
        QTest.qWait(30)
        assert next(x for x in _visual_children(view.rootObject())
                    if x.objectName() == "colorMap-cardiac").property("checked")
        assert all(v.activeColorMap == "cardiac" for v in tab.viewports_by_id.values()
                   if v.viewportRole not in ("ct", "fusion"))
        if fusion:
            click_named("paletteTarget-fusion")
            click_named("colorMap-hotMetal")
            assert tab.fusionColorMap == "hotMetal" and tab.petColorMap == "cardiac"
            tab.setPetColorMap("grayscale-inverted")
            wait_until(lambda: tab._committed_request == tab._requested)
            assert view.grabWindow().save(str(tmp_path / "petct-colors.png"))
            click_named("primaryTool-fusion-blend")
            click_named("fusionOpacity-75")
            assert tab.opacity == .75
            assert tab.fusionColorMap == "hotMetal" and tab.petColorMap == "grayscale-inverted"
            wait_until(lambda: tab._committed_request == tab._requested)
            assert view.grabWindow().save(str(tmp_path / "petct-blend.png"))
        click_named("primaryTool-pet-window" if fusion else "primaryTool-window")
        items = list(_visual_children(view.rootObject()))
        kbq = next(x for x in items if x.objectName() == "petUnit-kbqml")
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                        kbq.mapToScene(QPointF(kbq.width()/2, kbq.height()/2)).toPoint())
        wait_until(lambda: tab.petController.petActiveUnitId == "kbqml")
        assert tab.petController.petActiveUnitId == "kbqml"
        assert tab.petController.petControlUpper == 15
        if fusion:
            mip = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "mip")
            result = mip._mip_result
            row, col = np.unravel_index(np.nanargmax(result.modality_pixel), result.modality_pixel.shape)
            peak = result.peak_positions[row, col].copy()
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(layers[3], col, row))
            wait_until(lambda: np.allclose(tab._target_mpr_state.frame.center_patient, peak))
            np.testing.assert_allclose(tab._target_mpr_state.frame.center_patient, peak)
        if fusion:
            click_named("primaryTool-registration")
            assert tab.registrationActive
            registration_items = list(_visual_children(view.rootObject()))
            assert any(x.objectName() == "petRegistrationPanel" and x.isVisible() for x in registration_items)
            assert not any(x.objectName() == "petWorkspacePanel" and x.isVisible() for x in registration_items)
            assert view.grabWindow().save(str(tmp_path / "petct-registration.png"))
            before = tab.matrix.copy()
            fusion_view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "fusion")
            before_image = provider._images[fusion_view.viewportId].copy()
            before_source = fusion_view.imageSource
            QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, _scene(layers[2], 1., 1.))
            QTest.mouseMove(view, _scene(layers[2], 1.5, 1.), 20)
            QTest.mouseMove(view, _scene(layers[2], 2., 1.), 20)
            # The mouse is still held: verify actual worker output reaches QML.
            wait_until(lambda: mip._mip_result.preview and fusion_view.imageSource != before_source)
            assert tab._registration_dragging
            assert provider._images[fusion_view.viewportId] != before_image
            assert "registrationPreview" in mip.overlayInfo
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, _scene(layers[2], 2., 1.))
            wait_until(lambda: not mip._mip_result.preview)
            assert not np.allclose(tab.matrix, before)
            assert tuple(tab.matrix.ravel()) == tab._committed_request.transform
            before = tab.matrix.copy()
            QTest.mousePress(view, Qt.RightButton, Qt.NoModifier, _scene(layers[2], .5, .5))
            QTest.mouseMove(view, _scene(layers[2], 1., 1.), 20)
            QTest.mouseMove(view, _scene(layers[2], .5, 1.5), 20)
            QTest.mouseRelease(view, Qt.RightButton, Qt.NoModifier, _scene(layers[2], .5, 1.5))
            wait_until(lambda: tab._committed_request == tab._requested)
            assert not np.allclose(tab.matrix[:3, :3], before[:3, :3])
            parameter = next(x for x in _visual_children(view.rootObject())
                             if x.objectName() == "registrationParameter-0")
            parameter.forceActiveFocus()
            QMetaObject.invokeMethod(parameter, "selectAll")
            QTest.keyClick(view, "3")
            assert tab.registrationParameters[0] == pytest.approx(3)
            wait_until(lambda: not tab._requested.preview and tab._committed_request == tab._requested)
            QTest.keyClick(view, Qt.Key_Escape)
            assert not tab.registrationActive
            tab.setPlane("coronal")
            wait_until(lambda: tab._committed_request == tab._requested)
        if fusion:
            click_named("primaryTool-pet-window")
        # Enter a large custom control value; formatting must keep trailing zeros.
        items = list(_visual_children(view.rootObject()))
        control = next(x for x in items if x.objectName() == "petControlUpperInput")
        control.forceActiveFocus()
        display_upper = tab.petController.petDisplayUpper
        QMetaObject.invokeMethod(control, "selectAll")
        for char in "10000":
            QTest.keyClick(view, char)
            QTest.qWait(15)  # Let asynchronous frames arrive between keystrokes.
        QTest.keyClick(view, Qt.Key_Return)
        wait_until(lambda: tab._committed_request == tab._requested)
        assert tab.petController.petControlUpper == 10000
        assert control.property("text") == "10000"
        assert tab.petController.petDisplayUpper == display_upper
        assert not warnings, warnings
        preview = tmp_path / ("petct-fusion.png" if fusion else "pet-mpr.png")
        assert view.grabWindow().save(str(preview))
        print(f"PET workspace preview: {preview}")
    finally:
        view.hide()
        delete(view)
        service.shutdown()
        workspace.shutdown()
        panel.shutdown()


def test_main_qml_two_selection_entry_points(qt_app, paired_series, tmp_path):
    from PySide6.QtQml import QQmlApplicationEngine
    from test_tag_qml import _App, find, click
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    panel = PanelController(series_catalog=catalog)
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 2, 2, 0, [ct, pet]))
    panel.fusionCreateRequested.connect(workspace.createFusionTab)
    renderer = PetReconstructor(catalog, VolumeManager())
    workspace.renderRequested.connect(lambda r: workspace.handleRenderResult(renderer.render(r)))
    app = _App(workspace, panel)
    engine = QQmlApplicationEngine()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    engine.addImageProvider("navigation", SvgIconProvider())
    engine.addImageProvider("dicom", provider)
    engine.rootContext().setContextProperty("appController", app)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/Main.qml")))
    window = engine.rootObjects()[0]
    QTest.qWait(40)
    try:
        click(window, find(window, "series-" + pet.series_instance_uid))
        item = find(window, "series-" + ct.series_instance_uid)
        pos = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.ControlModifier, pos)
        QTest.qWait(20)
        assert len(panel.selectedSeriesUids) == 2
        # Checkboxes must support additive selection without a keyboard modifier.
        panel.selectSeries(pet.series_instance_uid)
        click(window, find(window, "selectSeries-" + ct.series_instance_uid))
        assert set(panel.selectedSeriesUids) == {pet.series_instance_uid, ct.series_instance_uid}
        click(window, find(window, "openView-fusion"))
        assert workspace.activeTabType == "petctfusion"
        assert len(workspace.currentTabAllViewports) == 4
        click(window, find(window, "series-" + ct.series_instance_uid))
        click(window, find(window, "openView-fusion"))
        assert panel.fusionDialogOpen
        candidates = find(window, "fusionCandidates")
        assert candidates.property("count") == 1
        assert window.grabWindow().save(str(tmp_path / "petct-pairing.png"))
        # Candidate is the first visual delegate within ListView's content item.
        candidate = find(window, "fusionCandidate-" + pet.series_instance_uid)
        click(window, candidate)
        click(window, find(window, "confirmFusion"))
        assert not panel.fusionDialogOpen
        assert len(workspace.tabs) == 1
        assert not warnings, warnings
        assert window.grabWindow().save(str(tmp_path / "petct-main.png"))
    finally:
        window.hide()
        delete(engine)
        workspace.shutdown()
        panel.shutdown()


@pytest.mark.parametrize("size", [(1000, 600), (1400, 900)])
def test_fusion_dialog_previews_and_confirmation(qt_app, paired_series, tmp_path, size):
    from dataclasses import replace
    from PySide6.QtQml import QQmlApplicationEngine
    from qt_dicom_viewer.core.series_thumbnail import read_series_thumbnail
    from qt_dicom_viewer.service.thumbnail_service import ThumbnailRequest
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    from test_tag_qml import _App, find, click

    catalog, ct, pet = paired_series
    # The warning and identity checkbox must still gate cross-patient pairing.
    pet = replace(pet, patient_id="OTHER-PATIENT")
    provider = DicomImageProvider()
    panel = PanelController(series_catalog=catalog, image_provider=provider)
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 2, 2, 0, [ct, pet]))
    workspace = WorkspaceController(catalog, provider)
    app = _App(workspace, panel)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("navigation", SvgIconProvider())
    engine.addImageProvider("dicom", provider)
    engine.rootContext().setContextProperty("appController", app)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/Main.qml")))
    window = engine.rootObjects()[0]
    window.resize(*size)
    opened = []
    panel.fusionCreateRequested.connect(lambda *uids: opened.append(uids))
    try:
        panel.selectSeries(ct.series_instance_uid)
        panel.requestFusionView()
        QTest.qWait(50)
        assert panel.fusionCandidates == []
        click(window, find(window, "fusionShowAllPatients"))
        candidate = find(window, "fusionCandidate-" + pet.series_instance_uid)
        click(window, candidate)
        candidate = find(window, "fusionCandidate-" + pet.series_instance_uid)
        confirm = find(window, "confirmFusion")
        assert not confirm.isEnabled()
        identity = find(window, "fusionIdentityConfirmation")
        click(window, identity)
        assert confirm.isEnabled()

        # Deliver actual decoded DICOM thumbnails after selection. Selection,
        # checkbox and delegates survive the asynchronous image refresh.
        for record in (ct, pet):
            path = record.instances[len(record.instances) // 2].path
            image = read_series_thumbnail(path)
            assert not image.isNull()
            panel._accept_thumbnail(ThumbnailRequest(record.series_instance_uid, path), image)
        QTest.qWait(50)
        assert find(window, "fusionCandidate-" + pet.series_instance_uid) is candidate
        assert identity.property("checked")
        assert panel.fusionPartnerUid == pet.series_instance_uid
        for record in (ct, pet):
            preview = find(window, "fusionPreview-" + record.series_instance_uid)
            assert preview.property("source").toString() == panel.fusionThumbnails[record.series_instance_uid]
            assert preview.property("progress") == 1.0
            assert preview.property("paintedWidth") > 0
        assert confirm.property("normalColor") != find(window, "cancelFusion").property("normalColor")
        for name in ("fusionCandidates", "fusionIdentityConfirmation", "cancelFusion", "confirmFusion"):
            item = find(window, name)
            position = item.mapToScene(QPointF(0, 0))
            assert position.x() >= 0 and position.y() >= 0
            assert position.x() + item.width() <= window.width()
            assert position.y() + item.height() <= window.height()
        assert window.grabWindow().save(str(tmp_path / f"fusion-picker-{size[0]}.png"))
        click(window, confirm)
        assert opened == [(ct.series_instance_uid, pet.series_instance_uid)]
        assert not panel.fusionDialogOpen

        panel.requestFusionView()
        QTest.qWait(40)
        click(window, find(window, "fusionShowAllPatients"))
        click(window, find(window, "fusionCandidate-" + pet.series_instance_uid))
        assert not find(window, "fusionIdentityConfirmation").property("checked")
        click(window, find(window, "cancelFusion"))
        assert not panel.fusionDialogOpen and len(opened) == 1
        assert not warnings, warnings
    finally:
        window.hide()
        delete(engine)
        workspace.shutdown()
        panel.shutdown()
