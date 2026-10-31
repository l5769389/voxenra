"""Exercise independent scene cells with real DICOM reslicing and persistence."""
from dataclasses import replace
import pytest
from PySide6.QtCore import QCoreApplication, QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from test_compare_2d import comparison
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_workspace_persistence import draw_length
from qt_dicom_viewer.core.workspace_document import read_document
from qt_dicom_viewer.ui.controller.tab.two_d_tab_controller import PRESETS, placements


def open_scene(app, records):
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, 'Scene', '2d')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    tab = workspace.activeTab
    return tab, tab.twoDLayout


def test_grid_cells_cover_every_position_without_overlap():
    for key in PRESETS:
        rows, columns, cells = placements(key)
        covered = [(r,c) for cell in cells for r in range(cell['row'], cell['row']+cell['rowSpan'])
                   for c in range(cell['column'], cell['column']+cell['columnSpan'])]
        assert sorted(covered) == [(r,c) for r in range(rows) for c in range(columns)], key


def test_independent_cells_and_stack_plane_state_retention(comparison):
    app, records = comparison
    tab, layout = open_scene(app, records)
    stack = tab.activeViewport
    stack.setSliceIndex(2)
    stack.setZoom(2)
    wait_until(lambda: stack._frame_meta.slice_index == 2)
    measurement = draw_length(stack)
    layout.setLayout('2x2')
    assert len(layout.cells) == 4 and layout.cells[1]['viewport'] is None
    assert layout.loadSeries(1, records[1].series_instance_uid)
    other = tab.activeViewport
    wait_until(lambda: other.loadState == 'ready')
    assert other.viewport_config.series_uid == records[1].series_instance_uid
    assert stack.sliceIndex == 2 and stack.zoom == 2
    for mode in ('axial', 'coronal', 'sagittal'):
        layout.setMode(0, mode)
        plane = tab.activeViewport
        wait_until(lambda: plane.loadState in ('ready', 'error'))
        assert plane.loadState == 'ready', plane.errorMessage
        assert plane.viewportType == mode and not plane.hasCrosshair
        plane.setSliceIndex(0)
        wait_until(lambda: plane._frame_meta.slice_index == 0)
        assert other.sliceIndex == 0 and stack.sliceIndex == 2
    layout.setMode(0, 'stack')
    assert tab.activeViewport is stack and stack.sliceIndex == 2
    assert measurement in stack._measure_controller._measurements
    layout.setLayout('1x1')
    assert len(layout.cells) == 1
    layout.setLayout('2x2')
    assert layout.cells[1]['viewport'] is other
    layout.setCustomLayout(999, -1)
    assert (layout.rows, layout.columns) == (6, 1)
    assert not layout.loadSeries(-1, records[1].series_instance_uid)
    assert not layout.loadSeries(0, 'unknown')


def test_multiseries_scene_workspace_roundtrip(comparison, tmp_path):
    app, records = comparison
    tab, layout = open_scene(app, records)
    layout.setLayout('left-2')
    for index in (1, 2):
        layout.loadSeries(index, records[index].series_instance_uid)
        wait_until(lambda: tab.activeViewport.loadState == 'ready')
    layout.setMode(0, 'coronal')
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    view = tab.activeViewport
    view.setSliceIndex(0)
    wait_until(lambda: view._frame_meta.slice_index == 0)
    view.setZoom(2)
    mid = draw_length(view)
    tab.historyController.capture()
    assert tab.historyController.canUndo
    path = tmp_path / 'scene.voxworkspace'
    doc = app.workspaceDocumentController
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    assert not doc.isError, doc.message
    assert len(read_document(path)['tabs'][0]['series']) == 3
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy, timeout=20000)
    assert not doc.isError, doc.message
    restored = app.workspaceController.activeTab
    wait_until(lambda: all(v.loadState == 'ready' for v in restored.viewports_by_id.values()))
    assert restored.twoDLayout.layout == 'left-2'
    assert [c['seriesUid'] for c in restored.twoDLayout.cells] == [r.series_instance_uid for r in records]
    assert restored.activeViewport.viewportType == 'coronal'
    assert restored.activeViewport.sliceIndex == 0
    assert restored.activeViewport.zoom == 2
    assert mid in restored.activeViewport._measure_controller._measurements
    restored.twoDLayout.setMode(0, 'stack')
    assert restored.activeViewport.viewportType == 'stack'


def test_replacing_cell_rejects_late_frame_and_preserves_other_views(comparison):
    app, records = comparison
    tab, layout = open_scene(app, records)
    layout.setLayout('1x2')
    layout.loadSeries(1, records[0].series_instance_uid)
    old = tab.activeViewport
    wait_until(lambda: old.loadState == 'ready')
    old_request = old._build_render_request(initial=False)
    layout.loadSeries(1, records[1].series_instance_uid)
    assert not tab.contains_viewport(old_request.viewport_id)
    assert layout.cells[0]['viewport'].viewport_config.series_uid == records[0].series_instance_uid
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    # Empty active cells are also a valid autosave state.
    layout.setLayout('2x2')
    layout.activateCell(3)
    from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot
    assert tab_snapshot(tab)['activeView'] == ''


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_layout_tools_collapse_drag_and_cell_activation_in_qml(sidebar_scene, theme):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    tab, layout = open_scene(app, records)
    find(window, 'twoDCell-0')
    click(window, find(window, 'primaryTool-mpr-layout'))
    click(window, find(window, 'twoDLayout-2x2'))
    target = find(window, 'twoDSeriesDrop-1')
    position = target.mapToScene(QPointF(target.width()/2, target.height()/2))
    mime = QMimeData()
    mime.setData('application/x-voxenra-series', records[1].series_instance_uid.encode())
    enter = QDragEnterEvent(position.toPoint(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QCoreApplication.sendEvent(window, enter)
    move = QDragMoveEvent(position.toPoint(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QCoreApplication.sendEvent(window, move)
    drop = QDropEvent(position, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QCoreApplication.sendEvent(window, drop)
    assert drop.isAccepted()
    wait_until(lambda: layout.cells[1]['viewport'] is not None and layout.cells[1]['viewport'].loadState == 'ready')
    loaded = layout.cells[1]['viewport']
    assert loaded.viewport_config.series_uid == records[1].series_instance_uid
    image = find(window, 'imageViewport-' + loaded.viewportId)
    click(window, image)
    assert tab.activeViewport is loaded
    # Clicking a viewport must not recreate the QML surface mid-gesture.
    assert find(window, 'imageViewport-' + loaded.viewportId) is image
    click(window, find(window, 'toggleRightPanel'))
    panel = find(window, 'rightPanel')
    wait_until(lambda: panel.width() == 44)
    for name in ('window', 'scroll', 'pan', 'zoom'):
        click(window, find(window, 'compactTool-' + name))
        assert tab.activeToolController.activeTool == name
        assert tab.activeToolController.activePanel == ''
    assert not any(i.isVisible() and i.objectName() == 'primaryTool-mpr-layout' for i in descendants(panel))
    click(window, find(window, 'toggleRightPanel'))
    wait_until(lambda: panel.width() >= 220)
    assert not warnings, warnings


def test_mode_selector_keeps_its_view_on_pointer_interaction(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    layout.setLayout('1x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    selector = find(window, 'twoDPlane-1')
    click(window, selector)
    QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: tab.activeViewport.viewportType == 'axial' and tab.activeViewport.loadState == 'ready')
    view = tab.activeViewport
    image = find(window, 'imageViewport-' + view.viewportId)
    tab.toolController.activateTool('pan')
    QTest.qWait(150)
    center = image.mapToScene(QPointF(image.width()/2, image.height()/2)).toPoint()
    from PySide6.QtCore import QPoint
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(window, center + QPoint(16, 10), delay=30)
    QTest.mouseMove(window, center + QPoint(32, 20), delay=30)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center + QPoint(32, 20))
    assert view._state.pan_x != 0
    assert find(window, 'imageViewport-' + view.viewportId) is image
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, center)
    wait_until(lambda: tab.focusedViewportId == view.viewportId)
    tab.focusSingleViewport('')
    click(window, find(window, 'primaryTool-mpr-layout'))
    QTest.qWait(150)
    assert window.grabWindow().save(str(tmp_path / 'two-d-layout.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('collapsed', [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_sidebar_drops_series_in_second_viewport(sidebar_scene, collapsed, cancel):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    layout.setLayout('1x2')
    uid = records[1].series_instance_uid
    if collapsed:
        click(window, find(window, 'sidebarToggle'))
    entry = find(window, ('compactSeries-' if collapsed else 'series-') + uid)
    target = find(window, 'twoDSeriesDrop-1')
    point = entry.mapToScene(QPointF(entry.width()/2, entry.height()/2)).toPoint()
    end = target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseMove(window, end, delay=30)
    if cancel:
        QTest.keyClick(window, Qt.Key_Escape)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    if cancel:
        assert layout.cells[1]['viewport'] is None
        return
    wait_until(lambda: layout.cells[1]['viewport'] is not None and tab.activeViewport.loadState == 'ready')
    assert tab.activeViewport.viewport_config.series_uid == uid
    assert not warnings, warnings


@pytest.mark.parametrize('collapsed', [False, True])
def test_sidebar_hands_drag_outside_window_to_native(sidebar_scene, monkeypatch, collapsed):
    window, app, records, warnings = sidebar_scene
    uid = records[0].series_instance_uid
    captured = []
    from PySide6.QtGui import QDrag
    def capture(drag, *args):
        captured.append(bytes(drag.mimeData().data('application/x-voxenra-series')).decode())
        return Qt.IgnoreAction
    monkeypatch.setattr(QDrag, 'exec', capture)
    if collapsed:
        click(window, find(window, 'sidebarToggle'))
    entry = find(window, ('compactSeries-' if collapsed else 'series-') + uid)
    point = entry.mapToScene(QPointF(entry.width()/2, entry.height()/2)).toPoint()
    from PySide6.QtCore import QPoint
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseMove(window, QPoint(window.width() + 35, point.y()), delay=30)
    wait_until(lambda: bool(captured))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(window.width() + 35, point.y()))
    assert captured == [uid]
    assert not warnings, warnings


def test_layout_persistence_changes_do_not_create_fake_edit_undo(comparison):
    app, records = comparison
    tab, layout = open_scene(app, records)
    history = tab.historyController
    layout.setLayout('2x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    assert not history.canUndo
    app.workspaceDocumentController._dirty = False
    tab.activeViewport.setZoom(2)
    assert app.workspaceDocumentController._dirty
    mid = draw_length(tab.activeViewport)
    history.capture()
    assert history.canUndo
    history.undo()
    assert mid not in tab.activeViewport._measure_controller._measurements
    history.redo()
    assert mid in tab.activeViewport._measure_controller._measurements


def test_reject_malformed_layout_before_workspace_restore():
    from qt_dicom_viewer.core.scene_layout import validate_scene
    valid = dict(layout='1x1', rows=1, columns=1, active=0,
                 cells=[dict(uid='series', mode='stack', modes=['stack'])])
    validate_scene(valid, ['series'])
    for field, value in [('rows', 0), ('columns', 99), ('layout', 'bad'), ('active', 1), ('cells', [])]:
        with pytest.raises(ValueError):
            validate_scene(dict(valid, **{field: value}), ['series'])
    with pytest.raises(ValueError):
        validate_scene(valid, ['missing'])


from test_pet_fusion import paired_series


def test_pet_orthogonal_cells_preserve_display_units(qt_app, paired_series, tmp_path):
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    _, ct, pet = paired_series
    app = AppController(DicomImageProvider(), settings_path=tmp_path / 'pet-settings.json')
    try:
        app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
        tab, layout = open_scene(app, [ct])
        layout.setLayout('1x2')
        layout.loadSeries(1, pet.series_instance_uid)
        wait_until(lambda: tab.activeViewport.loadState == 'ready')
        layout.setMode(1, 'coronal')
        view = tab.activeViewport
        wait_until(lambda: view.loadState in ('ready', 'error'))
        assert view.loadState == 'ready', view.errorMessage
        view.setPetUnit('kbqml')
        wait_until(lambda: not view.petUnitPending)
        assert view._frame_meta.pixel_value_meta.unit_id == 'kbqml'
        layout.activateCell(0)
        assert not tab.activeViewport.isPetViewport
        layout.activateCell(1)
        assert tab.activeViewport is view and view.pet_active_unit_id == 'kbqml'
    finally:
        app.shutdown()


@pytest.mark.parametrize('collapsed', [False, True])
def test_sidebar_does_not_start_queued_drag_after_release(sidebar_scene, monkeypatch, collapsed):
    """A fast move/release may finish before Qt.callLater starts native dragging."""
    from PySide6.QtGui import QDrag, QMouseEvent
    from PySide6.QtCore import QEvent
    window, app, records, warnings = sidebar_scene
    uid = records[0].series_instance_uid
    captured = []
    monkeypatch.setattr(QDrag, 'exec', lambda *args: captured.append(True) or Qt.IgnoreAction)
    if collapsed:
        click(window, find(window, 'sidebarToggle'))
    entry = find(window, ('compactSeries-' if collapsed else 'series-') + uid)
    point = entry.mapToScene(QPointF(entry.width()/2, entry.height()/2))
    end = QPointF(window.width() + 35, point.y())
    for kind, position, button, buttons in (
        (QEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton),
        (QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton),
        (QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton),
    ):
        event = QMouseEvent(kind, position, window.mapToGlobal(position.toPoint()),
                            button, buttons, Qt.NoModifier)
        QCoreApplication.sendEvent(window, event)
    QTest.qWait(50)
    assert captured == []
    assert not warnings, warnings
