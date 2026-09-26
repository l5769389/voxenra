"""Validated JSON schema for user preferences (no image or patient data)."""
from qt_dicom_viewer.i18n import message as _msg
from copy import deepcopy
from math import isfinite
from pathlib import Path
import re

from qt_dicom_viewer.core.color_maps import COLOR_MAPS
from qt_dicom_viewer.core.measurement_format import DEFAULT_DECIMAL_PLACES
from qt_dicom_viewer.core.mpr_layout import MPR_LAYOUTS
from qt_dicom_viewer.preset import CT_WINDOW_PRESETS

CORNER_FIELDS = {
    "viewPosition": _msg('text.0022'), "manufacturer": _msg('text.0023'), "seriesDescription": _msg('text.0024'),
    "studyDescription": _msg('text.0025'), "modality": _msg('text.0026'), "slice": _msg('text.0027'),
    "patientName": _msg('text.0028'), "patientId": _msg('text.0029'), "exposure": _msg("mr.acquisitionParameters"),
    "sliceThickness": _msg('text.0030'), "window": _msg('text.0031'), "cursor": _msg('text.0032'),
    "zoom": _msg('text.0033'), "transform": _msg('text.0034'), "instanceNumber": _msg('text.0035'),
    "matrix": _msg('text.0036'), "spacing": _msg('text.0037'), "seriesUid": _msg('text.0038'),
}
CORNERS = ("topLeft", "topRight", "bottomLeft", "bottomRight")
METRICS = {"mean": _msg('text.0039'), "std": _msg('text.0040'), "minimum": _msg('text.0041'),
           "maximum": _msg('text.0042'), "area": _msg('text.0043'), "dimensions": _msg('text.0044'), "count": _msg('text.0045')}
DEFAULTS = {
    "appearance": {"theme": "dark", "language": "zh-CN"},
    "updates": {"enabled": True, "dismissedVersion": ""},
    "workspace": {"automaticRecovery": True, "exitBehavior": "ask"},
    "layout": {"rightPanelCollapsed": False, "rightPanelWidth": 250, "settingsNavigationWidth": 180, "manualNavigationWidth": 260,
               "rememberedMprLayout": "", "rememberedFourDLayout": "", "settingsCollapsedGroups": []},
    "export": {"directory": ""},
    "colormap": {"gray": "grayscale", "pet": "grayscale"},
    "window": {"hidden": [], "custom": []},
    "crosshair": {"axialColor": "#ff0000", "coronalColor": "#008000", "sagittalColor": "#0000ff",
                  "axialWidth": 1.0, "coronalWidth": 1.0, "sagittalWidth": 1.0},
    "corners": {"enabled": True, "fontSize": 12, "lineHeight": 1.2,
                "colorMode": "auto", "color": "#f8fafc",
                "topLeft": ["viewPosition", "manufacturer", "seriesDescription", "slice"],
                "topRight": ["patientName", "patientId"],
                "bottomLeft": ["exposure", "sliceThickness", "window"], "bottomRight": ["transform", "cursor"]},
    "scale": {"enabled": True, "color": "#f8fafc", "lengthMm": 100},
    "measurement": {"editingColor": "#66d0ff", "completedColor": "#ffd45c", "lineWidth": 1.5,
                    "editingDash": True, "completedDash": False, "fontSize": 13,
                    "linkLabelToShape": False, "cardTransparency": 8,
                    "decimalPlaces": DEFAULT_DECIMAL_PLACES,
                    "annotationColor": "#ffd166", "annotationSize": 14},
    "services": {"mtfFrequencyUnit": "lp/mm", "mtfGaussianEquivalent": True,
                 "rampThicknessAngle": 23},
    "roi": {key: True for key in METRICS},
}


def validate_value(section, key, value):
    if section not in DEFAULTS or key not in DEFAULTS[section]:
        raise ValueError(_msg('text.0046'))
    default = DEFAULTS[section][key]
    if section == "updates" and key == "dismissedVersion":
        if not isinstance(value, str) or (value and not re.fullmatch(r"\d+\.\d+\.\d+", value)):
            raise ValueError(_msg("updates.invalidVersion"))
    elif section == "appearance":
        if key == "theme" and value not in ("dark", "graphite", "light"):
            raise ValueError(_msg('text.1166'))
        if key == "language" and (not isinstance(value, str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value)):
            raise ValueError(_msg('text.1167'))
    elif section == "export" and key == "directory":
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError(_msg('text.0047'))
        value = value.strip()
        if value:
            path = Path(value).expanduser()
            if not path.is_absolute() or (path.exists() and not path.is_dir()):
                raise ValueError(_msg('text.0048'))
            value = str(path)
    elif section == "workspace" and key == "exitBehavior":
        if value not in ("ask", "save", "discard"):
            raise ValueError(_msg('text.0049'))
    elif section == "layout" and key == "settingsCollapsedGroups":
        if (not isinstance(value, list) or len(value) > 128
                or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", v) for v in value)):
            raise ValueError(_msg('settings.invalidGroups'))
        value = list(dict.fromkeys(value))
    elif section == "layout" and key in ("rememberedMprLayout", "rememberedFourDLayout"):
        if not isinstance(value, str) or value not in ("", *MPR_LAYOUTS):
            raise ValueError(_msg("mpr.layout.invalid"))
    elif isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(_msg('text.0050'))
    elif key.lower().endswith("color"):
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(_msg('text.0051'))
        value = value.lower()
    elif section == "colormap":
        if value not in COLOR_MAPS:
            raise ValueError(_msg('text.0052'))
    elif key == "colorMode":
        if value not in ("auto", "custom"):
            raise ValueError(_msg('text.0053'))
    elif section == "scale" and key == "lengthMm":
        if isinstance(value, bool) or value not in (1, 10, 20, 50, 100):
            raise ValueError(_msg('text.0054'))
        value = int(value)
    elif section == "measurement" and key == "decimalPlaces":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0, 1, 2, 3):
            raise ValueError(_msg('measurement.invalidPrecision'))
        value = int(value)
    elif section == "services" and key == "mtfFrequencyUnit":
        if value not in ("lp/mm", "lp/cm"):
            raise ValueError(_msg('mtf.invalidUnit'))
    elif section == "services" and key == "rampThicknessAngle":
        if isinstance(value, bool) or value not in (23, 45):
            raise ValueError(_msg('ramp.invalidAngle'))
        value = int(value)
    elif isinstance(default, (int, float)):
        limits = {"fontSize": (10, 20), "lineHeight": (1, 1.8), "lineWidth": (1, 6), "annotationSize": (8, 28),
                  "cardTransparency": (0, 100), "rightPanelWidth": (220, 420), "settingsNavigationWidth": (156, 300), "manualNavigationWidth": (220, 400)}
        low, high = limits.get(key, (1, 6))
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value) or not low <= value <= high:
            raise ValueError(_msg('text.0055', value1=low, value2=high))
        value = int(round(value)) if isinstance(default, int) else round(float(value), 2)
    elif section == "corners" and key in CORNERS:
        if not isinstance(value, list) or len(value) > 8 or any(v not in CORNER_FIELDS for v in value) or len(set(value)) != len(value):
            raise ValueError(_msg('text.0056'))
    elif section == "window" and key == "hidden":
        ids = {p.preset_id for p in CT_WINDOW_PRESETS}
        if not isinstance(value, list) or any(v not in ids for v in value):
            raise ValueError(_msg('text.0057'))
        value = list(dict.fromkeys(value))
    elif section == "window" and key == "custom":
        if not isinstance(value, list) or len(value) > 20:
            raise ValueError(_msg('text.0058'))
        ids, labels, validated = set(), set(), []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError(_msg('text.0059'))
            name, identifier = str(item.get("label", "")).strip(), str(item.get("presetId", ""))
            if not name or len(name) > 40 or name.casefold() in labels or not re.fullmatch(r"custom-[a-zA-Z0-9-]+", identifier) or identifier in ids:
                raise ValueError(_msg('text.0060'))
            width, center = item.get("width"), item.get("center")
            if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not isfinite(v) for v in (width, center)) or not 1 <= width <= 1000000 or not -1000000 <= center <= 1000000:
                raise ValueError(_msg('text.0061'))
            ids.add(identifier)
            labels.add(name.casefold())
            validated.append(dict(presetId=identifier, label=name, width=float(width), center=float(center), enabled=bool(item.get("enabled", True))))
        value = validated
    return deepcopy(value)


def normalize_settings(raw):
    data = deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return data
    # Move calculation preferences out of annotation appearance. Existing
    # service values win, including an explicit reset to defaults.
    raw = deepcopy(raw)
    legacy = raw.get("measurement", {})
    services = raw.get("services", {})
    services = services if isinstance(services, dict) else {}
    if isinstance(legacy, dict):
        for key in DEFAULTS["services"]:
            if key not in services and key in legacy:
                services[key] = legacy[key]
    raw["services"] = services
    for section, entries in data.items():
        candidate = raw.get(section, {})
        if not isinstance(candidate, dict):
            continue
        for key in entries:
            if key in candidate:
                try:
                    entries[key] = validate_value(section, key, candidate[key])
                except (ValueError, TypeError):
                    pass
    # Upgrade only the former default layout. A versioned save keeps an
    # explicitly removed field removed on every subsequent launch.
    if raw.get("schemaVersion", 0) == 0:
        corners = raw.get("corners", {})
        if (isinstance(corners, dict) and corners.get("bottomRight") == ["cursor"]
                and not any("transform" in data["corners"][corner] for corner in CORNERS)):
            data["corners"]["bottomRight"] = ["transform", "cursor"]
    # Migrate the former independent flags without turning a hidden size back on.
    legacy_roi = raw.get("roi", {})
    if isinstance(legacy_roi, dict) and "dimensions" not in legacy_roi:
        data["roi"]["dimensions"] = not any(legacy_roi.get(key) is False for key in ("width", "height"))
    group_names = {"measurement-mtf": "services-mtf", "measurement-thickness": "services-fwhm"}
    data["layout"]["settingsCollapsedGroups"] = list(dict.fromkeys(
        group_names.get(key, key) for key in data["layout"]["settingsCollapsedGroups"]))
    return data
