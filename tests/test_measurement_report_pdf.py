"""Native PDF exports preserve Chinese glyphs and each phase's data."""
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtPdf import QPdfDocument

from qt_dicom_viewer.core.measurement_report import pdf_bytes
from qt_dicom_viewer.i18n.messages import builtin
from test_dicom_tags import qt_app


@pytest.mark.skipif(os.environ.get('VOXENRA_NATIVE_QA') != '1'
                    or sys.platform not in ('darwin', 'win32'),
                    reason='Chinese PDF glyph coverage requires the native macOS or Windows font database')
def test_native_chinese_pdf_preserves_glyphs_and_phase_data(qt_app):
    assert QGuiApplication.platformName() == ('cocoa' if sys.platform == 'darwin' else 'windows')
    rows = [
        dict(patient='患者 1', series='序列 1', modality='CT', view='3D 体积',
             id='M001', kind='分割', phase=1, mean=10, std=0, volume_cm3=.01,
             pixel_count=12, unit='HU'),
        dict(patient='患者 1', series='序列 1', modality='CT', view='3D 体积',
             id='M002', kind='体积', phase=2, mean=20, std=0, volume_cm3=.02,
             pixel_count=18, unit='HU'),
    ]
    output = Path('build/test-results/native-pdf')
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'chinese-phases.pdf'
    target.write_bytes(pdf_bytes(rows, translations=builtin('zh-CN')['messages'],
                                 created='2026-10-14 00:00'))
    document = QPdfDocument()
    try:
        assert document.load(str(target)) == QPdfDocument.Error.None_
        texts = []
        for page in range(document.pageCount()):
            rendered = document.render(page, QSize(1190, 1684))
            assert not rendered.isNull()
            # QPdfDocument renders onto transparency; composite for a readable
            # diagnostic PNG, including when the later text assertion fails.
            image = QImage(rendered.size(), QImage.Format_RGB32)
            image.fill(QColor('white'))
            painter = QPainter(image)
            painter.drawImage(0, 0, rendered)
            painter.end()
            assert image.save(str(output / f'chinese-phases-{page + 1}.png'))
            texts.append(document.getAllText(page).text())
        text = '\n'.join(texts)
        (output / 'chinese-phases.txt').write_text(text, encoding='utf-8')
        for label in ('测量结果', '患者 1', '序列 1', '体积 cm³', '均值', '强度单位'):
            assert label in text, f'Missing Chinese label {label!r}: {text!r}'
        first, second = text.split('M001', 1)[1].split('M002', 1)
        assert '时相 1' in first and '均值: 10.00' in first
        assert '体积 cm³: 0.01' in first and ': 12' in first
        assert '时相 2' in second and '均值: 20.00' in second
        assert '体积 cm³: 0.02' in second and ': 18' in second
        assert '强度单位: HU' in first and '强度单位: HU' in second
    finally:
        document.close()
