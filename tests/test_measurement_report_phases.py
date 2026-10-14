"""Reports evaluate every saved region against its own temporal source."""
import csv
from dataclasses import replace

import pytest
from PySide6.QtPdf import QPdfDocument

from qt_dicom_viewer.core.measurement_report import COLUMNS
from qt_dicom_viewer.ui.controller.language_controller import LanguageController
from qt_dicom_viewer.ui.controller.measurement_report_controller import MeasurementReportController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, wait_until
from test_four_d_tools import temporal, draw


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as source:
        values = list(csv.reader(source))
    return [dict(zip((key for key, _ in COLUMNS), row)) for row in values[1:]]


@pytest.fixture
def english_report_language(qt_app):
    # This checks phase/data ownership independently of the offscreen platform's
    # CJK font inventory. Native Chinese PDF coverage lives in test_measurement_report_pdf.
    settings = SettingsController(path=False)
    settings.setValue('appearance', 'language', 'en-US')
    language = LanguageController(settings, root=False)
    try:
        yield language
    finally:
        language.shutdown()


@pytest.mark.parametrize('format', ['csv', 'pdf'])
def test_report_exports_regions_from_each_phase_without_changing_view(
        temporal, tmp_path, format, english_report_language):
    tab, requests, (_, workspace) = temporal
    first = draw(tab, 'segmentation')
    tab.setPhaseIndex(1)
    second = draw(tab, 'voi')
    controller = tab.voiController
    assert set(controller.evaluations) == {second}
    before = len(requests)
    volume = tab.activeViewport._voi_volume
    report = MeasurementReportController(workspace, workspace._series_catalog)
    target = tmp_path / ('phases.' + format)
    try:
        assert report.export_to(target, format=format), report.message
        wait_until(lambda: not report.busy)
        assert not report.isError, report.message
        if format == 'csv':
            rows = read_csv(target)
            assert [(r['phase'], r['mean']) for r in rows] == [('1', '10.00'), ('2', '20.00')]
            assert [r['threshold'] for r in rows] == ['5.00', '']
            assert all(int(r['pixel_count']) > 0 for r in rows)
        else:
            document = QPdfDocument()
            assert document.load(str(target)) == QPdfDocument.Error.None_
            text = '\n'.join(document.getAllText(i).text() for i in range(document.pageCount()))
            first_text, second_text = text.split('M001', 1)[1].split('M002', 1)
            assert 'Phase 1' in first_text and '10.00' in first_text
            assert 'Phase 2' in second_text and '20.00' in second_text
            document.close()
        assert tab.currentPhaseIndex == controller.phaseIndex == 1
        assert set(controller.evaluations) == {second}
        assert tab.activeViewport._voi_volume is volume
        assert len(requests) == before
        assert [r['id'] for r in controller.records] == [first, second]
    finally:
        report.shutdown()


def test_report_resolves_tab_phase_identifier_after_catalog_reordering(temporal, tmp_path):
    tab, _, (_, workspace) = temporal
    catalog = workspace._series_catalog
    uid = tab.activeViewport.viewport_config.series_uid
    series = catalog.get_series(uid)
    identifiers = (17, 29, 41)
    series = replace(series, phases=tuple(replace(phase, phase_identifier=identifier)
        for phase, identifier in zip(series.phases, identifiers)))
    catalog._series_by_uid[uid] = series
    tab._phase_identifiers = identifiers
    draw(tab, 'voi')
    tab.setPhaseIndex(1)
    draw(tab, 'voi')
    catalog._series_by_uid[uid] = replace(series, phases=(series.phases[2], *series.phases[:2]))
    report = MeasurementReportController(workspace, catalog)
    target = tmp_path / 'reordered.csv'
    try:
        assert report.export_to(target), report.message
        wait_until(lambda: not report.busy)
        assert not report.isError, report.message
        rows = read_csv(target)
        assert [(r['phase'], r['mean']) for r in rows] == [('2', '10.00'), ('3', '20.00')]
    finally:
        report.shutdown()


def test_pending_report_owns_masks_settings_and_catalog(temporal, tmp_path):
    import numpy as np
    from threading import Event
    from qt_dicom_viewer.core.segmentation_masks import mask_record

    tab, _, (_, workspace) = temporal
    controller = tab.voiController
    first = draw(tab, 'segmentation')
    record, result = mask_record(tab.activeViewport._voi_volume,
        np.ones((1, 1, 1), dtype=bool), (0, 0, 0), name='Segment', phase=0)
    controller.add_masks([record], {record['id']: result})
    tab.setPhaseIndex(1)
    draw(tab, 'voi')
    entered, release = Event(), Event()
    report = MeasurementReportController(workspace, workspace._series_catalog)
    target = tmp_path / 'frozen.csv'

    def block_worker():
        entered.set()
        assert release.wait(5)

    report._executor.submit(block_worker)
    try:
        wait_until(entered.is_set)
        assert report.export_to(target), report.message
        assert report.busy and not target.exists()
        # Mutate the old objects as well as removing them from the live tab.
        record['mask'][:] = False
        record['mask_affine'][:] = 0
        next(r for r in controller.records if r['id'] == first)['threshold'] = 100
        controller.records.clear()
        workspace._series_catalog._series_by_uid.clear()
        release.set()
        wait_until(lambda: not report.busy)
        assert not report.isError, report.message
        rows = read_csv(target)
        assert [(r['phase'], r['mean']) for r in rows] == [
            ('1', '10.00'), ('1', '10.00'), ('2', '20.00')]
        assert rows[0]['threshold'] == '5.00'
        assert rows[1]['pixel_count'] == '1'
    finally:
        release.set()
        report.shutdown()


def test_cancelled_phase_evaluation_preserves_existing_report(temporal, tmp_path, monkeypatch):
    from threading import Event, get_ident
    from qt_dicom_viewer.core.volume_manager import VolumeManager

    tab, _, (_, workspace) = temporal
    draw(tab, 'voi')
    tab.setPhaseIndex(1)
    draw(tab, 'voi')
    entered, release = Event(), Event()
    owner_thread = get_ident()
    original = VolumeManager.get_or_build

    def blocked(manager, series, phase_identifier=None):
        assert get_ident() != owner_thread, 'Report volume loading must run off the UI thread'
        entered.set()
        assert release.wait(5)
        return original(manager, series, phase_identifier)

    monkeypatch.setattr(VolumeManager, 'get_or_build', blocked)
    report = MeasurementReportController(workspace, workspace._series_catalog)
    target = tmp_path / 'existing.csv'
    target.write_bytes(b'previous report')
    try:
        assert report.export_to(target), report.message
        wait_until(entered.is_set)
        report.cancel()
        release.set()
        wait_until(lambda: not report.busy)
        assert not report.isError and not report.resultPath
        assert target.read_bytes() == b'previous report'
    finally:
        release.set()
        report.shutdown()
