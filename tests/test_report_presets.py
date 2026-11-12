from pathlib import Path
import pytest
from PySide6.QtPdf import QPdfDocument
from PySide6.QtCore import QUrl
from voxplane.core.report_options import DEFAULTS, validate_options
from voxplane.core.measurement_report import pdf_bytes
from voxplane.ui.controller.report_preview_controller import ReportPreviewController
from test_dicom_tags import qt_app


def test_options_reject_identity_and_invalid_types():
    assert validate_options({}) == DEFAULTS
    for values in ({'title': 'Patient X'}, {'imageColumns': True}, {'orientation': 'x'}, {'anonymous': 1}):
        with pytest.raises(ValueError):
            validate_options(values)


def test_pdf_frozen_preview_and_layout(qt_app, tmp_path):
    rows = [dict(patient='P1', series='S1', modality='CT', view='2D', id='M001', kind='ROI', mean=23.45, std=0, unit='HU')]
    options = dict(DEFAULTS, orientation='landscape', fontSize='large')
    data = pdf_bytes(rows, options=options, content={'title':'Frozen report', 'notes':'Example note'})
    preview = ReportPreviewController()
    assert preview.set_pdf(data)
    rows[0]['mean'] = 999
    dest = tmp_path/'report.pdf'
    assert preview.save_to(dest)
    assert dest.read_bytes() == data
    doc = QPdfDocument()
    assert doc.load(str(dest)) == QPdfDocument.Error.None_
    text = ''.join(doc.getAllText(p).text() for p in range(doc.pageCount()))
    assert '23.45' in text and '999' not in text and 'HU' in text
    assert 'VoxPlane' not in text and 'Frozen report' in text and 'Example note' in text
    assert doc.pagePointSize(0).width() > doc.pagePointSize(0).height()
    image_paths = [Path(QUrl(p).toLocalFile()) for p in preview.pages]
    assert image_paths and all(p.exists() for p in image_paths)
    preview.clear()
    assert not any(p.exists() for p in image_paths)
    assert not preview.save_to(tmp_path/'cancel.pdf')
    doc.close()


def test_preview_releases_pdf_reader_before_notifying_or_cleanup(qt_app):
    preview = ReportPreviewController()
    readers_at_notification = []
    preview.changed.connect(lambda: readers_at_notification.append(
        len(preview.findChildren(QPdfDocument))))
    try:
        assert preview.set_pdf(pdf_bytes([]))
        assert not preview.findChildren(QPdfDocument)
        assert readers_at_notification and not any(readers_at_notification)
        assert not preview.set_pdf(b'not a PDF')
        assert not preview.findChildren(QPdfDocument)
        assert not any(readers_at_notification)
    finally:
        preview.clear()

@pytest.mark.parametrize('kind', ['measurement', 'qa'])
def test_long_report_content_wraps_without_truncation(qt_app, tmp_path, kind):
    from voxplane.i18n.messages import builtin
    content = {'title': 'Example report', 'operator': 'Alice', 'reviewer': 'Bob',
               'notes': 'STARTMARK ' + 'Long note with spaces 中文说明 ' * 120 + ' ENDMARK',
               'conclusion': 'FINALMARK'}
    options = dict(DEFAULTS, fontSize='large', orientation='landscape', includeImages=False)
    translations = builtin('en-US')['messages']
    if kind == 'measurement':
        data = pdf_bytes([], options=options, content=content, translations=translations)
    else:
        from test_water_qa_report import water_image
        from voxplane.core.water_qa import analyze_water_phantom
        from voxplane.core.water_qa_report import pdf_bytes as qa_pdf
        data = qa_pdf(analyze_water_phantom(water_image(), (1, 1)), slice_number=1,
                      spacing=(1, 1), screenshot=None, options=options, content=content, translations=translations)
    dest = tmp_path/'long.pdf'; dest.write_bytes(data)
    doc = QPdfDocument(); doc.load(str(dest))
    text = ''.join(doc.getAllText(p).text() for p in range(doc.pageCount()))
    assert doc.pageCount() > 1
    for marker in ('STARTMARK', 'ENDMARK', 'FINALMARK', 'Operator: Alice', 'Reviewer: Bob'):
        assert ''.join(marker.split()) in ''.join(text.split())
    doc.close()


def test_default_pdf_has_no_brand_in_text_or_metadata(qt_app, tmp_path):
    from voxplane.i18n.messages import builtin
    for language in ('en-US', 'zh-CN'):
        path = tmp_path/(language+'.pdf')
        path.write_bytes(pdf_bytes([], translations=builtin(language)['messages']))
        doc = QPdfDocument(); doc.load(str(path))
        assert 'VoxPlane' not in doc.getAllText(0).text()
        assert 'VoxPlane' not in doc.metaData(QPdfDocument.MetaDataField.Title)
        assert doc.metaData(QPdfDocument.MetaDataField.Creator) == ''
        doc.close()


def test_current_study_filter_and_changed_selection_rejected(qt_app, monkeypatch):
    from types import SimpleNamespace
    from voxplane.ui.controller import measurement_report_controller as module
    workspace = SimpleNamespace(activeViewport=SimpleNamespace(viewport_config=SimpleNamespace(series_uid='S1')))
    catalog = SimpleNamespace(get_series=lambda uid: SimpleNamespace(study_instance_uid='study1'))
    controller = module.MeasurementReportController(workspace, catalog)
    rows = [dict(id='M001', _study_uid='study1', _patient_key=('P1',), patient='P1', series='S1', kind='ROI', view='2D'),
            dict(id='M002', _study_uid='study2', _patient_key=('P1',), patient='P1', series='S2', kind='ROI', view='2D')]
    monkeypatch.setattr(module, 'capture_results', lambda *a, **kw: (rows, [], set()))
    try:
        assert [r['id'] for r in controller.availableResults(True, True)] == ['M001']
        rows[0]['view'] = 'Changed'
        assert not controller.export_to(None, format='pdf', selected_ids=['M001'], current_study=True)
        assert controller.isError and not controller.busy
        assert not controller.previewController.ready
    finally:
        controller.shutdown()


def test_cancel_prevents_late_preview_signal(qt_app):
    from voxplane.ui.controller.measurement_report_controller import MeasurementReportController
    controller = MeasurementReportController(None, None)
    try:
        data = pdf_bytes([])
        controller.cancelPreview()
        controller._accept_preview(data)
        assert not controller.previewController.ready
    finally:
        controller.shutdown()


def test_signature_limit_preserves_legacy_contract():
    assert validate_options({'softwareName': 'x'*80})['softwareName'] == 'x'*80
    assert validate_options({'organization': 'x'*120})['organization'] == 'x'*120
    for value in ('x'*81, 'name\x7f'):
        with pytest.raises(ValueError):
            validate_options({'softwareName': value})


@pytest.mark.parametrize('language_code', ['en-US', 'zh-CN'])
@pytest.mark.parametrize('kind,filename', [('water', 'Water-QA-slice-012.pdf'), ('air', 'Air-QA-slice-012.pdf'), ('measurement', 'Measurements.pdf')])
def test_preview_picker_uses_frozen_report_filename(qt_app, tmp_path, monkeypatch, kind, filename, language_code):
    from voxplane.ui.controller.measurement_report_controller import MeasurementReportController
    from voxplane.ui.controller.viewport.controller.water_qa_controller import WaterQaController
    from voxplane.ui.controller.settings_controller import SettingsController
    from voxplane.ui.controller.language_controller import LanguageController
    from voxplane.i18n.widgets import QFileDialog
    from types import SimpleNamespace
    settings = SettingsController(path=False)
    settings.setValue('appearance', 'language', language_code)
    if kind == 'measurement' and language_code == 'zh-CN': filename = '测量结果.pdf'
    settings.setValue('export', 'directory', str(tmp_path))
    language = LanguageController(settings, root=False)
    data = pdf_bytes([])
    suggested = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: suggested.append(args[2]) or ('', ''))
    report = MeasurementReportController(None, None)
    report._settings_controller = settings
    try:
        if kind == 'measurement':
            report._accept_preview(data)
        else:
            from voxplane.core import water_qa_report
            monkeypatch.setattr(water_qa_report, 'pdf_bytes', lambda **kwargs: data)
            qa = SimpleNamespace(_preview=report.previewController, _settings_controller=settings)
            WaterQaController._show_report_preview(qa, {'report_kind': kind, 'slice_number': 12})
        assert report.previewController.ready
        settings.setValue('export', 'directory', str(tmp_path/'changed-after-preview'))
        assert not report.previewController.save()
        assert suggested == [str(tmp_path/filename)]
    finally:
        report.shutdown()
        language.shutdown()


@pytest.mark.parametrize('key,value', [
    ('orientation','landscape'),('fontSize','large'),('pageNumbers',False),
    ('organization','Example Hospital'),('department','Imaging'),('softwareName','QA Desk'),
    ('tableDetail','detailed'),('imageColumns',2),('anonymous',False),('includeImages',False)])
def test_each_report_setting_changes_rendered_output(qt_app,tmp_path,key,value):
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QSize
    from voxplane.i18n.messages import builtin
    rows=[dict(patient='DEMO',series='Example',modality='CT',view='2D',id='M1',kind='ROI',
               mean=32.5,unit='HU',origin=(1,2,3))]
    image=QImage(200,100,QImage.Format_RGB32);image.fill(0xff77aa33)
    def rendered(options,name):
        path=tmp_path/name
        path.write_bytes(pdf_bytes(rows,options=options,images=[('A',image),('B',image)],created='2026-11-12',translations=builtin('en-US')['messages']))
        doc=QPdfDocument();assert doc.load(str(path))==QPdfDocument.Error.None_
        pages=[]
        for i in range(doc.pageCount()):
            pixels=doc.render(i,QSize(600,800)).convertToFormat(QImage.Format_RGB32)
            pages.append(bytes(pixels.constBits()))
        doc.close();return pages
    assert rendered(DEFAULTS,'base.pdf')!=rendered(dict(DEFAULTS,**{key:value}),'changed.pdf')
