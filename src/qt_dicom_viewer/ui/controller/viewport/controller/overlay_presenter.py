from math import cos, isfinite, radians, sqrt
from typing import Sequence

from qt_dicom_viewer.model import (
    FrameDisplayMeta,
    MprPlane,
    SeriesDisplayMeta,
    ViewportConfig,
    ViewportState,
)
from qt_dicom_viewer.utils.utils import _display_text, _display_number


_PLANE_NAMES_BY_AXIS = ("Sagittal", "Coronal", "Axial")
_POSITION_LABELS_BY_AXIS = (
    ("L", "R"),
    ("P", "A"),
    ("S", "I"),
)


def _format_view_position(
    viewport_type,
    image_position_patient: Sequence[float] | None,
    image_orientation_patient: Sequence[float] | None,
) -> str:
    """Format the plane's signed LPS distance like ``Axial, I: 12.34mm``."""
    if (
        image_position_patient is None
        or image_orientation_patient is None
        or len(image_position_patient) != 3
        or len(image_orientation_patient) != 6
    ):
        return ""

    position = tuple(float(value) for value in image_position_patient)
    orientation = tuple(
        float(value) for value in image_orientation_patient
    )
    if not all(isfinite(value) for value in (*position, *orientation)):
        return ""

    column = orientation[:3]
    row = orientation[3:]
    normal = (
        column[1] * row[2] - column[2] * row[1],
        column[2] * row[0] - column[0] * row[2],
        column[0] * row[1] - column[1] * row[0],
    )
    normal_length = sqrt(sum(value * value for value in normal))
    if normal_length <= 1e-12:
        return ""

    normal = tuple(value / normal_length for value in normal)
    dominant_axis = max(range(3), key=lambda index: abs(normal[index]))
    if normal[dominant_axis] < 0.0:
        normal = tuple(-value for value in normal)

    signed_distance = sum(
        position[index] * normal[index]
        for index in range(3)
    )
    positive_label, negative_label = _POSITION_LABELS_BY_AXIS[
        dominant_axis
    ]
    direction_label = (
        positive_label if signed_distance >= 0.0 else negative_label
    )
    # Ignore direction-cosine rounding, but identify real oblique cuts.
    plane_name = (_PLANE_NAMES_BY_AXIS[dominant_axis]
                  if abs(normal[dominant_axis]) >= cos(radians(0.1)) else "Oblique")
    distance = 0.0 if abs(signed_distance) < 0.005 else abs(signed_distance)
    return f"{plane_name}, {direction_label}: {distance:.2f}mm"


class OverlayPresenter:
    def build(
        self,
        *,
        viewport_config: ViewportConfig,
        series: SeriesDisplayMeta,
        frame: FrameDisplayMeta | None,
        state: ViewportState,
    ) -> dict:
        instance = frame.instance_meta if frame else None
        value_meta = frame.pixel_value_meta if frame else None
        window_precision = 3 if series.modality.upper() == "MR" else 2 if value_meta and value_meta.is_suv else 0
        pet_value_precision = (
            3
            if value_meta and value_meta.unit in {"SUVbw", "kBq/ml"}
            else 0
        )
        position = instance.image_position if instance else None
        spacing = instance.pixel_spacing if instance else None
        geometry = frame.geometry if frame else None
        is_ct = series.modality.upper() == "CT"
        is_pet = series.modality.upper() == "PT"
        derived = is_ct and not series.supports_ct_analysis
        intent = state.display_mapping
        custom = bool(value_meta and intent.applies_to(value_meta.unit))
        palette = frame.source_palette if frame else None
        bounds = (intent.lower, intent.upper) if custom else (palette.lower, palette.upper) if palette else None
        from qt_dicom_viewer.core.mr import format_mr_parameters
        return {
            "mrParameters": format_mr_parameters(instance.mr_parameters) if instance and series.modality.upper() == "MR" else "",
            "patientName": _display_text(series.patient_name),
            "patientId": _display_text(series.patient_id),
            "studyDescription": _display_text(series.study_description),
            "seriesDescription": _display_text(series.series_description),
            "modality": _display_text(series.modality),
            "manufacturer": _display_text(
                instance.manufacturer if instance else None
            ),
            "viewType": _display_text(viewport_config.viewport_type),
            "viewPosition": _format_view_position(
                viewport_config.viewport_type,
                geometry.image_position_patient if geometry else None,
                geometry.image_orientation_patient if geometry else None,
            ),
            "kvp": (
                _display_number(instance.kvp if instance else None)
                if is_ct
                else ""
            ),
            "tubeCurrentMa": (
                _display_number(
                    instance.tube_current_ma if instance else None
                )
                if is_ct
                else ""
            ),
            "sliceThickness": _display_number(
                instance.slice_thickness if instance else None
            ),
            "sliceIndex": str(frame.slice_index + 1) if frame else "--",
            "sliceCount": str(frame.slice_count) if frame else "--",
            "instanceNumber": _display_number(
                instance.instance_number if instance else None,
                precision=0,
            ),
            "rows": _display_number(
                instance.rows if instance else None,
                precision=0,
            ),
            "columns": _display_number(
                instance.columns if instance else None,
                precision=0,
            ),
            # DICOM PixelSpacing 的顺序是 row(Y), column(X)。
            "pixelSpacingX": _display_number(spacing[1] if spacing else None),
            "pixelSpacingY": _display_number(spacing[0] if spacing else None),
            "positionX": _display_number(position[0] if position else None),
            "positionY": _display_number(position[1] if position else None),
            "positionZ": _display_number(position[2] if position else None),
            "sliceLocation": _display_number(
                instance.slice_location if instance else None
            ),
            "windowCenter": _display_number(
                frame.window.center if frame else None,
                window_precision,
            ),
            "windowWidth": _display_number(
                (
                    frame.window.width * (-1 if frame.inverted else 1)
                    if frame
                    else None
                ),
                window_precision,
            ),
            "zoom": f"{state.zoom * 100:.0f}%",
            "radiopharmaceutical": (
                instance.radiopharmaceutical or ""
                if instance
                else ""
            ),
            "petUnits": instance.pet_units or "" if instance else "",
            "suvType": (
                value_meta.suv_type or ""
                if value_meta
                else ""
            ),
            "derivedMapping": derived,
            "mappingMode": "custom" if custom else "source",
            "mappingLower": _display_number(bounds[0], 3) if bounds else "",
            "mappingUpper": _display_number(bounds[1], 3) if bounds else "",
            "pixelUnit": value_meta.unit if value_meta else "",
            "sourceColor": bool(value_meta and value_meta.quantification == "color"),
            "supplementalColor": frame is not None and frame.supplemental_overlay is not None,
            "decayCorrection": (
                instance.decay_correction or ""
                if instance
                else ""
            ),
            "quantificationWarning": (
                value_meta.warning or ""
                if value_meta
                else ""
            ),
            "correctedImage": (
                "/".join(instance.corrected_image)
                if instance
                else ""
            ),
            "petDisplayLower": "0" if frame and is_pet else "",
            "petDisplayUpper": _display_number(
                (
                    state.window.center + state.window.width / 2.0
                    if state.window and is_pet
                    else None
                ),
                pet_value_precision,
            ),
            "rotation": _display_number(state.rotation_degrees, 0),
            "flip": (
                "H/V"
                if state.horizontal_flip and state.vertical_flip
                else "H"
                if state.horizontal_flip
                else "V"
                if state.vertical_flip
                else "--"
            ),
            "seriesUid": series.series_uid,
            "transform": f"Rot: {state.rotation_degrees:.0f}° · Flip: " + ("H" if state.horizontal_flip else "") + ("V" if state.vertical_flip else "") + ("—" if not state.horizontal_flip and not state.vertical_flip else ""),
        }
