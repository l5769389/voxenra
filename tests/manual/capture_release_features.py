"""Additional real-window README scenes, invoked by capture_readme.py."""
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from test_tag_qml import descendants, find


def capture_feature(app, window, uid, scene, output, folder, pump, wait, ready):
    ws = app.workspaceController
    frames = []
    output.mkdir(parents=True, exist_ok=True)
    app.panelController.selectSeries(uid)
    app.settingsController.setValue('layout', 'rightPanelWidth', 300)

    def shot(name=None, native=False, duration=650):
        pump(160)
        screen = QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen()
        picture = screen.grabWindow(window.winId()) if native else window.grabWindow()
        assert not picture.isNull()
        if name:
            assert picture.save(str(output / (name + '.png')), 'PNG')
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        picture.save(buffer, 'PNG')
        image = Image.open(BytesIO(data.data())).convert('RGB')
        image.thumbnail((1100, 760), Image.Resampling.LANCZOS)
        frames.append((image, duration))

    def save_animation(name):
        # One palette covering every frame avoids losing newly displayed colors.
        swatches = Image.new('RGB', (160 * len(frames), 100))
        for index, (frame, _) in enumerate(frames):
            swatches.paste(frame.resize((160, 100)), (160 * index, 0))
        palette = swatches.quantize(colors=224)
        indexed = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im, _ in frames]
        indexed[0].save(output / (name + '.gif'), save_all=True, append_images=indexed[1:],
                        duration=[duration for _, duration in frames], loop=0, disposal=2)
        print(name, len(frames), 'frames', flush=True)

    def reveal(name):
        pump(150)
        from test_settings_redesign import find_any
        item = find_any(window, name)
        flick = find(window, 'toolDetailFlickable')
        y = item.mapToScene(QPointF(0, item.height())).y()
        bottom = flick.mapToScene(QPointF(0, flick.height())).y()
        if y > bottom:
            flick.setProperty('contentY', flick.property('contentY') + y - bottom + 8)
        pump()
        return item

    if scene == '04-volume-rendering':
        ws.createTab(uid, 'CT · 3D 模板', '3d')
        ready()
        view = ws.activeViewport
        wait(lambda: view._host is not None and view._host.backend._initialized)
        ws.activeTab.toolController.activateTool('volume-preset')
        pump(600)
        shot(scene, native=True, duration=1200)
        for preset in ('bone', 'cardiac', 'lung', 'aaa'):
            view.applyVolumePreset(preset)
            pump(350)
            assert view.currentPresetId == preset
            shot(native=True, duration=1100)
        ws.activeTab.toolController.activateTool('volume-rotate')
        size = (view._host.width(), view._host.height())
        view.begin_drag((size[0] * .4, size[1] * .45), size)
        for step in range(1, 13):
            view.update_drag((size[0] * (.4 + step * .012), size[1] * (.45 + step * .003)))
            shot(native=True, duration=100)
        view.end_drag()
        shot(native=True, duration=900)
        save_animation('04-volume-presets')
        return

    kind = '2d' if scene == '01-2d-measurement' else 'mpr'
    if kind == '2d':
        window.resize(1440, 900)
        app.settingsController.setValue('layout', 'rightPanelCollapsed', False)
    ws.createTab(uid, 'CT · 自由形状测量' if kind == '2d' else 'CT · 分割与结果', kind)
    ready()
    tab = ws.activeTab
    if kind == 'mpr':
        tab.mprLayout.setLayout('left')
        view = next(v for v in tab.viewports_by_id.values() if v.viewportType == 'axial')
        tab.activateViewport(view.viewportId)
    view = tab.activeViewport
    view.applyWindowPreset(40, 400)
    pump(200)
    tab.toolController.activateTool('measure')
    tab.toolController.selectInteraction('measure:freehand')
    pump()
    # Find the image owned by the active viewport through the QML parent chain.
    from test_mpr_voi_qml import _owner
    layer = next(item for item in descendants(window.contentItem())
                 if item.objectName() == 'dicomPixelLayer' and item.isVisible() and _owner(item) is view)
    height, width = view._modality_pixel.shape
    points = [(width * (.53 + .10 * np.cos(a)), height * (.55 + .11 * np.sin(a)))
              for a in np.linspace(0, 2*np.pi, 13)]
    position = lambda p: layer.mapToScene(QPointF(p[0]+.5, p[1]+.5)).toPoint()
    shot(duration=800)
    for point in points:
        QTest.mouseMove(window, position(point), 15)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position(point))
        shot(duration=200)
    assert len(view._measure_controller.committed_measurements) == 1
    QTest.mouseMove(window, QPointF(700, 14).toPoint())
    shot(scene if kind == '2d' else '31-freehand-to-seg', duration=1600)
    if kind == '2d':
        save_animation('01-freehand-measurement')
        frames.clear()
        view._measure_controller.clear_all()
        tab.toolController.selectInteraction('measure:curve')
        for point in [(width*.3,height*.5),(width*.38,height*.4),
                      (width*.5,height*.37),(width*.63,height*.4),(width*.7,height*.5)]:
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position(point))
            shot(duration=300)
        QTest.keyClick(window, Qt.Key_Return)
        assert len(view._measure_controller.committed_measurements) == 1
        QTest.mouseMove(window, QPointF(700, 14).toPoint())
        shot('33-curve-measurement', duration=1800)
        save_animation('33-curve-measurement')
        return

    results = app.exportController.dicomResults
    assert results.convertSelectedRoi()
    wait(lambda: not results.busy)
    assert not results.isError, results.message
    voi = tab.voiController
    assert len(voi.records) == 1 and voi.records[0]['mask_origin'] == 'roi'
    tab.toolController.activateTool('segmentation')
    voi.renameItem(voi.records[0]['id'], '自由形状区域')
    shot(duration=1200)
    voi.begin(view, width*.28, height*.25, .1)
    voi.finish(view, width*.72, height*.78)
    wait(lambda: not voi.busy and len(voi.evaluations) == 2)
    voi.rename('骨性结构')
    assert all(e.metrics['count'] > 0 for e in voi.evaluations.values())
    shot(scene, duration=1600)
    tab.toolController.activateTool('export')
    reveal('exportStructuredReport')
    shot('32-structured-report', duration=1600)
    (folder / 'DICOM-Results').mkdir()
    assert results.export_to(folder / 'DICOM-Results', kind='sr')
    wait(lambda: not results.busy)
    assert not results.isError, results.message
    directory = Path(results.resultPath)
    assert list(directory.glob('SR-*.dcm')) and list(directory.glob('SEG-*.dcm'))
    voi.clear('')
    view._measure_controller.clear_all()
    tab.toolController.activateTool('import')
    shot(duration=1200)
    assert results.import_from(next(directory.glob('SEG-*.dcm')))
    wait(lambda: not results.busy and not voi.busy)
    assert not results.isError, results.message
    assert len(voi.records) == 2 and all(r['mask_origin'] == 'imported' for r in voi.records)
    shot('33-associated-import', duration=1600)
    tab.toolController.activateTool('segmentation')
    shot('34-segment-management', duration=1600)
    save_animation('02-segmentation-exchange')


def capture_layout_animation(app, window, output, pump, wait):
    tab = app.workspaceController.activeTab
    frames = []
    for layout in ('quad', 'left', 'columns', 'rows', 'right', 'quad'):
        tab.mprLayout.setLayout(layout)
        tab.activateViewport(next(iter(tab.viewports_by_id)))
        tab.toolController.activateTool('mpr-layout')
        wait(lambda: not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids)
        pump(450)
        screen = QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen()
        shot = screen.grabWindow(window.winId())
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        shot.save(buffer, 'PNG')
        image = Image.open(BytesIO(data.data())).convert('RGB')
        image.thumbnail((1100, 760), Image.Resampling.LANCZOS)
        frames.append(image)
    palette = frames[0].quantize(colors=224)
    frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    frames[0].save(output / '11-mpr-layouts.gif', save_all=True, append_images=frames[1:],
                   duration=1200, loop=0, disposal=2)
