"""Validation of optional analysis records in an untrusted workspace document."""
import math

from qt_dicom_viewer.model.mtf import BeadMtfResult, RampFwhmResult, MtfAxisResult, MtfSensitivitySample
from qt_dicom_viewer.model.water_qa import WaterQaResult, WaterQaSettings
from qt_dicom_viewer.model.measure import RoiMeasurement


def validate_mtf_diagnostics(value):
    """Validate new optional diagnostics without inventing fields in old results."""
    if isinstance(value, MtfSensitivitySample):
        if (not value.variant or len(value.variant) > 80
                or any(v is not None and (not math.isfinite(v) or v <= 0)
                       for v in (value.mtf50, value.mtf10))
                or value.error and (value.mtf50 is not None or value.mtf10 is not None)):
            raise ValueError('Invalid MTF comparison sample')
    elif isinstance(value, MtfAxisResult):
        if (len(value.sensitivity) > 32
                or len({s.variant for s in value.sensitivity}) != len(value.sensitivity)):
            raise ValueError('Invalid MTF comparison identifiers')
        for sample in value.sensitivity:
            validate_mtf_diagnostics(sample)
    elif isinstance(value, BeadMtfResult):
        threshold = value.sensitivity_threshold
        if (threshold is not None and (not math.isfinite(threshold) or not .01 <= threshold <= 1.)
                or threshold is None and (value.x.sensitivity or value.y.sensitivity)):
            raise ValueError('Invalid MTF sensitivity threshold')
        validate_mtf_diagnostics(value.x)
        validate_mtf_diagnostics(value.y)


def validate_analysis_records(analyses):
    if not isinstance(analyses, dict) or not set(analyses) <= {"mtf", "fwhm", "qa"}:
        raise ValueError("Invalid workspace analysis records")
    for kind, state in analyses.items():
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("Unsupported workspace analysis record version")
        if kind == "qa":
            records = state.get("records", [])
            if not isinstance(records, list) or not isinstance(state.get("settings"), WaterQaSettings):
                raise ValueError("Invalid QA record settings")
        else:
            records = state.get("records", {})
            if (not isinstance(records, dict) or not isinstance(state.get("roi"), dict)
                    or state.get("method") not in ({"ramp"} if kind == "fwhm" else {"bead", "wire"})
                    or state.get("analysis") not in {"direct_fft", "tukey_fft", "gaussian"}
                    or state.get("direction") not in {"x", "y"}):
                raise ValueError("Invalid MTF/FWHM record settings")
            records = records.values()
        if len(records) > 100000:
            raise ValueError("Too many saved analyses")
        for record in records:
            expected = WaterQaResult if kind == "qa" else RampFwhmResult if kind == "fwhm" else BeadMtfResult
            if (not isinstance(record, dict) or not isinstance(record.get("result"), expected)
                    or any(not isinstance(record.get(key), str) for key in ("timestamp", "app", "algorithm"))):
                raise ValueError("Invalid saved analysis result")
            if kind == 'mtf':
                validate_mtf_diagnostics(record['result'])
                validate_mtf_diagnostics(record.get('presented'))
            if kind == "qa":
                if not isinstance(record.get("key"), tuple):
                    raise ValueError("Invalid QA source identity")
            elif (not isinstance(record.get("frame"), tuple) or not isinstance(record.get("roi"), RoiMeasurement)
                  or not isinstance(record.get("preferences"), dict)
                  or type(record["preferences"].get("mtfGaussianEquivalent")) is not bool
                  or record["preferences"].get("rampThicknessAngle") not in (23, 45)
                  or not isinstance(record.get("fingerprint", ""), str)
                  or record.get("method") not in ({"ramp"} if kind == "fwhm" else {"bead", "wire"})
                  or record.get("analysis") not in {"direct_fft", "tukey_fft", "gaussian"}
                  or record.get("direction") not in {"x", "y"}
                  or record.get("presented") is not None and not isinstance(record["presented"], expected)
                  or not isinstance(record.get("source", {}), dict)):
                raise ValueError("Invalid analysis provenance")
