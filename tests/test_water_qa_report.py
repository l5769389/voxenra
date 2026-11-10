from dataclasses import replace
import unicodedata

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtPdf import QPdfDocument

from test_dicom_tags import qt_app
from test_water_qa import water_image
from qt_dicom_viewer.core.water_qa import analyze_water_phantom
from qt_dicom_viewer.core.water_qa_report import pdf_bytes
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController


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


def test_report_contains_image_tables_and_no_default_brand(qt_app, tmp_path):
    result = analyze_water_phantom(water_image(), (1, 1))
    data = pdf_bytes(result, slice_number=26, spacing=(1, 1), screenshot=picture())
    doc, text = read_pdf(tmp_path, data)
    assert 'Voxenra' not in text
    assert not doc.metaData(QPdfDocument.MetaDataField.Creator)
    assert '/Subtype /Image' in data.decode('latin1')
    for label in ('ROI', '均值', 'SD', '26', 'HU', 'mm'):
        assert label in text
    rendered = doc.render(0, QSize(800, 1131))
    assert any(rendered.pixelColor(x, y).green() > 130 and rendered.pixelColor(x, y).red() < 70
               for x in range(70, 730, 20) for y in range(150, 650, 20))
    assert doc.pageCount() <= 2
    doc.close()


def test_custom_report_name_and_paginated_roi_tables(qt_app, tmp_path):
    result = analyze_water_phantom(water_image(), (1, 1))
    rois = tuple(replace(result.rois[0], key=f'roi-{i}', label=f'ROI {i:02}') for i in range(60))
    data = pdf_bytes(replace(result, rois=rois), slice_number=1, spacing=(1, 1),
                     screenshot=picture(), software_name='成像质量工作站')
    doc, text = read_pdf(tmp_path, data)
    assert '成像质量工作站' in text and 'Voxenra' not in text
    assert doc.metaData(QPdfDocument.MetaDataField.Creator) == '成像质量工作站'
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
def test_report_category_matches_title_metadata_and_roi_content(qt_app, tmp_path, kind):
    result = analyze_water_phantom(water_image(), (1, 1))
    air = replace(result.rois[0], key='air-1', label='Air sample', group='air',
                  mean_hu=-999, delta_center_hu=None)
    water = replace(result.rois[0], label='Water sample')
    result = replace(result, rois=(water, air))
    data = pdf_bytes(result, slice_number=26, spacing=(1, 1), screenshot=picture(), report_kind=kind)
    doc, text = read_pdf(tmp_path, data)
    title = '水模 QA 报告' if kind == 'water' else '模体外空气报告'
    assert ''.join(title.split()) in ''.join(text.split())
    assert doc.metaData(QPdfDocument.MetaDataField.Title) == title
    assert ('Water sample' in text) == (kind == 'water')
    assert ('Air sample' in text) == (kind == 'air')
    assert ('水 CT 值' in text) == (kind == 'water')
    if kind == 'air':
        assert 'Δ中心' not in text and '-999' in text
    doc.close()
