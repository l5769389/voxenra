"""Actual anonymous PNG pixels, cancellation, and the shared DICOM identity rules."""
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pydicom
import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from voxplane.ui.controller.export_controller import ExportController, copy_dicom_series
from test_measurement_qml import viewport, qt_app, _visual_children
from test_dicom_tags import make_series, wait_until


def capture(item):
    grab = item.grabToImage()
    ready = []
    grab.ready.connect(lambda: ready.append(True))
    wait_until(lambda: ready)
    return grab.image()


def pixels(image):
    # bits() borrows the QImage buffer; keep its owner alive while copying.
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    return converted.bits().tobytes()


@pytest.fixture
def exporter(viewport, tmp_path, monkeypatch):
    view, controller, _, warnings = viewport
    series = make_series(tmp_path, 2)
    workspace = SimpleNamespace(activeViewport=controller)
    exporter = ExportController(workspace, None)
    exporter.current_series = lambda: [series]
    target = tmp_path / 'anonymous.png'
    monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(target), 'PNG'))
    try:
        yield view, controller, exporter, series, target, warnings
    finally:
        exporter.shutdown()


def test_png_removes_all_corner_free_text_and_annotation_text_then_restores_view(exporter, tmp_path):
    view, controller, exporter, series, target, warnings = exporter
    root = view.rootObject()
    overlay = next(i for i in _visual_children(root) if i.objectName() == 'viewportMetadataOverlay')
    corner = next(i for i in _visual_children(root) if i.objectName() == 'overlay-topLeft')
    corner.setProperty('text', 'SECRET^患者姓名\nID: SECRET-12345\n医院及检查描述 SECRET')
    text = controller.textAnnotationController
    text.setAnnotationText('SECRET 病人姓名')
    text.addAnnotation(45, 50, 120, 130)
    QTest.qWait(30)
    originals = [i.path.read_bytes() for i in series.instances]
    identified = capture(root)
    root.setProperty('anonymousExport', True)
    root.setProperty('capturingPng', True)
    expected = capture(root)
    assert not overlay.isVisible()
    labels = [i for i in _visual_children(root) if i.objectName().startswith('annotationLabel-')]
    assert labels and not any(i.isVisible() for i in labels)
    root.setProperty('anonymousExport', False)
    root.setProperty('capturingPng', False)
    assert pixels(identified) != pixels(expected)
    exporter.exportPng(root, 1.0)  # Default is anonymous without a caller flag.
    wait_until(lambda: not exporter.busy)
    assert not exporter.isError, exporter.message
    image = QImage(str(target))
    assert pixels(image) == pixels(expected)
    assert not image.textKeys()
    assert not root.property('anonymousExport') and not root.property('capturingPng') and overlay.isVisible()
    assert all(i.isVisible() for i in labels)
    assert len(text.annotationItems) == 1
    assert [i.path.read_bytes() for i in series.instances] == originals
    identified.save(str(tmp_path / 'identified-reference.png'))
    expected.save(str(tmp_path / 'anonymous-reference.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('action', ['cancel', 'switch', 'close'])
def test_header_check_cancellation_and_tab_changes_do_not_export_other_view(exporter, monkeypatch, action):
    view, controller, exporter, series, target, warnings = exporter
    entered, release = Event(), Event()
    def check(_):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr('voxplane.ui.controller.export_controller.check_pixel_identity', check)
    exporter.exportPng(view.rootObject(), 1.0)
    wait_until(entered.is_set)
    if action == 'cancel':
        exporter.cancel()
    else:
        exporter.workspace.activeViewport = None if action == 'close' else SimpleNamespace()
    release.set()
    wait_until(lambda: not exporter.busy)
    assert not target.exists()
    assert not view.rootObject().property('anonymousExport')
    assert not warnings, warnings


def test_capture_cancel_restores_overlay_and_old_callback_cannot_save_new_capture(exporter, monkeypatch):
    view, controller, exporter, series, target, warnings = exporter
    original = exporter._capture_png
    old_ids = []
    def cancel_capture():
        original()
        old_ids.append(exporter._grab_id)
        exporter.cancel()
    monkeypatch.setattr(exporter, '_capture_png', cancel_capture)
    exporter.exportPng(view.rootObject(), 1.0)
    wait_until(lambda: not exporter.busy)
    assert not target.exists() and not view.rootObject().property('anonymousExport')
    assert not view.rootObject().property('capturingPng')
    monkeypatch.setattr(exporter, '_capture_png', original)
    exporter.exportPng(view.rootObject(), 1.0, False)
    exporter._png_ready(old_ids[0])
    wait_until(lambda: not exporter.busy)
    assert not exporter.isError and target.exists()
    assert not warnings, warnings


def test_write_failure_restores_anonymous_capture_state(exporter, monkeypatch):
    view, controller, exporter, series, target, warnings = exporter
    monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(target / 'unwritable.png'), 'PNG'))
    exporter.exportPng(view.rootObject(), 1.0)
    wait_until(lambda: not exporter.busy)
    assert exporter.isError
    assert not view.rootObject().property('anonymousExport')
    assert not warnings, warnings


def test_anonymous_png_rejects_late_burned_in_instance_and_preserves_existing_output(exporter):
    view, controller, exporter, series, target, warnings = exporter
    source = series.instances[-1].path
    ds = pydicom.dcmread(source)
    ds.BurnedInAnnotation = 'YES'
    ds.save_as(source, enforce_file_format=True)
    target.write_bytes(b'previous output')
    exporter.exportPng(view.rootObject(), 1.0)
    wait_until(lambda: not exporter.busy)
    assert exporter.isError and '烧录' in exporter.message
    assert target.read_bytes() == b'previous output'
    assert not view.rootObject().property('anonymousExport')


def test_current_dicom_anonymizes_all_instances_with_one_uid_map_and_rolls_back(tmp_path):
    series = make_series(tmp_path, 2)
    target = tmp_path / 'output'
    target.mkdir()
    originals = []
    for instance in series.instances:
        ds = pydicom.dcmread(instance.path)
        ds.PatientName = 'SECRET^NAME'
        ds.PatientID = 'SECRET-ID'
        ds.add_new((0x0011, 0x1010), 'LO', 'SECRET-PRIVATE')
        ds.save_as(instance.path, enforce_file_format=True)
        originals.append(instance.path.read_bytes())
    output, count = copy_dicom_series([series], target, anonymous=True)
    files = sorted(output.rglob('*.dcm'))
    assert count == 2 and len(files) == 2
    results = [pydicom.dcmread(path) for path in files]
    assert len({ds.SeriesInstanceUID for ds in results}) == 1
    for path, result, source in zip(files, results, series.instances):
        assert b'SECRET' not in path.read_bytes()
        assert result.PatientIdentityRemoved == 'YES'
        np.testing.assert_array_equal(result.pixel_array, pydicom.dcmread(source.path).pixel_array)
    assert [i.path.read_bytes() for i in series.instances] == originals
    ds = pydicom.dcmread(series.instances[-1].path)
    ds.BurnedInAnnotation = 'YES'
    ds.save_as(series.instances[-1].path, enforce_file_format=True)
    with pytest.raises(ValueError, match='烧录'):
        copy_dicom_series([series], target, anonymous=True)
    assert list(target.iterdir()) == [output]


from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click


def test_montage_anonymous_png_hides_details_without_changing_expanded_state(sidebar_scene, monkeypatch, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, '匿名平铺', 'montage')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    controller = ws.activeViewport
    wait_until(lambda: controller._active_request is None)
    click(window, find(window, 'primaryTool-export'))
    item = find(window, 'rightPanel').property('exportItem')
    details = find(window, 'montageDetails')
    assert controller.detailsExpanded and details.property('opacity') == 1
    identified = capture(item)
    item.setProperty('anonymousExport', True)
    expected = capture(item)
    assert details.property('opacity') == 0
    item.setProperty('anonymousExport', False)
    assert pixels(identified) != pixels(expected)
    target = tmp_path / 'montage-anonymous.png'
    monkeypatch.setattr('voxplane.ui.controller.export_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(target), 'PNG'))
    click(window, find(window, 'exportPng'))
    wait_until(lambda: not app.exportController.busy)
    assert not app.exportController.isError, app.exportController.message
    assert pixels(QImage(str(target))) == pixels(expected)
    assert controller.detailsExpanded and details.property('opacity') == 1
    assert not warnings, warnings


@pytest.mark.parametrize('anonymous', [True, False])
def test_png_excludes_pointer_over_image(exporter, anonymous):
    from PySide6.QtCore import QPoint
    from qt_pointer import move_pointer
    view, _, exporter, _, target, _ = exporter
    root = view.rootObject()
    glyph = next(i for i in _visual_children(root) if i.objectName() == 'viewportCustomCursor')
    move_pointer(view, QPoint(240, 250))
    move_pointer(view, QPoint(300, 320))
    wait_until(lambda: glyph.isVisible() and abs(glyph.x() - 298) < 1 and abs(glyph.y() - 318) < 1)
    def pointer_crop(image):
        ratio = image.width() / root.width()
        return pixels(image.copy(*(round(i * ratio) for i in (295, 315, 48, 42))))

    # Build the comparison from the same image with only its pointer hidden.
    glyph.setOpacity(0)
    root.setProperty('anonymousExport', anonymous)
    expected = pointer_crop(capture(root))
    root.setProperty('anonymousExport', False)
    glyph.setOpacity(1)
    QTest.qWait(35)
    assert pointer_crop(capture(root)) != expected
    exporter.exportPng(root, 1., anonymous)
    wait_until(lambda: not exporter.busy)
    assert not exporter.isError and glyph.isVisible() and glyph.opacity() == 1
    assert pointer_crop(QImage(str(target))) == expected
