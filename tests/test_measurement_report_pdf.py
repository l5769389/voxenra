"""Native PDF semantic checks and visible/distinct Chinese glyph smoke guard.

This catches blank/tofu glyphs; typography still needs native visual review.
"""
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtPdf import QPdfDocument

from voxplane.core.measurement_report import pdf_bytes
from voxplane.i18n.messages import builtin
from test_dicom_tags import qt_app


def _assert_visible_distinct_glyphs(crops):
    """Reject blank rendering and a repeated missing-glyph box."""
    masks = []
    for crop in crops:
        assert not crop.isNull()
        normalized = crop.scaled(24, 24)
        mask = tuple(normalized.pixelColor(x, y).lightness() < 180
                     for y in range(24) for x in range(24))
        assert sum(mask) >= 15, "Chinese glyph has no visible ink"
        masks.append(mask)
    assert len(masks) == 4
    # Four different title characters must not all render as the same tofu box.
    assert all(sum(a != b for a, b in zip(masks[0], mask)) >= 15
               for mask in masks[1:]), "Chinese glyphs render as repeated boxes"


@pytest.mark.parametrize("blank", [True, False])
def test_glyph_guard_rejects_blank_or_repeated_boxes(blank):
    image = QImage(24, 24, QImage.Format_RGB32)
    image.fill(QColor('white'))
    if not blank:
        painter = QPainter(image)
        painter.drawRect(3, 3, 17, 17)
        painter.end()
    with pytest.raises(AssertionError, match="no visible ink|repeated boxes"):
        _assert_visible_distinct_glyphs([image] * 4)


@pytest.mark.skipif(os.environ.get('VOXPLANE_NATIVE_QA') != '1'
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
            page_text = document.getAllText(page).text()
            texts.append(page_text)
            if page == 0:
                start = page_text.index('测量结果')
                page_size = document.pagePointSize(page)
                crops = []
                for offset in range(4):
                    selection = document.getSelectionAtIndex(page, start + offset, 1)
                    assert selection.isValid()
                    assert selection.text() == '测量结果'[offset]
                    rect = selection.boundingRectangle()
                    from PySide6.QtCore import QRectF
                    raster_rect = QRectF(rect.x() * image.width() / page_size.width(),
                                         rect.y() * image.height() / page_size.height(),
                                         rect.width() * image.width() / page_size.width(),
                                         rect.height() * image.height() / page_size.height())
                    crops.append(image.copy(raster_rect.toAlignedRect()))
                _assert_visible_distinct_glyphs(crops)
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
