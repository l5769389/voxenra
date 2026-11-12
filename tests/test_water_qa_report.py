from dataclasses import replace
import unicodedata

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtPdf import QPdfDocument

from test_dicom_tags import qt_app
from test_water_qa import water_image
from voxplane.core.water_qa import analyze_water_phantom
from voxplane.core.water_qa_report import pdf_bytes
from voxplane.ui.controller.settings_controller import SettingsController
from pdf_test_support import report_language  # register bilingual PDF fixture


def picture():
    image = QImage(640, 400, QImage.Format_RGB32)
    image.fill(QColor('#25b59b'))
    return image


def read_pdf(tmp_path, data):
    path = tmp_path / 'report.pdf'
    path.write_bytes(data)
    doc = QPdfDocument()
    assert doc.load(str(path)) == QPdfDocument.Error.None_
    text = unicodedata.normalize('NFKC', '\n'.join(doc.getAllText(i).text() for i in range(doc.pageCount())))
    return doc, text


def test_report_contains_image_tables_and_no_default_brand(qt_app, tmp_path, report_language):
    language, translations = report_language
    result = analyze_water_phantom(water_image(), (1, 1))
    data = pdf_bytes(result, slice_number=26, spacing=(1, 1), screenshot=picture(), translations=translations)
    doc, text = read_pdf(tmp_path, data)
    assert 'VoxPlane' not in text
    assert not doc.metaData(QPdfDocument.MetaDataField.Creator)
    assert '/Subtype /Image' in data.decode('latin1')
    for label in ('ROI', '均值' if language == 'zh-CN' else 'Mean', 'SD', '26', 'HU', 'mm'):
        assert label in text
    rendered = doc.render(0, QSize(800, 1131))
    assert any(rendered.pixelColor(x, y).green() > 130 and rendered.pixelColor(x, y).red() < 70
               for x in range(70, 730, 20) for y in range(150, 650, 20))
    assert doc.pageCount() <= 2
    doc.close()


def test_custom_report_name_and_paginated_roi_tables(qt_app, tmp_path, report_language):
    language, translations = report_language
    software_name = '成像质量工作站' if language == 'zh-CN' else 'Imaging QA Workstation'
    result = analyze_water_phantom(water_image(), (1, 1))
    rois = tuple(replace(result.rois[0], key=f'roi-{i}', label=f'ROI {i:02}') for i in range(60))
    data = pdf_bytes(replace(result, rois=rois), slice_number=1, spacing=(1, 1),
                     screenshot=picture(), software_name=software_name, translations=translations)
    doc, text = read_pdf(tmp_path, data)
    assert software_name in text and 'VoxPlane' not in text
    assert doc.metaData(QPdfDocument.MetaDataField.Creator) == software_name
    assert doc.pageCount() > 2 and 'ROI 59' in text
    for i in range(1, doc.pageCount()):
        assert 'ROI' in ''.join(doc.getAllText(i).text().split())  # PDF text runs may split glyphs.
    doc.close()


def test_report_rejects_missing_screenshot(qt_app):
    result = analyze_water_phantom(water_image(), (1, 1))
    with pytest.raises(ValueError):
        pdf_bytes(result, slice_number=1, spacing=(1, 1), screenshot=QImage())


def test_report_name_is_optional_validated_and_persisted(qt_app, tmp_path):
    path = tmp_path / 'settings.json'
    settings = SettingsController(path=path)
    assert settings.section('export')['reportSoftwareName'] == ''
    assert settings.setValue('export', 'reportSoftwareName', '  质量工作站  ')
    assert SettingsController(path=path).section('export')['reportSoftwareName'] == '质量工作站'
    for invalid in ('x'*81, 'bad\nname', 'bad\x00name', 42):
        assert not settings.setValue('export', 'reportSoftwareName', invalid)
    assert settings.setValue('export', 'reportSoftwareName', '')


@pytest.mark.parametrize('kind', ['water', 'air'])
def test_report_category_matches_title_metadata_and_roi_content(qt_app, tmp_path, kind, report_language):
    language, translations = report_language
    result = analyze_water_phantom(water_image(), (1, 1))
    air = replace(result.rois[0], key='air-1', label='Air sample', group='air',
                  mean_hu=-999, delta_center_hu=None)
    water = replace(result.rois[0], label='Water sample')
    result = replace(result, rois=(water, air))
    data = pdf_bytes(result, slice_number=26, spacing=(1, 1), screenshot=picture(), report_kind=kind,
                     translations=translations)
    doc, text = read_pdf(tmp_path, data)
    title = ('水模 QA 报告' if kind == 'water' else '模体外空气报告') if language == 'zh-CN' else (
        'Water Phantom QA Report' if kind == 'water' else 'Phantom Exterior Air Report')
    assert ''.join(title.split()) in ''.join(text.split())
    assert doc.metaData(QPdfDocument.MetaDataField.Title) == title
    assert ('Water sample' in text) == (kind == 'water')
    assert ('Air sample' in text) == (kind == 'air')
    assert (('水 CT 值' if language == 'zh-CN' else 'Water CT number') in text) == (kind == 'water')
    if kind == 'air':
        assert ('Δ中心' if language == 'zh-CN' else 'ΔCenter') not in text and '-999' in text
    doc.close()


@pytest.mark.parametrize('precision, values', [
    (2, ('12.35', '2.35', '-3.46', '45.68', '6.79', '23.46', '34.57', '9.88', '76.54')),
    (3, ('12.346', '2.346', '-3.457', '45.679', '6.789', '23.457', '34.568', '9.876', '76.543')),
])
def test_report_numeric_values_stay_associated_with_labels_and_units(qt_app, tmp_path, precision, values):
    from voxplane.model.water_qa import WaterPhantom, WaterQaSettings, WaterQaRoi, WaterQaResult
    from voxplane.i18n.messages import builtin
    roi = WaterQaRoi('probe', 'Probe', 23.4567, 34.5678, 4.938, 57, 76.5432,
                     12.3456, 2.3456, -3.4567, 45.6789, 6.7891)
    missing = replace(roi, key='missing', label='Missing', delta_center_hu=None)
    result = WaterQaResult(WaterPhantom(80, 90, 50.125, 1), WaterQaSettings(),
                           (roi, missing), 1.125, 2.25, 3.375, 4.5, 5.625, 6.75, 7.875,
                           noise_percent=8.125)
    doc, text = read_pdf(tmp_path, pdf_bytes(result, slice_number=26, spacing=(.625, .875),
                         screenshot=picture(), decimal_places=precision,
                         translations=builtin('en-US')['messages']))
    compact = ''.join(text.split())
    # Explicit references: no formatter or result-analysis helper builds expectations.
    summary = [('WaterCTnumber', '1.12', '1.125', 'HU'),
               ('NoiseSD', '2.25', '2.250', 'HU'),
               ('Noise', '8.12', '8.125', '%'),
               ('Uniformity', '3.38', '3.375', 'HU'),
               ('Consistency', '4.50', '4.500', 'HU'),
               ('Horizontaldifference', '5.62', '5.625', 'HU'),
               ('Verticaldifference', '6.75', '6.750', 'HU'),
               ('Noiserange', '7.88', '7.875', 'HU')]
    for label, two, three, unit in summary:
        assert label + (two if precision == 2 else three) + unit in compact
    mean, sd, minimum, maximum, delta, x, y, diameter, area = values
    assert 'Probe' + mean + sd + minimum + maximum + '57' + delta in compact
    assert 'Missing' + mean + sd + minimum + maximum + '57—' in compact
    assert 'Probe/CTnumberanduniformity' + x + y + diameter + area in compact
    assert 'MeanHUSDHUMinimumHU' in compact
    assert 'MaximumHUPixelsΔcenterHU' in compact
    assert 'XpxYpxDiametermmSampledareamm2' in compact
    assert ('Pixelspacing(row×column):0.62×0.88mm' if precision == 2 else 'Pixelspacing(row×column):0.625×0.875mm') in compact
    assert ('Waterphantomdiameter:100.25mm' if precision == 2 else 'Waterphantomdiameter:100.250mm') in compact
    doc.close()
