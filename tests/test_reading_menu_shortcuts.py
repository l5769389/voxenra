"""Exercise scoped shortcuts through real keys, controls, focus changes and image state."""
import os
import pytest
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_input_settings_qml import reading_scene, visible_viewport
from test_pet_fusion import paired_series
from test_series_sidebar import sidebar_scene
from test_tag_qml import click, find, descendants, type_text


def label(button):
    return next(i for i in descendants(button) if i.objectName() == 'toolActionLabel').property('text')


def test_rotation_keys_follow_menu_remap_and_reset(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    view = tab.activeViewport
    app.settingsController.setValue('appearance', 'toolLabels', True)
    app.settingsController.setValue('layout', 'rightPanelWidth', 420)
    click(window, find(window, 'primaryTool-rotate'))
    for action, key in [('mirror-h', 'H'), ('mirror-v', 'V'), ('cw90', 'K'), ('ccw90', 'J')]:
        assert label(find(window, 'rotateAction-rotate:' + action)).endswith('(' + key + ')')
    QTest.keyClick(window, Qt.Key_K)
    assert view.rotationDegrees == 90
    QTest.keyClick(window, Qt.Key_J)
    assert view.rotationDegrees == 0
    QTest.keyClick(window, Qt.Key_H)
    QTest.keyClick(window, Qt.Key_V)
    assert view.viewport_state.horizontal_flip and view.viewport_state.vertical_flip
    QTest.keyClick(window, Qt.Key_R)
    assert not view.viewport_state.horizontal_flip and not view.viewport_state.vertical_flip
    assert app.shortcutController.assign('rotate:cw90', 'F7')
    assert not app.shortcutController.assign('rotate:cw90', 'R')
    QTest.keyClick(window, Qt.Key_K)
    assert view.rotationDegrees == 0
    QTest.keyClick(window, Qt.Key_F7)
    assert view.rotationDegrees == 90
    search = find(window, 'sidebarPatientSearch')
    click(window, search)
    QTest.keyClick(window, Qt.Key_H)
    assert search.property('text').lower() == 'h'
    assert not view.viewport_state.horizontal_flip
    search.setProperty('text', '')
    visible_viewport(window).forceActiveFocus()
    app.feedbackController.show()
    wait_until(lambda: window.property('shortcutPopupOpen'))
    QTest.keyClick(window, Qt.Key_F7)
    QTest.keyClick(window, Qt.Key_H)
    assert view.rotationDegrees == 90 and not view.viewport_state.horizontal_flip
    QTest.keyClick(window, Qt.Key_Escape)
    wait_until(lambda: not window.property('shortcutPopupOpen'))
    click(window, find(window, 'primaryTool-window'))
    field = find(window, 'windowWidthInput')
    field.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_F7)
    assert view.rotationDegrees == 90
    assert not app.shortcutController.activate('rotate:cw90', tab.toolController, tab, 'window')
    click(window, find(window, 'toggleRightPanel'))
    click(window, find(window, 'compactTool-rotate'))
    child = find(window, 'compactAction-rotate:cw90')
    assert child.parentItem().property('tooltipText').endswith('(F7)')
    QTest.keyClick(window, Qt.Key_F7)
    assert view.rotationDegrees == 180
    click(window, find(window, 'compactTool-rotate'))
    QTest.keyClick(window, Qt.Key_F7)
    assert view.rotationDegrees == 180
    assert not sidebar_scene[3], sidebar_scene[3]


def test_view_reset_follows_the_visible_tool_and_shared_remap(sidebar_scene, tmp_path):
    window, app, tab = reading_scene(sidebar_scene)
    vp = tab.activeViewport
    shortcuts = app.shortcutController
    baseline = (vp.windowCenter, vp.windowWidth)
    vp.applyWindowPreset(123, 321)
    vp.setZoom(2)
    vp.applyTransformAction('rotate:cw90')
    reset = find(window, 'activeToolReset')
    assert find(window, 'toolResetBar').isAncestorOf(reset)
    assert reset.property('tooltipText').endswith('(R)')
    QTest.keyClick(window, Qt.Key_R)
    assert (vp.windowCenter, vp.windowWidth) == baseline
    assert (vp.zoom, vp.rotationDegrees) == (2, 90)
    assert tuple(float(find(window, name).property('text'))
                 for name in ('windowCenterInput', 'windowWidthInput')) == baseline
    assert label(reset).endswith('(R)')
    assert [item for item in descendants(window.contentItem())
            if item.objectName() == 'activeToolReset' and item.isVisible()] == [reset]
    assert window.grabWindow().save(str(tmp_path / 'window-reset.png'))

    # One assignment changes all reset buttons and releases the old key immediately.
    from test_settings_redesign import reveal_setting
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('input')
    record = find(window, 'shortcutRecord-view-reset')
    reveal_setting(window, record)
    click(window, record)
    QTest.keyClick(window, Qt.Key_F8)
    assert shortcuts.hint('view-reset') == 'F8' and not shortcuts.recordingAction
    click(window, find(window, 'workspaceTab-' + tab.tab_config.tab_id))
    vp.applyWindowPreset(123, 321)
    reset = find(window, 'activeToolReset')
    assert label(reset).endswith('(F8)')
    QTest.keyClick(window, Qt.Key_R)
    assert (vp.windowCenter, vp.windowWidth) == (123, 321)
    click(window, reset)
    assert (vp.windowCenter, vp.windowWidth) == baseline and vp.zoom == 2
    # A draft must also clear when the committed window is already at baseline.
    width_input = find(window, 'windowWidthInput')
    type_text(window, width_input, '999')
    click(window, reset)
    assert float(width_input.property('text')) == baseline[1]
    for tool in ('zoom', 'rotate'):
        click(window, find(window, 'primaryTool-' + tool))
        assert label(find(window, 'activeToolReset')).endswith('(F8)')
        QTest.keyClick(window, Qt.Key_R)
        assert vp.rotationDegrees == 90
        if tool == 'zoom':
            assert vp.zoom == 2
        QTest.keyClick(window, Qt.Key_F8)
        assert vp.zoom == 1 and vp.rotationDegrees == (90 if tool == 'zoom' else 0)

    click(window, find(window, 'primaryTool-scroll'))
    current = vp.sliceIndex
    prev, nxt = (find(window, 'scrollShortcut-' + a) for a in ('prev', 'next'))
    assert not prev.isEnabled() and prev.property('text').endswith('(J)')
    assert nxt.isEnabled() and nxt.property('text').endswith('(K)')
    for key, index in ((Qt.Key_K, 1), (Qt.Key_K, 2), (Qt.Key_K, 2), (Qt.Key_J, 1), (Qt.Key_F8, current)):
        QTest.keyClick(window, key)
        assert vp.sliceIndex == index
        assert prev.isEnabled() == (index > 0)
        assert nxt.isEnabled() == (index < vp.sliceCount - 1)
    # The pair also appears as clickable actions, and remains independent of CPR remaps.
    click(window, nxt)
    assert vp.sliceIndex == 1
    assert not shortcuts.assign('scroll-next', 'F8')
    assert shortcuts.assign('scroll-next', 'F7')
    nxt = find(window, 'scrollShortcut-next')
    assert nxt.property('text').endswith('(F7)')
    QTest.keyClick(window, Qt.Key_K)
    assert vp.sliceIndex == 1
    QTest.keyClick(window, Qt.Key_F7)
    assert vp.sliceIndex == 2 and shortcuts.hint('cpr-next') == 'K'
    click(window, find(window, 'primaryTool-pan'))
    QTest.keyClick(window, Qt.Key_J)
    QTest.keyClick(window, Qt.Key_F8)
    assert vp.sliceIndex == 2
    vp.apply_pan(25, 12)
    assert label(find(window, 'activeToolReset')).endswith('(F8)')
    QTest.keyClick(window, Qt.Key_F8)
    assert (vp.panX, vp.panY) == (0, 0)
    assert vp.sliceIndex == 2
    assert not sidebar_scene[3], sidebar_scene[3]


def test_measure_keys_remap_focus_and_visibility(sidebar_scene, tmp_path):
    window, app, tab = reading_scene(sidebar_scene)
    tools = tab.toolController
    click(window, find(window, 'primaryTool-measure'))
    for letter, tool in [('A', 'angle'), ('R', 'rect'), ('E', 'ellipse'),
                         ('V', 'curve'), ('F', 'freehand'), ('L', 'length')]:
        QTest.keyClick(window, getattr(Qt, 'Key_' + letter))
        button = find(window, 'measureEntry-' + tool)
        assert button.property('checked') and tools.activeInteraction == 'measure:' + tool
        assert label(button).endswith('(' + letter + ')')
    assert not any(item.objectName() == 'activeToolReset' and item.isVisible()
                   for item in descendants(window.contentItem()))
    assert window.grabWindow().save(str(tmp_path / 'measure-bindings.png'))
    assert app.shortcutController.assign('measure:ellipse', 'P')  # shadows general Pan only here
    QTest.keyClick(window, Qt.Key_E)
    assert tools.activePanel == 'export'  # The released E now opens general Export.
    QTest.keyClick(window, Qt.Key_M)
    QTest.keyClick(window, Qt.Key_P)
    assert tools.activeInteraction == 'measure:ellipse'
    search = find(window, 'sidebarPatientSearch')
    click(window, search)
    QTest.keyClick(window, Qt.Key_A)
    assert search.property('text').lower() == 'a' and tools.activeInteraction == 'measure:ellipse'
    search.setProperty('text', '')
    image = visible_viewport(window)
    image.forceActiveFocus()
    app.feedbackController.show()
    wait_until(lambda: window.property('shortcutPopupOpen'))
    QTest.keyClick(window, Qt.Key_L)
    assert tools.activeInteraction == 'measure:ellipse'
    QTest.keyClick(window, Qt.Key_Escape)
    wait_until(lambda: not window.property('shortcutPopupOpen'))
    pos = image.mapToScene(QPointF(image.width()/2, image.height()/2)).toPoint()
    QTest.mousePress(window, Qt.RightButton, Qt.NoModifier, pos)
    QTest.keyClick(window, Qt.Key_A)
    QTest.mouseRelease(window, Qt.RightButton, Qt.NoModifier, pos)
    assert tools.activeInteraction == 'measure:ellipse'
    QTest.keyClick(window, Qt.Key_F12)
    assert window.property('maximizedReadingArea') and not window.property('activeReadingMenu')
    QTest.keyClick(window, Qt.Key_A)
    assert tools.activeInteraction == 'annotate:arrow'  # The hidden measure menu releases A.
    QTest.keyClick(window, Qt.Key_P)
    assert tools.activeInteraction == 'pan'
    for key in (Qt.Key_V, Qt.Key_F, Qt.Key_R):
        QTest.keyClick(window, key)
        assert tools.activeInteraction == 'pan'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_compact_groups_own_keys_only_while_expanded(sidebar_scene, tmp_path):
    from test_sidebar_style_polish import reveal
    window, app, tab = reading_scene(sidebar_scene)
    click(window, find(window, 'toggleRightPanel'))
    rail = find(window, 'compactToolRail')
    def group(name):
        reveal(window, rail, find(window, 'compactTool-' + name))
    group('measure')
    QTest.keyClick(window, Qt.Key_A)
    assert tab.activeViewport.activeInteraction == 'measure:angle'
    assert find(window, 'compactAction-measure:angle').property('checked')
    for key, action in ((Qt.Key_R, 'rect'), (Qt.Key_V, 'curve'), (Qt.Key_F, 'freehand')):
        QTest.keyClick(window, key)
        assert tab.activeViewport.activeInteraction == 'measure:' + action
        assert find(window, 'compactAction-measure:' + action).property('checked')
    assert window.grabWindow().save(str(tmp_path / 'compact-bindings.png'))
    group('measure')
    assert not window.property('activeReadingMenu')
    QTest.keyClick(window, Qt.Key_V)
    assert tab.activeViewport.activeInteraction == 'measure:freehand'
    group('rotate')
    view = tab.activeViewport
    view.setZoom(2)
    reveal(window, rail, find(window, 'compactAction-rotate:cw90'))
    assert view.rotationDegrees == 90
    QTest.keyClick(window, Qt.Key_R)
    assert (view.rotationDegrees, view.zoom) == (0, 2)
    view.applyTransformAction('rotate:cw90')
    group('rotate')
    QTest.keyClick(window, Qt.Key_R)
    assert (view.rotationDegrees, view.zoom) == (90, 2)
    group('zoom')  # Direct compact tool with no submenu: R must not reset the zoom.
    QTest.keyClick(window, Qt.Key_R)
    assert not window.property('activeReadingMenu') and view.zoom == 2
    assert not sidebar_scene[3], sidebar_scene[3]


def test_cpr_reference_reset_and_curved_measure_guard(sidebar_scene):
    from test_cpr_controller import draw
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CPR', 'cpr')
    tab = ws.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((35, 48), (65, 48)))
    path_id = tab.selectedPathId
    window.requestActivate()
    click(window, find(window, 'primaryTool-zoom'))
    vp = tab.activeViewport
    vp.setZoom(2)
    QTest.keyClick(window, Qt.Key_R)
    assert vp.zoom == 1 and not tab.pathEditing and tab.selectedPathId == path_id
    click(window, find(window, 'primaryTool-cpr-path'))
    tab.setReferenceBrowsing(False)
    find(window, 'cprViewport-curved')
    assert tab.activeViewport.viewportRole == 'curved'
    click(window, find(window, 'primaryTool-measure'))
    disabled = find(window, 'measureEntry-angle')
    assert not disabled.isEnabled()
    QTest.keyClick(window, Qt.Key_A)
    assert tab.toolController.activeInteraction != 'measure:angle'
    assert not warnings, warnings


def test_detached_window_and_tab_only_reset_their_own_tool(sidebar_scene):
    from test_tab_windows import detached
    window, app, first = reading_scene(sidebar_scene)
    first.activeViewport.setZoom(2)
    app.workspaceController.createTab(sidebar_scene[2][1].series_instance_uid, 'Second', '2d')
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
    second = app.workspaceController.activeTab
    second.activeViewport.setZoom(5)
    _, other = detached(app, first)
    other.requestActivate()
    wait_until(other.isActive)
    click(other, find(other, 'primaryTool-zoom'))
    QTest.keyClick(other, Qt.Key_R)
    assert first.activeViewport.zoom == 1 and second.activeViewport.zoom == 5
    window.requestActivate()
    wait_until(window.isActive)
    click(window, find(window, 'primaryTool-zoom'))
    first.activeViewport.setZoom(2)
    QTest.keyClick(window, Qt.Key_R)
    assert first.activeViewport.zoom == 2 and second.activeViewport.zoom == 1
    assert not sidebar_scene[3], sidebar_scene[3]


def test_fusion_view_reset_uses_selected_modality(sidebar_scene, paired_series, tmp_path):
    from voxplane.model import DicomFolderScanSnapshot
    window, app, _, warnings = sidebar_scene
    _, ct, pet = paired_series
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    app.workspaceController.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = app.workspaceController.activeTab
    wait_until(lambda: tab.ready)
    window.requestActivate()
    original = (tab.ctCenter, tab.ctWidth)
    pet_upper = tab.pet_display.target.upper
    tab.setCtWindow(300, 800)
    tab.pet_display.set_upper(pet_upper / 2)
    click(window, find(window, 'primaryTool-ct-window'))
    QTest.keyClick(window, Qt.Key_R)
    assert (tab.ctCenter, tab.ctWidth) == original and tab.pet_display.target.upper == pet_upper / 2
    tab.setCtWindow(300, 800)
    click(window, find(window, 'primaryTool-pet-window'))
    assert label(find(window, 'activeToolReset')).endswith('(R)')
    QTest.keyClick(window, Qt.Key_R)
    assert tab.pet_display.target.upper == pet_upper and (tab.ctCenter, tab.ctWidth) == (300, 800)
    assert float(find(window, 'petDisplayUpperInput').property('text')) == pytest.approx(pet_upper, abs=.0005)
    wait_until(lambda: tab._committed_request == tab._requested)
    assert window.grabWindow().save(str(tmp_path / 'fusion-pet-reset.png'))
    tab.setOpacity(.75)
    click(window, find(window, 'primaryTool-fusion-blend'))
    QTest.keyClick(window, Qt.Key_R)
    assert tab.opacity == .5 and (tab.ctCenter, tab.ctWidth) == (300, 800)
    click(window, find(window, 'primaryTool-registration'))
    tab.setRegistrationParameters([7, 0, 0, 0, 0, 0])
    assert tab.registrationParameters[0] == 7
    reset = find(window, 'activeToolReset')
    assert find(window, 'toolResetBar').isAncestorOf(reset) and label(reset).endswith('(R)')
    click(window, reset)
    assert tab.registrationParameters[0] == 0
    tab.setRegistrationParameters([7, 0, 0, 0, 0, 0])
    QTest.keyClick(window, Qt.Key_R)
    assert tab.registrationParameters[0] == 0
    assert not warnings, warnings


@pytest.mark.skipif(os.environ.get('VOXPLANE_NATIVE_QA') != '1', reason='Requires a native desktop OpenGL window')
def test_native_volume_canvas_keeps_active_menu_shortcut(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '3D keys', '3d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    vp = ws.activeViewport
    wait_until(lambda: vp._host is not None and vp._host.surface_ready())
    wait_until(lambda: vp._host.frame_ready, timeout=15000)
    window.requestActivate()
    click(window, find(window, 'primaryTool-zoom'))
    QTest.keyClick(window, Qt.Key_2)
    assert vp.zoom == 2
    canvas = vp._host.vtk_widget
    QTest.mouseClick(canvas.windowHandle(), Qt.LeftButton, Qt.NoModifier, QPoint(60, 60))
    QTest.keyClick(QGuiApplication.focusWindow(), Qt.Key_R)
    assert vp.zoom == 1
    assert not warnings, warnings


@pytest.mark.parametrize('compact', [False, True])
def test_palette_reset_follows_visible_menu_and_preserves_other_view_state(sidebar_scene, compact):
    window, app, tab = reading_scene(sidebar_scene)
    view = tab.activeViewport
    view.applyColorMap('blackbody')
    view.setZoom(2)
    if compact:
        click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_C)
    reset = find(window, 'compactPaletteReset' if compact else 'activeToolReset')
    assert reset.property('tooltipText').endswith('(R)')
    QTest.keyClick(window, Qt.Key_R)
    assert view.activeColorMap == 'grayscale' and view.zoom == 2
    if compact:
        QTest.keyClick(window, Qt.Key_Escape)
        wait_until(lambda: not window.property('activeReadingMenu'))
        view.applyColorMap('blackbody')
        QTest.keyClick(window, Qt.Key_R)
        assert view.activeColorMap == 'blackbody'
    assert not sidebar_scene[3], sidebar_scene[3]

def test_orientation_reset_is_owned_by_mpr_comparison_layout_only(sidebar_scene):
    window, app, single = reading_scene(sidebar_scene)
    assert app.shortcutController.assign('view-reset', 'P')
    QTest.keyClick(window, Qt.Key_G)
    # A normal layout has no reset action and releases P to the primary pan tool.
    assert find(window, 'primaryTool-pan').parentItem().property('tooltipText').endswith('(P)')
    QTest.keyClick(window, Qt.Key_P)
    assert single.toolController.activeTool == 'pan'

    ws = app.workspaceController
    ws.createMprCompareTab(*(r.series_instance_uid for r in sidebar_scene[2][:2]))
    tab = ws.activeTab
    wait_until(lambda: tab.ready)
    active, other = tab.groups
    tab.activateViewport(active.activeViewport.viewportId)
    before = active._target_mpr_state
    other_before = other._target_mpr_state
    active._handle_mpr_3d_rotation_requested((1., 0., 0.), .2)
    assert active._target_mpr_state.frame != before.frame
    QTest.keyClick(window, Qt.Key_G)
    reset = find(window, 'compareMprResetOrientation')
    assert reset.property('text').endswith('(P)')
    QTest.keyClick(window, Qt.Key_P)
    assert active._target_mpr_state.frame == before.frame
    assert other._target_mpr_state == other_before
    assert tab.activeToolController.activePanel == 'mpr-layout'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_3d_camera_reset_requires_visible_enabled_tool(sidebar_scene, monkeypatch):
    from voxplane.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    monkeypatch.setattr(VolumeViewportController, 'ensureNativeView', lambda self: None)
    monkeypatch.setattr(VolumeViewportController, 'setNativeVisible', lambda self, visible: None)
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '3D camera', '3d')
    volume = ws.activeViewport
    wait_until(lambda: volume.loadState == 'ready')
    window.requestActivate()
    click(window, find(window, 'primaryTool-volume-rotate'))
    volume.setViewFace('L')
    volume.setZoom(3)
    assert label(find(window, 'activeToolReset')).endswith('(R)')
    QTest.keyClick(window, Qt.Key_R)
    assert volume.currentFace == 'A' and volume.zoom == 3
    volume.setViewFace('L')
    click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_R)
    assert volume.currentFace == 'L'
    from test_sidebar_style_polish import reveal
    rail = find(window, 'compactToolRail')
    reveal(window, rail, find(window, 'compactTool-volume-direction'))
    assert find(window, 'compactAction-view-reset').parentItem().property('tooltipText').endswith('(R)')
    QTest.keyClick(window, Qt.Key_R)
    assert volume.currentFace == 'A' and volume.zoom == 3
    volume.setViewFace('P')
    volume.render_failed('Volume unavailable')
    assert not find(window, 'compactAction-view-reset').isEnabled()
    QTest.keyClick(window, Qt.Key_R)
    assert volume.currentFace == 'P' and volume.zoom == 3
    assert not warnings, warnings
