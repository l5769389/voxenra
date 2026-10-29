from test_cpr_persistence import cpr_app, qt_app
from test_dicom_tags import wait_until
from pathlib import Path
import pydicom
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider


def test_export_is_disabled_for_draft_preview_and_pending_reconstruction(cpr_app):
    app, tab, _ = cpr_app
    tab.activateViewport(tab.viewForRole('curved').viewportId)
    export = app.exportController
    assert export.canExportPng
    tab.startPath()
    assert not export.canExportPng
    tab.cancel_operation()
    assert export.canExportPng
    view = tab.viewForRole('reference-a')
    view.cprBeginDrag(20, 35, 1)
    view.cprMoveDrag(25, 30)
    assert not export.canExportPng
    view.cprEndDrag(25, 30)
    assert not export.canExportPng
    wait_until(lambda: tab.ready)
    assert export.canExportPng


def test_export_scope_selects_required_view_and_restores_combined_layout(cpr_app):
    _, tab, _ = cpr_app
    tab.focusSingleViewport(tab.viewForRole('reference-a').viewportId)
    tab.setExportScope('cross')
    assert tab.activeViewport.viewportRole == 'cross'
    assert tab.focusedViewportId == tab.activeViewport.viewportId
    tab.setExportScope('combined')
    assert tab.exportScope == 'combined'
    assert not tab.focusedViewportId


def test_three_scopes_write_real_anonymous_pngs_and_reject_changed_scope(cpr_app, tmp_path, monkeypatch):
    app, tab, record = cpr_app
    for instance in record.instances:
        dataset = pydicom.dcmread(instance.path)
        dataset.BurnedInAnnotation = 'NO'
        dataset.save_as(instance.path, enforce_file_format=True)
    window = QQuickView()
    provider = DicomImageProvider()
    tab.imageUpdateRequested.connect(provider.set_array)
    for viewport in tab.viewports_by_id.values():
        viewport.refresh_window_image()
    warnings = []
    window.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window.engine().addImageProvider('dicom', provider)
    window.engine().addImageProvider('navigation', SvgIconProvider())
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.resize(1000, 700)
    window.setInitialProperties(dict(controller=tab))
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/
        'src/qt_dicom_viewer/qml/sections/center/viewportArea/CprPage.qml')))
    assert window.status() == QQuickView.Ready
    window.show()
    QTest.qWait(80)
    target = tmp_path/'initial.png'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.export_controller.QFileDialog.getSaveFileName',
                        lambda *args, **kwargs: (str(target), 'PNG (*.png)'))
    images = {}
    try:
        for scope in ('curved', 'cross', 'combined'):
            tab.setExportScope(scope)
            QTest.qWait(30)
            target = tmp_path/(scope+'.png')
            item = window.rootObject().activeExportItem()
            assert item is not None and item.isVisible()
            app.exportController.exportPng(item, 1., True)
            wait_until(lambda: not app.exportController.busy)
            assert target.exists(), app.exportController.message
            image = QImage(str(target))
            assert not image.isNull() and not image.textKeys()
            images[scope] = image
            assert not window.rootObject().property('anonymousExport')
        assert images['combined'].size().width() == 1000
        assert images['combined'].size().height() == 700
        assert images['curved'].width() < images['combined'].width()
        assert images['curved'] != images['cross']
        target = tmp_path/'stale.png'
        app.exportController.exportPng(window.rootObject().activeExportItem(), 1., True)
        tab.setExportScope('cross')
        wait_until(lambda: not app.exportController.busy)
        assert not target.exists()
        assert not warnings, '\n'.join(warnings)
    finally:
        window.hide()
        delete(window)
