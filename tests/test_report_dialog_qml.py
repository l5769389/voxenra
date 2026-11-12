from pathlib import Path
import pytest
from PySide6.QtCore import QUrl, QMetaObject, QPointF
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app
from test_pacs_qml import scene
from voxplane.core.measurement_report import pdf_bytes


@pytest.mark.parametrize('theme', ['dark', 'light', 'graphite'])
@pytest.mark.parametrize('width', [540, 1000])
def test_report_dialog_preview_save_cancel(scene, tmp_path, theme, width):
    window, app, warnings = scene
    app.settingsController.setValue('appearance', 'theme', theme)
    engine = QQmlEngine.contextForObject(window).engine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(Path('src/voxplane/qml/sections/right/panels/ReportDialog.qml').resolve())))
    assert not component.isError(), component.errors()
    report = app.exportController.measurementReport
    dialog = component.createWithInitialProperties(dict(reportController=report, settingsController=app.settingsController, parent=window.contentItem()))
    assert dialog, component.errors()
    dialog.setProperty('width', width)
    dialog.setProperty('height', 700)
    QMetaObject.invokeMethod(dialog, 'open')
    QTest.qWait(80)
    data = pdf_bytes([dict(patient='P', series='S', modality='CT', view='2D', id='M001', kind='ROI', mean=12.34, unit='HU')])
    assert report.previewController.set_pdf(data)
    QTest.qWait(80)
    assert dialog.property('visible')
    from test_tag_qml import descendants
    options = next(i for i in descendants(dialog.property('contentItem')) if i.objectName() == 'reportOptionsScroll')
    assert options.isVisible() is (width >= 650)
    footer = dialog.property('footer')
    for button in descendants(footer):
        if button.property('minimumButtonWidth') is None:
            continue
        if button.property('text') is not None and button.isVisible():
            assert button.width() > 0
            point = button.mapToItem(footer, QPointF())
            assert point.x() >= 15 and point.y() >= 15
            assert point.x()+button.width() <= footer.width()-15
            assert point.y()+button.height() <= footer.height()-15
    assert report.previewController.save_to(tmp_path/'preview.pdf')
    assert (tmp_path/'preview.pdf').read_bytes() == data
    assert window.grabWindow().save(str(tmp_path/f'report-{theme}-{width}.png'))
    report.previewController.clear()
    QTest.qWait(30)
    assert options.isVisible()
    QMetaObject.invokeMethod(dialog, 'close')
    QTest.qWait(80)
    assert not report.previewController.ready
    dialog.deleteLater()
    QTest.qWait(20)
    assert not warnings, warnings


@pytest.mark.parametrize('qa',[True,False])
def test_image_columns_only_visible_for_measurement_report(scene,qa):
    from test_tag_qml import descendants
    window,app,warnings=scene
    engine=QQmlEngine.contextForObject(window).engine()
    component=QQmlComponent(engine,QUrl.fromLocalFile(str(Path('src/voxplane/qml/sections/right/panels/ReportDialog.qml').resolve())))
    dialog=component.createWithInitialProperties(dict(reportController=app.exportController.measurementReport,
        settingsController=app.settingsController,parent=window.contentItem(),qa=qa))
    QMetaObject.invokeMethod(dialog,'open');QTest.qWait(60)
    content=dialog.property('contentItem')
    control=next(i for i in descendants(content) if i.objectName()=='reportOption_imageColumns')
    assert control.isVisible() is (not qa)
    QMetaObject.invokeMethod(dialog,'close');dialog.deleteLater();QTest.qWait(20)
    assert not warnings,warnings
