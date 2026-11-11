"""Display precision is persistent, shared and never mutates measured data."""
import csv
import io
import json
import math

import pytest
from PySide6.QtPdf import QPdfDocument

from voxplane.core.measurement_format import format_measurement
from voxplane.core.measurement_report import csv_bytes, pdf_bytes, COLUMNS
from voxplane.settings.preferences import normalize_settings
from voxplane.ui.controller.settings_controller import SettingsController
from voxplane.ui.controller.viewport.controller.measure.measure_controller import MeasurementController
from test_dicom_tags import qt_app
from test_measurement_controller import _context, _position, _drag
from test_mpr_voi_controller import setup_voi, draw
from test_mpr_voi_qml import settle


@pytest.mark.parametrize("value, places, expected", [
    (12.3456, 0, "12"), (12.3456, 1, "12.3"), (12.3456, 2, "12.35"), (12.3456, 3, "12.346"),
    (1200, 2, "1200.00"), (0.0004, 3, "0.000"), (-0.0004, 3, "0.000"),
    (-12.3456, 2, "-12.35"), (2.125, 2, "2.12"), (None, 2, "—"),
    (math.nan, 2, "—"), (math.inf, 3, "—"),
])
def test_result_formatting_handles_large_small_signed_and_missing_values(value, places, expected):
    assert format_measurement(value, places) == expected


def test_precision_migrates_validates_persists_and_resets_only_measurement(tmp_path):
    path = tmp_path / "display.json"
    path.write_text(json.dumps({"measurement": {"lineWidth": 4}, "roi": {"mean": False}}))
    settings = SettingsController(path=path)
    assert settings.values["measurement"]["decimalPlaces"] == 2
    for places in range(4):
        assert settings.setValue("measurement", "decimalPlaces", places)
        assert SettingsController(path=path).values["measurement"]["decimalPlaces"] == places
    saved = path.read_bytes()
    for invalid in (-1, 4, 1.5, True, "2", math.nan, math.inf, None):
        assert not settings.setValue("measurement", "decimalPlaces", invalid)
        assert path.read_bytes() == saved
        assert normalize_settings({"measurement": {"decimalPlaces": invalid}})["measurement"]["decimalPlaces"] == 2
    assert settings.resetSection("measurement")
    assert settings.values["measurement"]["decimalPlaces"] == 2
    assert not settings.values["roi"]["mean"]


def test_precision_change_updates_draft_and_commit_without_rounding_geometry():
    controller = MeasurementController()
    start, end = _position(0, 0), _position(12.3456, 0)
    controller.begin(start, _context())
    controller.update(_drag(start, end))
    assert controller.activeTransaction["label"] == "12.35 mm"
    notices = []
    controller.activeTransactionChanged.connect(lambda: notices.append(1))
    assert controller.settingsController.setValue("measurement", "decimalPlaces", 3)
    assert controller.activeTransaction["label"] == "12.346 mm" and notices
    controller.end(end)
    raw = controller.committed_measurements
    assert raw[0].length_mm == 12.3456
    controller.settingsController.setValue("measurement", "decimalPlaces", 0)
    assert controller.measurementItems[0]["label"] == "12 mm"
    controller.settingsController.setValue("measurement", "decimalPlaces", 2)
    assert controller.measurementItems[0]["label"] == "12.35 mm"
    assert controller.committed_measurements == raw
    assert controller.selectedMeasurementId == raw[0].measurement_id


@pytest.mark.parametrize("places, expected", [(0, "12"), (1, "12.3"), (2, "12.35"), (3, "12.346")])
def test_csv_pdf_use_same_precision_and_keep_counts_and_missing_values(qt_app, tmp_path, places, expected):
    row = dict(patient="Demo", series="Series", modality="MR", view="Axial", id="M001", kind="ROI",
               length_mm=12.3456, mean=12.3456, minimum=12, std=None, pixel_count=123, slice=4,
               threshold=-0.0001, angle_deg=math.nan)
    original = dict(row)
    data = csv_bytes([row], decimal_places=places)
    values = next(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    ordered = list(values.values())
    indexed = dict(zip((key for key, _ in COLUMNS), ordered))
    assert indexed["length_mm"] == indexed["mean"] == expected
    assert indexed["minimum"] == ("12" if places == 0 else "12." + "0" * places)
    assert indexed["pixel_count"] == "123" and indexed["slice"] == "4"
    assert indexed["std"] == indexed["angle_deg"] == ""
    assert not indexed["threshold"].startswith("-")
    path = tmp_path / "measurement.pdf"
    path.write_bytes(pdf_bytes([row], decimal_places=places))
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    text = document.getAllText(0).text()
    assert expected in text and "123" in text
    assert "12.3456" not in text
    document.close()
    assert row == original


def test_voi_precision_refreshes_results_without_recalculating_volume(setup_voi):
    controller, viewport, tools = setup_voi
    draw(controller, viewport)
    settle(controller)
    original = controller.evaluations[controller.selectedId]
    assert controller.selected["metrics"][0]["value"] == "500.00"
    notifications = []
    controller.changed.connect(lambda: notifications.append(1))
    tools.settingsController.setValue("measurement", "decimalPlaces", 3)
    assert controller.selected["metrics"][0]["value"] == "500.000" and notifications
    assert controller.evaluations[controller.selectedId] is original
    assert not controller.busy
    assert controller.selected["metrics"][-1]["value"] == str(original.metrics["count"])


def test_mtf_units_migrate_validate_persist_and_reset(tmp_path):
    path = tmp_path / "mtf-settings.json"
    path.write_text(json.dumps({"measurement": {"decimalPlaces": 3}, "roi": {"mean": False}}))
    settings = SettingsController(path=path)
    assert settings.values["services"]["mtfFrequencyUnit"] == "lp/mm"
    assert settings.setValue("services", "mtfFrequencyUnit", "lp/cm")
    assert SettingsController(path=path).values["services"]["mtfFrequencyUnit"] == "lp/cm"
    saved = path.read_bytes()
    for invalid in (None, True, 10, "Hz", "lp/m", [], {}):
        assert not settings.setValue("services", "mtfFrequencyUnit", invalid)
        assert path.read_bytes() == saved
        assert normalize_settings({"measurement": {"mtfFrequencyUnit": invalid}})["services"]["mtfFrequencyUnit"] == "lp/mm"
    assert settings.values["measurement"]["decimalPlaces"] == 3
    assert settings.resetSection("services")
    assert settings.values["services"]["mtfFrequencyUnit"] == "lp/mm"
    assert not settings.values["roi"]["mean"]


def test_ramp_angle_persists_and_validates_without_changing_frequency_unit(tmp_path):
    path = tmp_path / 'ramp-settings.json'
    settings = SettingsController(path=path)
    assert settings.values['services']['rampThicknessAngle'] == 23
    settings.setValue('services', 'mtfFrequencyUnit', 'lp/cm')
    assert settings.setValue('services', 'rampThicknessAngle', 45)
    assert SettingsController(path=path).values['services']['rampThicknessAngle'] == 45
    for invalid in (0, 90, True, '23', None, 22.5, float('nan')):
        assert not settings.setValue('services', 'rampThicknessAngle', invalid)
        assert settings.values['services']['rampThicknessAngle'] == 45
        assert normalize_settings({'measurement': {'rampThicknessAngle': invalid}})['services']['rampThicknessAngle'] == 23
    assert settings.values['services']['mtfFrequencyUnit'] == 'lp/cm'
    settings.resetSection('services')
    assert settings.values['services']['rampThicknessAngle'] == 23


def test_card_settings_persist_validate_and_reset(tmp_path):
    path = tmp_path/'cards.json'
    settings = SettingsController(path=path)
    assert settings.values['measurement']['linkLabelToShape'] is False
    assert settings.values['measurement']['cardTransparency'] == 8
    for key, value in [('linkLabelToShape', True), ('fontSize', 18), ('cardTransparency', 65)]:
        assert settings.setValue('measurement', key, value)
    assert SettingsController(path=path).values == settings.values
    for value in (-1,101,float('nan'),float('inf'),True,'55'):
        assert not settings.setValue('measurement','cardTransparency',value)
    assert settings.resetSection('measurement')
    restored = SettingsController(path=path)
    assert restored.values['measurement']['cardTransparency'] == 8
    assert not restored.values['measurement']['linkLabelToShape']
