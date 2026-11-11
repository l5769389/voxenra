"""Tool keys must match visible controls and respect scoped menus and text input."""
import os
import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_input_settings_qml import reading_scene, visible_viewport
from test_tag_qml import find, click, descendants
from test_workspace_persistence import draw_length


@pytest.mark.parametrize('compact', [False, True])
def test_annotation_entry_and_modes_follow_visible_menu(sidebar_scene, compact, tmp_path):
    window, app, tab = reading_scene(sidebar_scene)
    app.panelController.selectSeries(sidebar_scene[2][0].series_instance_uid)
    if compact:
        click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_A)
    assert tab.toolController.activePanel == 'annotate'
    assert window.property('activeReadingMenu') == 'annotate'
    assert tab.activeViewport.activeInteraction == 'annotate:arrow'
    if not compact:
        assert not find(window, 'primaryTool-window').property('checked')
    arrow = find(window, 'compactAction-annotate:arrow' if compact else 'annotateArrowMode')
    text = find(window, 'compactAction-annotate:text' if compact else 'annotateTextMode')
    assert (arrow.parentItem() if compact else arrow).property('shortcutHint') == 'A'
    assert (text.parentItem() if compact else text).property('shortcutHint') == 'T'
    QTest.keyClick(window, Qt.Key_T)
    assert tab.activeViewport.activeInteraction == 'annotate:text'
    assert text.property('checked') and len(app.workspaceController.tabs) == 1
    QTest.keyClick(window, Qt.Key_A)
    assert arrow.property('checked') and tab.activeViewport.activeInteraction == 'annotate:arrow'
    assert window.grabWindow().save(str(tmp_path / f'annotation-keys-{compact}.png'))
    QTest.keyClick(window, Qt.Key_M)
    QTest.keyClick(window, Qt.Key_A)
    assert tab.toolController.activePanel == 'measure'
    assert tab.activeViewport.activeInteraction == 'measure:angle'
    QTest.keyClick(window, Qt.Key_E)
    assert tab.activeViewport.activeInteraction == 'measure:ellipse'
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('compact', [False, True])
def test_export_key_opens_panel_without_exporting_and_popup_owns_keys(sidebar_scene, compact, tmp_path):
    window, app, tab = reading_scene(sidebar_scene)
    view = tab.activeViewport
    view.setZoom(3)
    if compact:
        click(window, find(window, 'toggleRightPanel'))
    QTest.keyClick(window, Qt.Key_E)
    assert tab.toolController.activePanel == 'export'
    assert not app.exportController.busy and not app.exportController.resultPath
    if compact:
        from test_mpr_volume_tools_qml import item_window
        popup = window.findChild(QObject, 'compactVolumePanel')
        wait_until(lambda: popup.property('opened'))
        def export_panel():
            return next((item for item in descendants(popup.property('contentItem'))
                         if item.objectName() == 'exportPanel' and item.isVisible()), None)
        wait_until(lambda: export_panel() is not None)
        surface = item_window(export_panel())
        QTest.keyClick(surface, Qt.Key_Q)
        assert view.zoom == 3  # Only the floating export panel owns input.
        QTest.keyClick(surface, Qt.Key_Escape)
        wait_until(lambda: not popup.property('visible'))
    else:
        assert find(window, 'exportPanel').isVisible()
        assert find(window, 'primaryTool-export').parentItem().property('shortcutHint') == 'E'
        assert window.grabWindow().save(str(tmp_path / 'export-key.png'))
    assert not sidebar_scene[3], sidebar_scene[3]


def test_global_reset_and_local_reset_have_separate_scope(sidebar_scene):
    window, app, first = reading_scene(sidebar_scene)
    original = first.activeViewport
    original.setZoom(4)
    draw_length(original)
    ws = app.workspaceController
    ws.createTab(sidebar_scene[2][1].series_instance_uid, 'Second', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    view = ws.activeViewport
    draw_length(view)
    view.setZoom(3)
    view.apply_pan(20, 30)
    click(window, find(window, 'primaryTool-zoom'))
    QTest.keyClick(window, Qt.Key_R)
    assert view.zoom == 1 and view.panX != 0 and view.measurementController.measurementItems
    QTest.keyClick(window, Qt.Key_Q)
    assert (view.zoom, view.panX, view.panY) == (1, 0, 0)
    assert not view.measurementController.measurementItems
    assert original.zoom == 4 and original.measurementController.measurementItems
    assert find(window, 'primaryTool-reset').parentItem().property('shortcutHint') == 'Q'
    click(window, find(window, 'toggleRightPanel'))
    assert find(window, 'compactToolReset').parentItem().property('shortcutHint') == 'Q'
    view.setZoom(2)
    QTest.keyClick(window, Qt.Key_Q)
    assert view.zoom == 1
    assert not sidebar_scene[3], sidebar_scene[3]


def test_annotation_text_and_modal_keep_keys_local(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    QTest.keyClick(window, Qt.Key_A)
    QTest.keyClick(window, Qt.Key_T)
    view = tab.activeViewport
    view.setZoom(3)
    editor = find(window, 'annotationTextEditor')
    click(window, editor)
    QTest.keySequence(window, QKeySequence(QKeySequence.SelectAll))
    for key in (Qt.Key_A, Qt.Key_E, Qt.Key_Q, Qt.Key_T):
        QTest.keyClick(window, key)
    assert editor.property('text') == 'aeqt'
    assert view.activeInteraction == 'annotate:text' and view.zoom == 3
    visible_viewport(window).forceActiveFocus()
    app.feedbackController.show()
    wait_until(lambda: window.property('shortcutPopupOpen'))
    for key in (Qt.Key_A, Qt.Key_E, Qt.Key_Q):
        QTest.keyClick(window, key)
    assert view.zoom == 3 and tab.toolController.activePanel == 'annotate'
    assert not sidebar_scene[3], sidebar_scene[3]


def test_tool_and_annotation_mode_bindings_can_be_changed(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    keys = app.shortcutController
    for action, key in [('annotate', 'B'), ('export', 'H'), ('reset', 'F'), ('annotate:text', 'N')]:
        assert keys.assign(action, key)
    QTest.keyClick(window, Qt.Key_A)
    assert tab.toolController.activeTool == 'window'
    QTest.keyClick(window, Qt.Key_B)
    assert tab.toolController.activePanel == 'annotate'
    assert find(window, 'annotateTextMode').property('shortcutHint') == 'N'
    QTest.keyClick(window, Qt.Key_N)
    assert tab.activeViewport.activeInteraction == 'annotate:text'
    tab.activeViewport.setZoom(3)
    QTest.keyClick(window, Qt.Key_H)
    assert tab.toolController.activePanel == 'export'
    QTest.keyClick(window, Qt.Key_F)
    assert tab.activeViewport.zoom == 1
    assert not sidebar_scene[3], sidebar_scene[3]


def test_annotation_keys_create_arrow_and_text_then_reset_clears_current_view(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    view = tab.activeViewport
    pixels = find(window, 'dicomPixelLayer')
    QTest.keyClick(window, Qt.Key_A)
    for x, y in ((20, 20), (65, 45)):
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pixels.mapToScene(QPointF(x, y)).toPoint())
    arrows = view.measurementController.measurementItems
    assert len(arrows) == 1 and arrows[0]['type'] == 'arrow'
    QTest.keyClick(window, Qt.Key_T)
    for x, y in ((20, 65), (65, 75)):
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pixels.mapToScene(QPointF(x, y)).toPoint())
    texts = view.textAnnotationController.annotationItems
    assert len(texts) == 1 and texts[0]['text'] and not texts[0]['draft']
    QTest.keyClick(window, Qt.Key_Q)
    assert not view.measurementController.measurementItems
    assert not view.textAnnotationController.annotationItems
    assert not sidebar_scene[3], sidebar_scene[3]


def test_playback_and_pointer_drag_block_primary_commands(sidebar_scene):
    window, app, tab = reading_scene(sidebar_scene)
    view = tab.activeViewport
    view.setZoom(3)
    QTest.keyClick(window, Qt.Key_Space)
    assert tab.playing
    playing_tool = tab.toolController.activeTool
    for key in (Qt.Key_A, Qt.Key_E, Qt.Key_Q):
        QTest.keyClick(window, key)
    assert view.zoom == 3 and tab.toolController.activeTool == playing_tool
    QTest.keyClick(window, Qt.Key_Space)
    wait_until(lambda: not tab.playing and not view.render_pending)
    stopped_tool = tab.toolController.activeTool
    viewport = visible_viewport(window)
    pos = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.RightButton, Qt.NoModifier, pos)
    try:
        for key in (Qt.Key_A, Qt.Key_E, Qt.Key_Q):
            QTest.keyClick(window, key)
        assert view.zoom == 3 and tab.toolController.activeTool == stopped_tool
    finally:
        QTest.mouseRelease(window, Qt.RightButton, Qt.NoModifier, pos)
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.parametrize('kind', ['mpr', 'cpr', '3d', 'montage'])
def test_other_view_types_export_and_reset_only_supported_tools(sidebar_scene, monkeypatch, kind):
    from voxplane.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    monkeypatch.setattr(VolumeViewportController, 'ensureNativeView', lambda self: None)
    monkeypatch.setattr(VolumeViewportController, 'setNativeVisible', lambda self, visible: None)
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, kind, kind)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    window.requestActivate()
    wait_until(window.isActive)
    view = ws.activeViewport
    view.setZoom(3)
    QTest.keyClick(window, Qt.Key_A)
    if kind in ('3d', 'montage'):
        assert ws.activeTab.toolController.activeTool != 'annotate'
    else:
        assert ws.activeTab.toolController.activePanel == 'annotate'
    QTest.keyClick(window, Qt.Key_Q)
    assert view.zoom == 1
    QTest.keyClick(window, Qt.Key_E)
    assert ws.activeTab.toolController.activePanel == 'export'
    assert find(window, 'cprExportPanel' if kind == 'cpr' else 'exportPanel').isVisible()
    assert not warnings, warnings


def test_older_custom_view_binding_wins_over_new_annotation_default(qt_app, tmp_path):
    import json
    from voxplane.ui.controller.settings_controller import SettingsController
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'shortcuts': {'bindings': {'open-view-mpr': 'A', 'zoom': 'Q'}}}))
    bindings = SettingsController(path=path).section('shortcuts')['bindings']
    assert bindings['open-view-mpr'] == 'A' and bindings['annotate'] == ''
    assert bindings['zoom'] == 'Q' and bindings['reset'] == ''


@pytest.mark.parametrize('role', ['reference-a', 'curved'])
def test_cpr_reset_preserves_path_and_matches_button(sidebar_scene, role):
    from test_cpr_controller import draw
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CPR reset', 'cpr')
    tab = ws.activeTab
    wait_until(lambda: tab.referencesReady)
    draw(tab, ((20, 20), (60, 65)))
    path = tab.selectedPathId
    curve = tab._result.curve
    view = tab.viewForRole(role)
    tab.activateViewport(view.viewportId)
    window.requestActivate()
    wait_until(window.isActive)
    view.setZoom(3)
    QTest.keyClick(window, Qt.Key_Q)
    assert view.zoom == 1 and tab.selectedPathId == path and tab._result.curve is curve
    view.setZoom(2)
    click(window, find(window, 'primaryTool-reset'))
    assert view.zoom == 1 and tab.selectedPathId == path and tab._result.curve is curve
    assert not warnings, warnings


def test_detached_reading_window_resets_only_its_active_view(sidebar_scene):
    from test_tab_windows import detached
    window, app, first = reading_scene(sidebar_scene)
    first.activeViewport.setZoom(3)
    ws = app.workspaceController
    ws.createTab(sidebar_scene[2][1].series_instance_uid, 'Main', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    second = ws.activeTab
    second.activeViewport.setZoom(4)
    _, other = detached(app, first)
    other.requestActivate()
    wait_until(other.isActive)
    QTest.keyClick(other, Qt.Key_Q)
    assert first.activeViewport.zoom == 1 and second.activeViewport.zoom == 4
    QTest.keyClick(other, Qt.Key_E)
    assert first.toolController.activePanel == 'export' and second.toolController.activePanel != 'export'
    assert not sidebar_scene[3], sidebar_scene[3]


@pytest.mark.skipif(os.environ.get('VOXPLANE_NATIVE_QA') != '1', reason='Requires a native VTK desktop window')
@pytest.mark.parametrize('kind', ['3d', 'mpr'])
def test_native_volume_focus_keeps_reset_and_export_keys(sidebar_scene, kind):
    from PySide6.QtCore import QPoint
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Native keys', kind)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    if kind == 'mpr':
        tab.mprLayout.setLayout('quad')
        tab.mprLayout.activate()
    view = tab.activeViewport
    assert view.viewportType == 'volume'
    wait_until(lambda: view._host is not None and view._host.surface_ready())
    view.setZoom(3)
    window.requestActivate()
    QTest.mouseClick(view._host.vtk_widget.windowHandle(), Qt.LeftButton, Qt.NoModifier, QPoint(60, 60))
    QTest.keyClick(QGuiApplication.focusWindow(), Qt.Key_Q)
    assert view.zoom == 1
    QTest.keyClick(QGuiApplication.focusWindow(), Qt.Key_E)
    assert tab.activeToolController.activePanel == 'export'
    assert find(window, 'exportPanel').isVisible()
    assert not warnings, warnings
