"""Exercise MR through the real QML app and background renderer."""
from pathlib import Path
from PySide6.QtTest import QTest
from qt_dicom_viewer.model import DicomFolderScanSnapshot, WindowLevel
from qt_dicom_viewer.core.mr import automatic_mr_window
from test_pacs_qml import scene
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import find, click, descendants, type_text
from test_mr import write_mr_series


def test_mr_window_buttons_navigation_and_mpr(scene,tmp_path):
    window,app,warnings=scene
    series=write_mr_series(tmp_path/'mr')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path,4,4,0,[series]))
    workspace=app.workspaceController
    wait_until(lambda: workspace.activeViewport is not None and bool(workspace.activeViewport.imageSource))
    view=workspace.activeViewport
    view._tool_controller.activateTool('window')
    QTest.qWait(50)
    assert find(window,'autoWindowButton').isVisible()
    assert find(window,'invertWindowButton').isVisible()
    assert not any(item.objectName()=='beginSaveWindowTemplate' and item.isVisible() for item in descendants(window.contentItem()))
    assert find(window,'openView-3d').isEnabled()
    assert not find(window,'openView-4d').isEnabled()
    assert find(window,'openView-mpr').isEnabled()
    assert 'TE: 80 ms' in view.overlayInfo['mrParameters']
    initial=view.current_window
    view.applyWindowPreset(100,300)
    wait_until(lambda: view.current_window==WindowLevel(100,300))
    click(window,find(window,'autoWindowButton'))
    wait_until(lambda: view.current_window==initial)
    click(window,find(window,'invertWindowButton'))
    wait_until(lambda: view.inverted)
    view.apply_slice_index(2)
    wait_until(lambda: view._frame_meta.slice_index==2)
    assert view.current_window==initial and view.inverted
    shots=tmp_path/'screenshots'; shots.mkdir(exist_ok=True)
    assert window.grabWindow().save(str(shots/'mr-2d.png'))
    click(window,find(window,'openView-mpr'))
    wait_until(lambda: len(workspace.currentTabAllViewports)==3 and all(v.imageSource for v in workspace.currentTabAllViewports),10000)
    views=list(workspace.currentTabAllViewports)
    views[0].applyWindowPreset(.05,.2)
    wait_until(lambda: all(v.current_window==WindowLevel(.05,.2) for v in views))
    views[0].autoWindow()
    wait_until(lambda: all(v.current_window==views[0].current_window for v in views))
    QTest.qWait(100)
    assert window.grabWindow().save(str(shots/'mr-mpr.png'))
    assert not warnings,warnings


def test_mr_mixed_echo_mpr_opens_error_tab_with_reason(scene,tmp_path):
    window,app,warnings=scene
    series=write_mr_series(tmp_path/'echo',change=lambda ds,i:setattr(ds,'EchoTime',80+i*10))
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path,4,4,0,[series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None and bool(app.workspaceController.activeViewport.imageSource))
    assert find(window,'openView-mpr').isEnabled()
    click(window, find(window, 'openView-mpr'))
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'error')
    assert app.workspaceController.activeLoadState.errorMessage
    assert not app.exportController.canExportPng
    assert app.panelController.seriesViewError(series.series_instance_uid,'mpr')
    assert find(window,'openView-montage').isEnabled()
    assert not warnings,warnings



def test_mr_montage_auto_window_small_values_and_reset(scene,tmp_path):
    window,app,warnings=scene
    series=write_mr_series(tmp_path/'montage',change=lambda ds,i:setattr(ds,'RescaleSlope',.0001))
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path,4,4,0,[series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None and bool(app.workspaceController.activeViewport.imageSource))
    click(window,find(window,'openView-montage'))
    wait_until(lambda:app.workspaceController.activeTabType=='montage' and app.workspaceController.activeViewport.hasWindow)
    view=app.workspaceController.activeViewport
    view._tool_controller.activateTool('window')
    QTest.qWait(50)
    initial=view.viewport_state.window
    assert 0<initial.width<1
    type_text(window,find(window,'windowCenterInput'),'0.123')
    type_text(window,find(window,'windowWidthInput'),'0.456')
    click(window,find(window,'applyWindowValues'))
    wait_until(lambda:view.viewport_state.window==WindowLevel(.123,.456))
    click(window,find(window,'invertWindowButton'))
    assert view.inverted
    click(window,find(window,'autoWindowButton'))
    wait_until(lambda:view.viewport_state.window==initial)
    assert view.inverted
    from qt_dicom_viewer.model import ToolType
    view.reset_tool_state(ToolType.WINDOW)
    assert view.viewport_state.window==initial and not view.inverted
    assert 'TE: 80 ms' in view.scanParameters
    shots=tmp_path/'screenshots'; shots.mkdir(exist_ok=True)
    QTest.qWait(100)
    assert window.grabWindow().save(str(shots/'mr-montage.png'))
    assert not warnings,warnings



def test_mr_series_update_refreshes_mpr_eligibility(scene,tmp_path):
    from dataclasses import replace
    window,app,warnings=scene
    series=write_mr_series(tmp_path/'updated')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path,4,4,0,[series]))
    wait_until(lambda:app.workspaceController.activeViewport is not None and bool(app.workspaceController.activeViewport.imageSource))
    assert find(window,'openView-mpr').isEnabled()
    other=replace(series.instances[1], mr_parameters=replace(series.instances[1].mr_parameters,echo_time=120))
    updated=replace(series,instances=(series.instances[0],other,*series.instances[2:]))
    app.panelController._update_series_record(DicomFolderScanSnapshot(tmp_path,4,4,0,[updated]))
    wait_until(lambda:bool(find(window,'openView-mpr').parentItem().property('viewError')))
    assert find(window,'openView-mpr').isEnabled()
    assert not warnings,warnings


def test_shared_panels_tolerate_controller_properties_during_teardown(qt_app):
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickView
    from shiboken6 import delete
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    qml = Path(__file__).resolve().parents[1] / 'src/qt_dicom_viewer/qml'
    for file, properties in [
        ('sections/right/ToolResetBar.qml', {'toolController': None, 'voiController': {}}),
        ('sections/center/viewportArea/MprReferenceViewport.qml', {'controller': {}}),
    ]:
        view = QQuickView()
        warnings = []
        view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        view.engine().addImageProvider('navigation', SvgIconProvider())
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.resize(320, 200)
        view.setInitialProperties(properties)
        try:
            view.setSource(QUrl.fromLocalFile(str(qml/file)))
            assert view.status() == QQuickView.Ready
            view.show()
            QTest.qWait(60)
            assert not warnings, warnings
        finally:
            view.hide()
            delete(view)



def test_compare_alt_click_cross_plane_and_reference_line(scene, tmp_path):
    from PySide6.QtCore import QPointF, Qt
    from pydicom.uid import generate_uid
    window, app, warnings = scene
    study, frame = generate_uid(), generate_uid()
    def geometry(sagittal):
        def change(ds, index):
            ds.StudyInstanceUID, ds.FrameOfReferenceUID = study, frame
            ds.ImageOrientationPatient = [0,1,0,0,0,1] if sagittal else [1,0,0,0,1,0]
            ds.ImagePositionPatient = [index*.8,0,0] if sagittal else [0,0,index*.8]
        return change
    axial = write_mr_series(tmp_path/'axial', 8, change=geometry(False))
    sagittal = write_mr_series(tmp_path/'sagittal', 8, change=geometry(True))
    snapshot = DicomFolderScanSnapshot(tmp_path,16,16,0,[axial,sagittal])
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    ws = app.workspaceController
    ws.createMultiCompareTab([axial.series_instance_uid, sagittal.series_instance_uid])
    tab = ws.activeTab
    a, b = list(tab.viewports_by_id.values())
    wait_until(lambda: all(v.loadState=='ready' for v in (a,b)))
    a.setSliceIndex(3)
    wait_until(lambda:a._frame_meta.slice_index==3)
    assert b.sliceIndex == 4  # Scrolling must not link perpendicular stacks.
    cell = find(window, 'imageViewport-'+a.viewportId)
    layer = next(i for i in descendants(cell) if i.objectName()=='dicomPixelLayer')
    def alt_click(column, row):
        QTest.mouseClick(window, Qt.LeftButton, Qt.AltModifier,
                         layer.mapToScene(QPointF(column+.5,row+.5)).toPoint())
    initial = a.current_window
    alt_click(2,5)
    wait_until(lambda:b._frame_meta.slice_index==2)
    assert a.current_window == initial
    assert tab.activeViewport is a
    assert b.referenceLines and abs(b.referenceLines[0]['y1']-3)<1e-6
    canvas = next(i for i in descendants(find(window,'imageViewport-'+b.viewportId))
                  if i.objectName()=='compareReferenceLines')
    assert canvas.isVisible() and canvas.property('lines')
    # Use the rendered pixel layer after display transformations as well.
    a.applyTransformAction("rotate:cw90"); a.applyTransformAction("rotate:mirror-h")
    QTest.qWait(100)
    alt_click(5,4)
    wait_until(lambda:b._frame_meta.slice_index==5)
    assert not warnings, warnings



def test_accessible_mr_series_selection_matches_controller_and_opens_image(scene,tmp_path):
    from PySide6.QtGui import QAccessible, QAccessibleActionInterface
    window, app, warnings = scene
    series = write_mr_series(tmp_path/'accessible')
    snapshot = DicomFolderScanSnapshot(tmp_path,4,4,0,[series])
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    QTest.qWait(50)
    uid = series.series_instance_uid
    checkbox = find(window,'selectSeries-'+uid)
    interface = QAccessible.queryAccessibleInterface(checkbox)
    assert 'TE=80' in interface.text(QAccessible.Name)
    toggle = interface.actionInterface()
    toggle.doAction(QAccessibleActionInterface.toggleAction())
    assert checkbox.property('checked')
    assert app.panelController.selectedSeriesUids == [uid]
    assert find(window,'openView-2d').isEnabled()
    toggle.doAction(QAccessibleActionInterface.toggleAction())
    assert not checkbox.property('checked')
    assert app.panelController.selectedSeriesUids == []
    row = find(window,'series-'+uid)
    accessible = QAccessible.queryAccessibleInterface(row)
    assert accessible.role() == QAccessible.Button
    assert series.series_description in accessible.text(QAccessible.Name)
    accessible.actionInterface().doAction(QAccessibleActionInterface.pressAction())
    wait_until(lambda:app.workspaceController.activeViewport is not None
               and app.workspaceController.activeViewport.loadState=='ready')
    assert app.workspaceController.activeTabType == '2d'
    assert not warnings,warnings


def test_mr_initial_middle_slice_slider_matches_display_across_tabs(scene, tmp_path):
    window, app, warnings = scene
    for number in range(3):
        series = write_mr_series(tmp_path / str(number))
        app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
        view = app.workspaceController.activeViewport
        wait_until(lambda: view._frame_meta is not None)
        # Pixel decoding may finish before the asynchronous workspace page.
        # Wait for this tab's real slider instead of assuming 60 ms is enough.
        wait_until(lambda: any(item.isVisible() and item.objectName() == 'sliceControl'
                               and item.parentItem().property('viewportController') == view
                               for item in descendants(window.contentItem())))
        sliders = [item for item in descendants(window.contentItem())
                   if item.isVisible() and item.inherits('QQuickSlider')]
        assert len(sliders) == 1
        assert view.sliceIndex == 2
        assert sliders[0].property('value') == view.sliceIndex + 1
        assert sliders[0].property('from') == 1
        assert sliders[0].property('to') == view.sliceCount
    assert not warnings, warnings


def test_slice_slider_tracks_late_range_without_index_change(scene, tmp_path):
    from PySide6.QtCore import QObject, Property, Signal
    window, app, warnings = scene
    series = write_mr_series(tmp_path / 'late-range')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and bool(app.workspaceController.activeViewport.imageSource))
    wait_until(lambda: any(item.isVisible() and item.inherits('QQuickSlider')
                           for item in descendants(window.contentItem())))
    slider = next(item for item in descendants(window.contentItem())
                  if item.isVisible() and item.inherits('QQuickSlider'))
    slider_root = slider.parentItem()
    class DelayedRange(QObject):
        indexChanged = Signal()
        countChanged = Signal()
        count = 0
        @Property(str, constant=True)
        def viewportType(self): return 'stack'
        @Property(int, notify=indexChanged)
        def sliceIndex(self): return 16
        @Property(int, notify=countChanged)
        def sliceCount(self): return self.count
    view = DelayedRange(window)
    original = app.workspaceController.activeViewport
    slider_root.setProperty('viewportController', view)
    try:
        assert slider.property('value') == 1
        view.count = 32
        view.countChanged.emit()
        assert slider.property('value') == 17
    finally:
        slider_root.setProperty('viewportController', original)
    assert not warnings, warnings


def test_accessible_checkable_actions_update_mpr_layout_and_compare_state(scene, tmp_path):
    from PySide6.QtGui import QAccessible, QAccessibleActionInterface
    window, app, warnings = scene
    series = write_mr_series(tmp_path / 'accessible-controls')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and bool(app.workspaceController.activeViewport.imageSource))
    click(window, find(window, 'openView-mpr'))
    wait_until(lambda: len(app.workspaceController.currentTabAllViewports) == 3
               and all(v.imageSource for v in app.workspaceController.currentTabAllViewports))
    click(window, find(window, 'primaryTool-mpr-layout'))
    choice = find(window, 'mprLayout-columns')
    QAccessible.queryAccessibleInterface(choice).actionInterface().doAction(QAccessibleActionInterface.toggleAction())
    wait_until(lambda: not find(window, 'mprLayout-right').property('checked'))
    assert choice.property('checked')
    click(window, find(window, 'primaryTool-viewport-settings'))
    checkbox = find(window, 'viewportSetting-scale-bar')
    view = app.workspaceController.activeViewport
    QAccessible.queryAccessibleInterface(checkbox).actionInterface().doAction(QAccessibleActionInterface.toggleAction())
    assert not checkbox.property('checked')
    assert not view.viewport_state.display_settings.show_scale_bar
    assert not warnings, warnings


def test_accessible_slice_number_and_keyboard_jump(scene, tmp_path):
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QAccessible, QAccessibleActionInterface
    window, app, warnings = scene
    series = write_mr_series(tmp_path / 'slice-jump')
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and app.workspaceController.activeViewport.loadState == 'ready')
    view = app.workspaceController.activeViewport
    slider = find(window, 'sliceControl')
    accessible = QAccessible.queryAccessibleInterface(slider)
    assert accessible.text(QAccessible.Name)
    assert accessible.valueInterface().currentValue() == view.sliceIndex + 1
    assert accessible.valueInterface().minimumValue() == 1
    assert accessible.valueInterface().maximumValue() == view.sliceCount
    jump = QAccessible.queryAccessibleInterface(find(window, 'sliceJumpButton'))
    jump.actionInterface().doAction(QAccessibleActionInterface.pressAction())
    field = find(window, 'sliceNumberInput')
    type_text(window, field, '0')
    assert not find(window, 'sliceJumpApply').isEnabled()
    type_text(window, field, '4')
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: view._frame_meta.slice_index == 3)
    assert accessible.valueInterface().currentValue() == 4
    accessible.actionInterface().doAction(QAccessibleActionInterface.decreaseAction())
    wait_until(lambda: view._frame_meta.slice_index == 2)
    assert accessible.valueInterface().currentValue() == 3
    accessible.valueInterface().setCurrentValue(2)
    wait_until(lambda: view._frame_meta.slice_index == 1)
    slider.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Up)
    wait_until(lambda: view._frame_meta.slice_index == 0)
    assert accessible.valueInterface().currentValue() == 1
    # Visual top remains the first slice despite the normal accessible range.
    a = slider.mapToScene(QPointF(slider.width()/2, 1))
    b = slider.mapToScene(QPointF(slider.width()/2, slider.height()-1))
    top, bottom = sorted((a, b), key=lambda point: point.y())
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, bottom.toPoint())
    wait_until(lambda: view._frame_meta.slice_index == 3)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, top.toPoint())
    wait_until(lambda: view._frame_meta.slice_index == 0)
    assert not warnings, warnings
