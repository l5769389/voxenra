from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PySide6.QtTest import QTest

from qt_dicom_viewer.model import DicomFolderScanSnapshot, ImagePoint, MeasurementKind
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_results import source as source
from test_dicom_tags import qt_app as qt_app, wait_until
from test_segmentation_import import external_seg as external_seg, full_mask
from test_pacs_qml import scene as scene
from test_tag_qml import find, click
from PySide6.QtCore import QPointF


def open_mpr(app, series, folder):
    snapshot = DicomFolderScanSnapshot(
        folder, len(series.instances), len(series.instances), 0, [series]
    )
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    app.workspaceController.createTab(series.series_instance_uid, "Exchange", "mpr")
    tab = app.workspaceController.activeTab
    wait_until(
        lambda: (
            bool(tab.voiController.sources) and all(
                view._plane_geometry is not None and not view.render_pending
                for view in tab.viewports_by_id.values())
        )
    )
    return tab


@pytest.fixture
def exchange(qt_app, source, tmp_path):
    app = AppController(DicomImageProvider(), settings_path=False)
    tab = open_mpr(app, source[0], tmp_path)
    yield app, tab, app.exportController.dicomResults
    app.shutdown()


def import_masks(controller, path):
    assert controller.import_from(path), controller.message
    wait_until(lambda: not controller.busy)
    assert not controller.isError, controller.message


def test_import_history_persistence_and_reexport(exchange, external_seg, tmp_path):
    app, tab, controller = exchange
    path, expected, _ = external_seg
    voi, history = tab.voiController, tab.historyController
    import_masks(controller, path)
    wait_until(lambda: not voi.busy)
    assert len(voi.items) == 2 and all(i["fixedMask"] for i in voi.items)
    assert all(voi.masks(view) for view in tab.viewports_by_id.values())
    assert not voi.overlays(tab.activeViewport)
    history.capture()
    history.undo()
    assert not voi.records
    history.redo()
    wait_until(lambda: len(voi.evaluations) == 2 and not voi.busy)
    first = voi.records[0]
    voi.select(first["id"])
    voi.setThreshold(999)
    voi.setDepth(999)
    assert first["threshold"] == 0
    np.testing.assert_array_equal(
        full_mask(first, expected.shape[:3]), expected[..., 0]
    )
    voi.renameItem(first["id"], "Renamed")
    voi.setColor(first["id"], "#ffbb55")
    voi.toggleVisible(first["id"])
    assert not first["visible"]
    # A duplicate file must not partially append its segments.
    assert controller.import_from(path)
    wait_until(lambda: not controller.busy)
    assert controller.isError and len(voi.records) == 2
    document = app.workspaceDocumentController
    workspace_file = tmp_path / "masks.voxworkspace"
    assert document.save_to(workspace_file)
    wait_until(lambda: not document.busy)
    assert not document.isError, document.message
    path.unlink()
    assert document.restore_from(workspace_file)
    wait_until(lambda: not document.busy, timeout=20000)
    assert not document.isError, document.message
    restored = app.workspaceController.activeTab.voiController
    wait_until(lambda: len(restored.evaluations) == 2 and not restored.busy)
    assert restored.records[0]["name"] == "Renamed"
    assert restored.records[0]["color"] == "#ffbb55"
    assert not restored.records[0]["visible"]
    for index, record in enumerate(restored.records):
        np.testing.assert_array_equal(
            full_mask(record, expected.shape[:3]), expected[..., index]
        )
    assert controller.export_to(tmp_path)
    wait_until(lambda: not controller.busy)
    assert not controller.isError, controller.message
    assert len(list(Path(controller.resultPath).glob("*.dcm"))) == 2


@pytest.mark.parametrize("change", ["cancel", "close", "phase"])
def test_import_does_not_publish_after_target_changes(
    exchange, external_seg, monkeypatch, change
):
    app, tab, controller = exchange
    import qt_dicom_viewer.core.segmentation_import as module

    actual = module.read_segmentation
    entered, release = Event(), Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return actual(*args, **kwargs)

    monkeypatch.setattr(module, "read_segmentation", blocked)
    try:
        assert controller.import_from(external_seg[0])
        assert entered.wait(3)
        if change == "cancel":
            controller.cancel()
        elif change == "close":
            app.workspaceController.closeTab(tab.tab_config.tab_id)
        else:
            tab.voiController._phase = "another-phase"
        release.set()
        wait_until(lambda: not controller.busy)
        assert not tab.voiController.records
        assert controller.isError == (change != "cancel")
    finally:
        release.set()


def test_selected_freehand_conversion_keeps_measurement_and_can_undo(
    exchange, tmp_path
):
    from test_series_sidebar import phantom_series

    app, _, controller = exchange
    folder = tmp_path / "orthogonal"
    folder.mkdir()
    series = phantom_series(folder, 1, "TEST", "1.2.3.9", "20260916")
    tab = open_mpr(app, series, folder)
    view = tab.activeViewport
    tab.toolController.activateTool("measure")
    measure = view._measure_controller
    wait_until(lambda: measure.frame_key is not None)
    context = view._measurement_context(1, 0.1, kind=MeasurementKind.FREEHAND)
    identifier = measure.paste_points(
        [ImagePoint(1, 1), ImagePoint(4, 1), ImagePoint(3, 4)], context
    )
    assert identifier
    tab.historyController.capture()
    assert controller.convertSelectedRoi(), controller.message
    wait_until(lambda: not controller.busy)
    assert not controller.isError, controller.message
    assert len(tab.voiController.records) == 1
    assert identifier in measure._measurements
    tab.historyController.capture()
    tab.historyController.undo()
    assert not tab.voiController.records and identifier in measure._measurements
    QTest.qWait(50)


def test_import_button_and_mask_list_at_small_window(
    scene, source, external_seg, tmp_path, monkeypatch
):
    window, app, warnings = scene
    tab = open_mpr(app, source[0], tmp_path)
    controller = app.exportController.dicomResults
    window.resize(1000, 600)
    app.settingsController.setValue("layout", "rightPanelWidth", 240)
    monkeypatch.setattr(
        "qt_dicom_viewer.ui.controller.dicom_results_controller.QFileDialog.getOpenFileName",
        lambda *args: (str(external_seg[0]), ""),
    )
    QTest.qWait(100)
    flickable = find(window, "toolDetailFlickable")

    def reveal(name):
        item = find(window, name)
        edge = item.mapToScene(QPointF(0, item.height())).y()
        bottom = flickable.mapToScene(QPointF(0, flickable.height())).y()
        if edge > bottom:
            flickable.setProperty(
                "contentY", flickable.property("contentY") + edge - bottom + 8
            )
        QTest.qWait(70)
        return item

    click(window, find(window, "primaryTool-import"))
    QTest.qWait(80)
    click(window, reveal("importSegmentation"))
    wait_until(lambda: not controller.busy)
    assert not controller.isError, controller.message
    click(window, reveal("manageImportedSegments"))
    QTest.qWait(80)
    first = tab.voiController.records[0]
    click(window, reveal("voiVisibility-" + first["id"]))
    assert not first["visible"]
    original = first["color"]
    click(window, reveal("voiColor-" + first["id"]))
    assert first["color"] != original
    assert find(window, "voiRegionList").property("count") == 2
    click(window, reveal("voiDelete-" + first["id"]))
    assert len(tab.voiController.records) == 1
    assert not warnings, warnings


def test_refinement_history_workspace_and_nrrd_exchange(exchange, tmp_path):
    app, tab, io = exchange
    c, view = tab.voiController, tab.activeViewport
    tab.toolController.activateTool('segmentation')
    c.newSegment(); c.setBrushDiameter(8)
    x, y = (view._plane_geometry.columns-1)/2, (view._plane_geometry.rows-1)/2
    c.begin(view, x, y, .1); c.finish(view, x+1, y)
    key = c.selectedId
    original = c.records[0]['mask'].copy()
    assert original.any()
    tab.historyController.capture()
    c.setEditMode('erase'); c.setBrushDiameter(100)
    c.begin(view, x, y, .1); c.finish(view, x, y)
    assert not c.records[0]['mask'].any()
    tab.historyController.capture(); tab.historyController.undo()
    wait_until(lambda: not c.busy)
    np.testing.assert_array_equal(c.records[0]['mask'], original)
    assert c.selectedId == key
    tab.historyController.redo(); wait_until(lambda: not c.busy)
    assert not c.records[0]['mask'].any()
    tab.historyController.undo(); wait_until(lambda: not c.busy)
    document = app.workspaceDocumentController
    path = tmp_path / 'refined.voxworkspace'
    assert document.save_to(path)
    wait_until(lambda: not document.busy)
    assert not document.isError, document.message
    assert document.restore_from(path)
    wait_until(lambda: not document.busy, timeout=20000)
    assert not document.isError, document.message
    restored = app.workspaceController.activeTab.voiController
    wait_until(lambda: bool(restored.sources) and not restored.busy)
    np.testing.assert_array_equal(restored.records[0]['mask'], original)
    assert io.export_nrrd_to(tmp_path)
    wait_until(lambda: not io.busy)
    assert not io.isError, io.message
    output = Path(io.resultPath)
    assert (output/'source.nrrd').exists() and (output/'segmentation.seg.nrrd').exists()
    assert io.import_from(output/'segmentation.seg.nrrd')
    wait_until(lambda: not io.busy)
    assert not io.isError, io.message
    assert len(restored.records) == 2
    np.testing.assert_array_equal(restored.records[1]['mask'], original)


def test_brush_keeps_qml_layers_alive_during_paint_and_erase(scene, source, tmp_path):
    from test_tag_qml import descendants
    from shiboken6 import getCppPointer
    window, app, warnings = scene
    tab = open_mpr(app, source[0], tmp_path)
    tab.toolController.activateTool('segmentation')
    c, view = tab.voiController, tab.activeViewport
    c.newSegment(); c.setBrushDiameter(8)
    cx, cy = (view._plane_geometry.columns-1)/2, (view._plane_geometry.rows-1)/2
    c.begin(view, cx, cy, .1); c.finish(view, cx, cy)
    def layers():
        return [x for x in descendants(window.contentItem()) if x.objectName() == 'mprSegmentationMask']
    # QML creates the three plane delegates asynchronously, even after the
    # controller has finished loading. Start the stroke only once all are ready.
    wait_until(lambda: len(layers()) == 3 and all(x.property('maskReady') for x in layers()))
    initial = {getCppPointer(x)[0] for x in layers()}
    assert initial
    for mode in ('paint', 'erase'):
        c.setEditMode(mode)
        c.begin(view, cx, cy, .1)
        for x in np.linspace(cx, cx+1, 12):
            c.update(view, float(x), cy)
            QTest.qWait(5)
            assert {getCppPointer(x)[0] for x in layers()} == initial
            assert all(x.property('maskReady') for x in layers())  # Image.Ready
        c.finish(view, cx+1, cy)
        QTest.qWait(30)
        assert {getCppPointer(x)[0] for x in layers()} == initial
    slider = find(window, 'segmentationBrushSlider')
    assert slider.isVisible()
    assert slider.property('from') == 1 and slider.property('to') == 50
    c.setBrushDiameter(75)
    QTest.qWait(10)
    assert c.brushDiameter == 75 and slider.property('value') == 50
    c.setBrushDiameter(.5)
    QTest.qWait(10)
    assert c.brushDiameter == .5 and slider.property('value') == 1
    click(window, slider)
    assert 20 < c.brushDiameter < 30
    assert find(window, 'segmentationBrushDiameter').property('numberValue') == c.brushDiameter
    for name, shortcut in [('segmentationUndo', tab.historyController.undoShortcutText),
                           ('segmentationRedo', tab.historyController.redoShortcutText)]:
        assert '(' + shortcut + ')' in find(window, name).property('text')
    tab.historyController.capture()
    observed = []
    c.masksChanged.connect(lambda: observed.append(len(c.masks(view))))
    for action in (tab.historyController.undo, tab.historyController.redo):
        action()
        QTest.qWait(30)
        assert {getCppPointer(x)[0] for x in layers()} == initial
        assert all(x.property('maskReady') for x in layers())
    assert observed and all(observed), observed
    # Relative size uses the same view scale for its cursor and actual voxels.
    from test_mpr_voi_qml import _owner
    from test_measurement_qml import _scene
    from PySide6.QtCore import Qt
    c.setBrushRelative(True)
    c.setBrushPercent(10)
    QTest.qWait(20)
    assert slider.property('to') == 25
    assert find(window, 'segmentationBrushDiameter').property('numberValue') == 10
    layer = next(x for x in descendants(window.contentItem())
                 if x.objectName() == 'dicomPixelLayer' and _owner(x) is view)
    diameters = []
    for zoom in (view.zoom, view.zoom * 2):
        view.apply_zoom(zoom)
        c.newSegment()
        QTest.qWait(30)
        start = _scene(layer, cx, cy)
        end = start + QPointF(8, 0).toPoint()
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(window, end, 20)
        assert c._draft is not None
        scale, side = view._brush_view_metrics
        assert c._draft['diameter'] == pytest.approx(side * .1 / scale)
        diameters.append(c._draft['diameter'])
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    assert diameters[1] == pytest.approx(diameters[0] / 2)
    c.setBrushRelative(False)
    for theme, locale in [('dark','zh-CN'), ('graphite','en-US'), ('light','en-US')]:
        app.settingsController.setValue('appearance', 'theme', theme)
        app.languageController.selectLanguage(locale)
        app.settingsController.setValue('layout', 'rightPanelWidth', 240)
        window.resize(1280, 720)
        tab.toolController.activateTool('segmentation')
        QTest.qWait(50)
        field = find(window, 'segmentationBrushDiameter')
        assert field.width() > 30 and field.isVisible()
        slider = find(window, 'segmentationBrushSlider')
        scope = find(window, 'segmentationBrushScope')
        tool = find(window, 'segmentationEditMode')
        assert field.width() <= 64 and slider.width() > field.width()
        assert abs(field.mapToScene(QPointF(0, field.height()/2)).y()
                   - slider.mapToScene(QPointF(0, slider.height()/2)).y()) < 1
        assert abs(scope.mapToScene(QPointF()).y() - tool.mapToScene(QPointF()).y()) < 1

    assert not warnings, warnings


def test_refinement_survives_fresh_process(exchange, tmp_path):
    import os
    import subprocess
    import sys
    app, tab, _ = exchange
    c, view = tab.voiController, tab.activeViewport
    tab.toolController.activateTool('segmentation')
    x, y = (view._plane_geometry.columns-1)/2, (view._plane_geometry.rows-1)/2
    for i in range(2):
        c.newSegment()
        c.setBrushDiameter(5 + i)
        c.begin(view, x, y, .1); c.finish(view, x + .5, y)
        c.renameItem(c.selectedId, 'Restart ' + str(i))
    c.toggleVisible(c.records[0]['id'])
    c.setEditMode('erase')
    c.setBrushDiameter(17)
    c.setBrushPercent(8)
    c.setBrushRelative(True)
    c.setBrushSphere(True)
    expected = dict(count=len(c.records), mode=c.editMode, selected=c.selectedId,
                    diameter=c.brushDiameter, relative=c.brushRelative,
                    percent=c.brushPercent, sphere=c.brushSphere)
    for i, record in enumerate(c.records):
        for key, field in [('mask', 'mask'), ('offset', 'mask_offset'), ('name', 'name'),
                           ('color', 'color'), ('visible', 'visible')]:
            expected[key + str(i)] = record[field]
    np.savez_compressed(tmp_path / 'expected.npz', **expected)
    manager = app.workspaceDocumentController
    path = tmp_path / 'restart.voxworkspace'
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    assert not manager.isError, manager.message
    result = subprocess.run([sys.executable, str(Path(__file__).parent / 'manual/verify_refinement_restart.py'),
                             str(path), str(tmp_path / 'expected.npz')],
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_refinement_tool_preferences_dirty_but_display_refresh_is_not(exchange, tmp_path):
    app, tab, _ = exchange
    c = tab.voiController
    manager = app.workspaceDocumentController
    wait_until(lambda: not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids and not c.busy)
    QTest.qWait(150)
    for change in (lambda: c.setEditMode('erase'), lambda: c.setBrushDiameter(23),
                   lambda: c.setBrushRelative(True), lambda: c.setBrushPercent(9),
                   lambda: c.setBrushSphere(True), lambda: c.setEnabled(False)):
        assert manager.save_to(tmp_path / 'preferences.voxworkspace')
        wait_until(lambda: not manager.busy)
        assert not manager.dirty
        c.changed.emit()  # Reformatting/redrawing is not a workspace edit.
        assert not manager.dirty
        change()
        assert manager.dirty


def test_history_signal_connections_preserve_static_qml_metadata(exchange):
    """QML must not cache transient per-instance signal-receiver metaobjects."""
    from qt_dicom_viewer.ui.controller.edit_history_controller import EditHistoryController
    _, tab, _ = exchange
    history = tab.historyController
    assert history.metaObject().methodCount() == EditHistoryController.staticMetaObject.methodCount()
    assert history.metaObject().indexOfSlot('capture()') >= 0
    assert history.metaObject().indexOfSlot('schedule()') >= 0
