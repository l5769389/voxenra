"""Exercise compact 3D tools through QML without creating a GPU surface."""
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPointF, QUrl, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QKeyEvent, QGuiApplication
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from test_measurement_qml import qt_app, _visual_children
from test_pet_fusion import paired_series
from test_mr import write_mr_series


@pytest.fixture(params=['CT', 'MR', 'PT'])
def scene(qt_app, paired_series, request, tmp_path):
    catalog, ct, pet = paired_series
    series = ct if request.param == 'CT' else pet
    if request.param == 'MR':
        series = write_mr_series(tmp_path / 'mr')
        catalog.update(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    owner = QObject()
    owner._settings_controller = SettingsController(owner, path=False)
    workspace = WorkspaceController(catalog, DicomImageProvider(), owner)
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(workspace.handleRenderResult)
    workspace.renderRequested.connect(worker.handleRenderRequest)
    workspace.createTab(series.series_instance_uid, 'MPR', 'mpr')
    tab = workspace.activeTab
    tab.mprLayout.setLayout('quad')
    tab.mprLayout.activate()
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setPosition(600, 40)
    view.resize(52, 900)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties(dict(toolController=tab.activeToolController,
        viewportController=tab.activeViewport, tabController=tab, toolVisible=True, collapsed=True))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/RightPanel.qml')))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(60)
    try:
        yield view, tab, request.param, warnings
    finally:
        view.hide()
        delete(view)
        workspace.shutdown()


def popup(view):
    return view.rootObject().findChild(QObject, 'compactVolumePanel')


def find(view, name):
    from toolbar_navigation import reveal_primary_tool
    reveal_primary_tool(view.rootObject(), name)
    roots = [view.rootObject(), popup(view).property('contentItem')]
    return next(item for root in roots for item in _visual_children(root)
                if item.objectName() == name and item.isVisible())


def item_window(item):
    # QQuickPopupWindow can expose a stale PySide wrapper through item.window().
    # Resolve its current public QQuickWindow by the content-item tree instead.
    root = item
    while root.parentItem() is not None:
        root = root.parentItem()
    return next(w for w in QGuiApplication.allWindows() if w.contentItem() == root)


def click(view, name):
    item = find(view, name)
    parent = item.parentItem()
    while parent is not None:
        offset = parent.property('contentY')
        if offset is not None:
            y = item.mapToItem(parent, QPointF()).y()
            if y < 0 or y + item.height() > parent.height():
                parent.setProperty('contentY', max(0, min(
                    parent.property('contentHeight') - parent.height(),
                    offset + y - (parent.height() - item.height()) / 2)))
                QTest.qWait(20)
        parent = parent.parentItem()
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    QTest.mouseClick(item_window(item), Qt.LeftButton, pos=point)
    QTest.qWait(35)


def test_compact_presets_directions_and_reset_are_scoped_to_volume(scene):
    view, tab, modality, warnings = scene
    volume = tab.mprLayout.volumeViewport
    tab.mprLayout.setLinkRotation(False)
    original = tab._target_mpr_state
    slice_windows = [(v.windowCenter, v.windowWidth) for v in tab.viewports_by_id.values()]
    assert find(view, 'volumeToolContext').property('text') == '3D'
    click(view, 'compactTool-volume-preset')
    assert popup(view).property('opened')
    assert popup(view).property('width') == 280
    assert item_window(find(view, 'compactVolumePanelClose')).width() == 280
    if modality == 'PT':
        assert find(view, 'standalonePetVolumePanel')
        assert find(view, 'pet3dOpacity')
        volume.setPetOpacity(.4)
    else:
        preset = 'mr-bright' if modality == 'MR' else 'bone'
        click(view, 'volumePreset-' + preset)
        assert volume.currentPresetId == preset
        names = [p['presetId'] for p in volume.volumePresets]
        assert ('bone' in names) == (modality == 'CT')
        if modality == 'CT':
            assert len(names) == 20
            for choice in ('cardiac', 'hardware', names[-1]):
                click(view, 'volumePreset-' + choice)
                assert volume.currentPresetId == choice
    # Escape works even though this is a separate popup window above VTK.
    # Escape destroys Qt's transient popup window on key press.
    QCoreApplication.sendEvent(item_window(find(view, 'compactVolumePanelClose')),
                               QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    QTest.keyRelease(view, Qt.Key_Escape)
    QTest.qWait(30)
    assert not popup(view).property('visible')
    click(view, 'compactTool-volume-direction')
    for face in 'APLRSI':
        click(view, 'compactAction-' + face)
        assert volume.currentFace == face
        assert find(view, 'compactAction-' + face).property('checked')
    volume.setZoom(2)
    camera, display = volume.state, volume.display_state
    # Selecting a slice and returning must retain 3D appearance and camera.
    tab.activateViewport(next(iter(tab.viewports_by_id)))
    tab.mprLayout.activate()
    assert volume.state == camera and volume.display_state == display
    assert tab._target_mpr_state == original
    assert [(v.windowCenter, v.windowWidth) for v in tab.viewports_by_id.values()] == slice_windows
    click(view, 'compactToolReset')
    assert volume.zoom == 1 and volume.currentFace == 'A'
    assert tab._target_mpr_state == original
    assert [(v.windowCenter, v.windowWidth) for v in tab.viewports_by_id.values()] == slice_windows
    assert not warnings, warnings


def test_compact_reference_settings_and_context_change_close_popup(scene):
    view, tab, modality, warnings = scene
    click(view, 'compactTool-mpr-layout')
    assert popup(view).property('opened')
    assert popup(view).property('width') == 280
    assert item_window(find(view, 'compactVolumePanelClose')).width() == 280
    assert find(view, 'mprLayout-quad').property('checked')
    assert not any(item.objectName() == 'mprLinkRotation' and item.isVisible()
                   for item in _visual_children(popup(view).property('contentItem')))
    click(view, 'compactVolumePanelClose')
    click(view, 'compactTool-viewport-settings')
    assert find(view, 'mprReferenceMode')
    assert tab.mprLayout.linkRotation
    assert find(view, 'mprLinkRotation').property('checked')
    click(view, 'mprLinkRotation')
    assert not tab.mprLayout.linkRotation
    view.rootObject().setProperty('collapsed', False)
    view.resize(280, 900)
    QTest.qWait(40)
    assert not find(view, 'mprLinkRotation').property('checked')
    click(view, 'mprLinkRotation')
    assert tab.mprLayout.linkRotation
    view.rootObject().setProperty('collapsed', True)
    view.resize(52, 900)
    QTest.qWait(40)
    assert tab.activeToolController.activeTool == 'viewport-settings'
    click(view, 'compactTool-viewport-settings')
    # A real context change closes the stale popup, and leaves slice tools active.
    tab.activateViewport(next(iter(tab.viewports_by_id)))
    view.rootObject().setProperty('toolController', tab.activeToolController)
    view.rootObject().setProperty('viewportController', tab.activeViewport)
    QTest.qWait(40)
    assert not popup(view).property('visible')
    assert not any(item.objectName() == 'volumeToolContext' and item.isVisible()
                   for item in _visual_children(view.rootObject()))
    click(view, 'compactTool-viewport-settings')
    assert find(view, 'mprLinkRotation').property('checked')
    click(view, 'mprLinkRotation')
    assert not tab.mprLayout.linkRotation
    assert find(view, 'viewportSetting-scale-bar')
    assert not warnings, warnings


def test_quad_slice_window_link_keeps_volume_template_independent(scene):
    view, tab, modality, warnings = scene
    if modality == 'PT':
        pytest.skip('PET intensity controls use the shared PET display controller')
    volume = tab.mprLayout.volumeViewport
    volume.applyVolumePreset('mr-bright' if modality == 'MR' else 'bone')
    display = volume.display_state
    for source in tab.viewports_by_id.values():
        source.applyWindowPreset(41.5, 250.5)
        assert all(v.windowCenter == 41.5 and v.windowWidth == 250.5
                   for v in tab.viewports_by_id.values())
        assert volume.display_state == display
    volume.applyWindowPreset(100, 500)
    assert all(v.windowCenter == 41.5 and v.windowWidth == 250.5
               for v in tab.viewports_by_id.values())
    assert not warnings, warnings


def test_compact_layout_available_for_every_mpr_slice(scene):
    view, tab, _modality, warnings = scene
    for viewport_id in tab.viewports_by_id:
        tab.activateViewport(viewport_id)
        view.rootObject().setProperty('toolController', tab.activeToolController)
        view.rootObject().setProperty('viewportController', tab.activeViewport)
        QTest.qWait(40)
        click(view, 'compactTool-mpr-layout')
        assert popup(view).property('opened')
        assert find(view, 'mprLayout-quad').property('checked')
        click(view, 'mprLayout-columns')
        assert tab.mprLayout.layout == 'columns'
        click(view, 'mprLayout-quad')
        assert tab.mprLayout.layout == 'quad'
        # Collapsing an expanded layout panel must retain the layout selection.
        view.rootObject().setProperty('collapsed', False)
        view.rootObject().setProperty('collapsed', True)
        QTest.qWait(30)
        assert tab.activeToolController.activeTool == 'mpr-layout'
        assert find(view, 'compactTool-mpr-layout').property('checked')
    assert not warnings, warnings


def test_remember_layout_checkbox_works_in_compact_and_expanded_panel(scene):
    view, tab, modality, warnings = scene
    layout = tab.mprLayout
    click(view, 'compactTool-mpr-layout')
    checkbox = find(view, 'mprRememberLayout')
    assert not checkbox.property('checked')
    click(view, 'mprRememberLayout')
    assert layout.rememberLayout
    assert layout._settings.section('layout')['rememberedMprLayout'] == 'quad'
    view.rootObject().setProperty('collapsed', False)
    view.resize(280, 900)
    QTest.qWait(40)
    assert find(view, 'mprRememberLayout').property('checked')
    click(view, 'mprRememberLayout')
    assert not layout.rememberLayout and layout.layout == 'quad'
    click(view, 'mprRememberLayout')
    click(view, 'mprLayout-columns')
    assert layout.layout == 'columns'
    assert layout._settings.section('layout')['rememberedMprLayout'] == 'columns'
    assert not warnings, warnings


def test_compact_flyout_trigger_toggles_and_switches(scene, tmp_path):
    view, tab, modality, warnings = scene
    for tool in ('mpr-layout', 'viewport-settings', 'volume-preset'):
        click(view, 'compactTool-' + tool)
        assert popup(view).property('visible')
        assert find(view, 'toolFlyoutHeader').height() == 24
        assert item_window(find(view, 'compactVolumePanelClose')).grabWindow().save(
            str(tmp_path / (tool + '.png')))
        # Test press/release separately: dismissal on press used to cause reopen.
        for _ in range(3):
            trigger = find(view, 'compactTool-' + tool)
            point = trigger.mapToScene(QPointF(trigger.width()/2, trigger.height()/2)).toPoint()
            QTest.mousePress(view, Qt.LeftButton, pos=point)
            # Native popup may already be dismissed; release must not reopen it.
            QTest.qWait(120)
            QTest.mouseRelease(view, Qt.LeftButton, pos=point)
            QTest.qWait(50)
            assert not popup(view).property('visible')
            click(view, 'compactTool-' + tool)
            assert popup(view).property('visible')
        click(view, 'compactVolumePanelClose')
    click(view, 'compactTool-mpr-layout')
    click(view, 'compactTool-viewport-settings')
    assert popup(view).property('visible')
    assert popup(view).property('panelTool') == 'viewport-settings'
    assert find(view, 'mprLinkRotation')
    click(view, 'compactTool-pan')
    assert not popup(view).property('visible')
    assert not warnings, warnings
