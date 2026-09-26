from qt_dicom_viewer.i18n import message as _msg
import os
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from math import exp, isfinite, log
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from pydicom import FileDataset
from pydicom.multival import MultiValue
from pydicom.pixels import apply_modality_lut
from qt_dicom_viewer.core.ct import validate_ct_dataset
from qt_dicom_viewer.core.enhanced_frames import is_enhanced_ct
from qt_dicom_viewer.core.mr import automatic_mr_window, read_mr_parameters, validate_mr_dataset
from pydicom.valuerep import DA, DT, TM

from qt_dicom_viewer.model import (
    DicomLoadResult,
    InstanceDisplayMeta,
    PixelUnitOption,
    PixelValueMeta,
    WindowLevel, RenderRequest,
)


def _first_value(value: Any) -> Any:
    if isinstance(value, (MultiValue, list, tuple)):
        return value[0] if value else None
    return value


def _optional_float(value: Any) -> float | None:
    value = _first_value(value)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    value = _first_value(value)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    value = _first_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_values(value: Any) -> tuple[float, ...] | None:
    if value is None or isinstance(value, (str, bytes)):
        return None
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None


def _float_pair(value: Any) -> tuple[float, float] | None:
    values = _float_values(value)
    if values is None or len(values) != 2:
        return None
    return values[0], values[1]


def _float_triplet(value: Any) -> tuple[float, float, float] | None:
    values = _float_values(value)
    if values is None or len(values) != 3:
        return None
    return values[0], values[1], values[2]


def _string_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        text = str(value).strip()
        return (text,) if text else ()
    try:
        return tuple(
            text
            for item in value
            if (text := str(item).strip())
        )
    except TypeError:
        text = str(value).strip()
        return (text,) if text else ()


def _parse_dicom_datetime(value: Any) -> datetime | None:
    text = _optional_str(value)
    if text is None:
        return None
    try:
        parsed = DT(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, datetime) else None


def _parse_dicom_date(value: Any) -> date | None:
    text = _optional_str(value)
    if text is None:
        return None
    try:
        parsed = DA(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, date) else None


def _parse_dicom_time(value: Any) -> time | None:
    text = _optional_str(value)
    if text is None:
        return None
    try:
        parsed = TM(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, time) else None


def _combine_datetime(date_value: Any, time_value: Any) -> datetime | None:
    parsed_date = _parse_dicom_date(date_value)
    parsed_time = _parse_dicom_time(time_value)
    if parsed_date is None or parsed_time is None:
        return None
    return datetime.combine(parsed_date, parsed_time)


def _acquisition_datetime(dataset: FileDataset) -> datetime | None:
    parsed = _parse_dicom_datetime(
        getattr(dataset, "AcquisitionDateTime", None)
    )
    if parsed is not None:
        return parsed
    parsed = _combine_datetime(
        getattr(dataset, "AcquisitionDate", None),
        getattr(dataset, "AcquisitionTime", None),
    )
    if parsed is not None:
        return parsed
    return _combine_datetime(
        getattr(dataset, "SeriesDate", None),
        getattr(dataset, "SeriesTime", None),
    )


def _radiopharmaceutical_item(dataset: FileDataset):
    sequence = getattr(
        dataset,
        "RadiopharmaceuticalInformationSequence",
        None,
    )
    if sequence is None or len(sequence) != 1:
        return None
    return sequence[0]


def _radiopharmaceutical_start_datetime(
    item: Any,
    acquisition: datetime,
) -> datetime | None:
    parsed = _parse_dicom_datetime(
        getattr(item, "RadiopharmaceuticalStartDateTime", None)
    )
    if parsed is not None:
        return parsed

    parsed_time = _parse_dicom_time(
        getattr(item, "RadiopharmaceuticalStartTime", None)
    )
    if parsed_time is None:
        return None
    parsed = datetime.combine(acquisition.date(), parsed_time)
    if parsed > acquisition.replace(tzinfo=None):
        parsed -= timedelta(days=1)
    return parsed


def _comparable_datetimes(
    first: datetime,
    second: datetime,
) -> tuple[datetime, datetime]:
    first_aware = first.utcoffset() is not None
    second_aware = second.utcoffset() is not None
    if first_aware != second_aware:
        return first.replace(tzinfo=None), second.replace(tzinfo=None)
    return first, second


def _suv_unit(suv_type: str | None) -> tuple[str, str]:
    normalized = (suv_type or "BW").strip().upper()
    mapping = {
        "BW": "SUVbw",
        "BSA": "SUVbsa",
        "IBW": "SUVibw",
        "LBM": "SUVlbm",
        "LBMJAMES128": "SUVlbm",
        "LBMJANMA": "SUVlbm",
    }
    return mapping.get(normalized, f"SUV({normalized})"), normalized


def _pet_native_unit(units: str) -> str:
    return {
        "BQML": "Bq/ml",
        "CNTS": "counts",
        "CPS": "counts/s",
        "PCNT": "%",
        "NONE": "",
    }.get(units, units)


def _iter_visible_files(folder: Path):
    for root, dirnames, filenames in os.walk(folder):
        # dirnames 和 os.walk(folder) 返回的对象指向同一块区域。
        # 如果采用 dirnames = xxx 。则下次遍历还会遍历.xx的文件夹。
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            yield Path(root) / filename


def _read_series_dataset(file_path: Path) -> FileDataset | None:
    try:
        dataset = pydicom.dcmread(file_path, stop_before_pixels=False)
        return dataset
    except Exception:
        return None


class DicomLoader:
    def __init__(self):
        self._decoded = OrderedDict()
        self._headers = OrderedDict()

    def load_a_dicom(
        self,
        instance_path: Path,
        render_request: RenderRequest,
        frame_index: int | None = None,
    ) -> DicomLoadResult | None:
        dataset, pixels = self.read_frame(instance_path, frame_index)

        return self.load_dataset(
            dataset=dataset,
            target_window=render_request.window,
            inverted=render_request.inverted,
            preferred_unit=getattr(render_request, "value_unit", None),
            modality_pixels=pixels,
        )

    def read_frame(self, instance_path, frame_index=None):
        from qt_dicom_viewer.core.enhanced_frames import frame_metadata, is_enhanced_image
        from qt_dicom_viewer.core.pixel_codecs import decode_pixels
        stat = instance_path.stat()
        source = (str(instance_path), stat.st_size, stat.st_mtime_ns)
        key = (*source, frame_index)
        if key not in self._decoded:
            if source not in self._headers:
                header = pydicom.dcmread(instance_path, stop_before_pixels=True)
                # Avoid reparsing thousands of functional groups on every slice.
                # Small Enhanced objects retain encoded bytes, never all decoded
                # frames. Large objects stay on pydicom's indexed file path.
                if is_enhanced_image(header) and stat.st_size <= 64 * 1024 * 1024:
                    header = pydicom.dcmread(instance_path)
                self._headers[source] = header
                while (len(self._headers) > 4 or sum(len(getattr(d, "PixelData", b""))
                       for d in self._headers.values()) > 128 * 1024 * 1024):
                    self._headers.popitem(last=False)
            self._headers.move_to_end(source)
            header = self._headers[source]
            if is_enhanced_image(header):
                dataset = frame_metadata(header, frame_index)
                pixels = self.rescale_pixels(decode_pixels(header if "PixelData" in header else instance_path,
                                                        header=header,
                                                        index=frame_index), dataset)
            else:
                dataset = header
                from qt_dicom_viewer.core.color_image import is_color
                if is_color(header):
                    pixels = decode_pixels(instance_path, index=frame_index if frame_index is not None else 0)
                else:
                    dataset = pydicom.dcmread(instance_path)
                    pixels = self.to_modality_pixels(dataset)
                # Keep the header and decoded frame, not a second raw PixelData buffer.
                dataset = header
                if frame_index is not None:
                    dataset = header.copy()
                    dataset._voxenra_frame_index = frame_index
            validate_ct_dataset(dataset)
            validate_mr_dataset(dataset)
            self._decoded[key] = (dataset, pixels)
            while len(self._decoded) > 12:
                self._decoded.popitem(last=False)
        self._decoded.move_to_end(key)
        return self._decoded[key]

    def load_dataset(
        self,
        dataset: FileDataset,
        target_window: WindowLevel | None,
        inverted: bool,
        preferred_unit: str | None = None,
        modality_pixels: np.ndarray | None = None,
    ) -> DicomLoadResult:
        """Load one source DICOM frame and prepare its display result."""
        from qt_dicom_viewer.core.color_image import is_color, color_pixels
        if is_color(dataset):
            if modality_pixels is None:
                from qt_dicom_viewer.core.pixel_codecs import decode_pixels
                modality_pixels = decode_pixels(dataset, index=0)
            return DicomLoadResult(window=WindowLevel(127.5, 255), inverted=False,
                image=color_pixels(modality_pixels, dataset), modality_pixel=None,
                instance_meta=self.extract_instance_meta(dataset),
                pixel_value_meta=PixelValueMeta(quantification="color", unit_id="color"))
        validate_ct_dataset(dataset)
        validate_mr_dataset(dataset)
        if modality_pixels is None:
            modality_pixels = self.to_modality_pixels(dataset)
        if modality_pixels.ndim != 2:
            if int(getattr(dataset, "SamplesPerPixel", 1)) > 1:
                raise ValueError(_msg("viewer.colorUnsupported"))
            raise ValueError(_msg("viewer.frameLayoutUnsupported"))

        display_pixels, pixel_value_meta, value_scale = (
            self.to_display_values(
                dataset,
                modality_pixels,
                preferred_unit=preferred_unit,
            )
        )
        modality = (
            _optional_str(getattr(dataset, "Modality", None)) or ""
        ).upper()
        minimum_width = (
            0.01
            if pixel_value_meta.is_suv
            else 0.001
            if modality in ("PT", "MR")
            else 1.0
        )
        effective_target_window = target_window
        if (
            modality == "PT"
            and preferred_unit
            and pixel_value_meta.unit_id != preferred_unit
        ):
            # A requested quantitative unit can become unavailable on a
            # later slice. Recompute a truthful source-domain range instead
            # of applying an SUV-scale upper limit to Bq/ml values.
            effective_target_window = None
        # CT VOI and supplemental palette use the source modality/stored domains.
        from qt_dicom_viewer.core.ct_display import supplemental_overlay, composite_palette
        from qt_dicom_viewer.core.display_mapping import source_palette
        ct_source = modality == "CT" and is_enhanced_ct(dataset)
        window_pixels = modality_pixels if ct_source else display_pixels
        overlay = supplemental_overlay(dataset, modality_pixels) if ct_source else None
        effective_window = self.resolve_window(
            dataset=dataset,
            target_window=effective_target_window,
            modality_pixels=window_pixels,
            pixel_value_meta=pixel_value_meta,
            value_scale=value_scale,
        )
        image = self.apply_window(
            modality_pixels=window_pixels,
            target_window=effective_window,
            inverted=inverted ^ (modality == "MR" and getattr(dataset, "PhotometricInterpretation", "") == "MONOCHROME1"),
            minimum_width=minimum_width,
        )

        return DicomLoadResult(
            window=effective_window,
            inverted=inverted,
            image=composite_palette(image, overlay),
            window_pixels=window_pixels if ct_source else None,
            supplemental_overlay=overlay,
            source_palette=source_palette(dataset) if ct_source else None,
            modality_pixel=display_pixels,
            instance_meta=self.extract_instance_meta(dataset),
            pixel_value_meta=pixel_value_meta,
        )

    @staticmethod
    def to_modality_pixels(dataset: FileDataset) -> np.ndarray:
        """Convert stored pixels with the DICOM Modality LUT/rescale."""
        validate_ct_dataset(dataset)
        validate_mr_dataset(dataset)
        from qt_dicom_viewer.core.pixel_codecs import decode_pixels
        stored = np.asarray(decode_pixels(dataset))
        return DicomLoader.rescale_pixels(stored, dataset)

    @staticmethod
    def rescale_pixels(stored: np.ndarray, dataset: FileDataset) -> np.ndarray:
        from qt_dicom_viewer.core.color_image import is_color
        if is_color(dataset):
            return np.ascontiguousarray(stored)
        padding_mask = DicomLoader._padding_mask(stored, dataset)
        values = np.asarray(
            apply_modality_lut(stored, dataset),
            dtype=np.float32,
        )
        if padding_mask is not None:
            values = values.copy()
            values[padding_mask] = np.nan
        return np.ascontiguousarray(values, dtype=np.float32)

    @staticmethod
    def _padding_mask(
        stored_pixels: np.ndarray,
        dataset: FileDataset,
    ) -> np.ndarray | None:
        padding_value = _optional_float(
            getattr(dataset, "PixelPaddingValue", None)
        )
        if padding_value is None:
            return None
        range_limit = _optional_float(
            getattr(dataset, "PixelPaddingRangeLimit", None)
        )
        if range_limit is None:
            return stored_pixels == padding_value
        lower, upper = sorted((padding_value, range_limit))
        return (stored_pixels >= lower) & (stored_pixels <= upper)

    @staticmethod
    def to_display_values(
        dataset: FileDataset,
        modality_pixels: np.ndarray,
        *,
        preferred_unit: str | None = None,
    ) -> tuple[np.ndarray, PixelValueMeta, float]:
        modality = (_optional_str(getattr(dataset, "Modality", None)) or "").upper()
        if modality == "CT":
            if is_enhanced_ct(dataset):
                from qt_dicom_viewer.core.ct_display import quantitative_values
                values, meta = quantitative_values(dataset, modality_pixels)
                return values, meta, 1.0
            return modality_pixels, PixelValueMeta(unit="HU", source_unit="HU"), 1.0
        if modality == "MR":
            source_unit = _optional_str(getattr(dataset, "RescaleType", None))
            unit = source_unit if source_unit and source_unit.upper() not in ("US", "UNSPECIFIED") else "a.u."
            return modality_pixels, PixelValueMeta(unit=unit, source_unit=source_unit), 1.0
        if modality != "PT":
            rescale_type = _optional_str(
                getattr(dataset, "RescaleType", None)
            )
            return modality_pixels, PixelValueMeta(
                unit=rescale_type or "",
                source_unit=rescale_type,
                quantification="native",
            ), 1.0

        units = (_optional_str(getattr(dataset, "Units", None)) or "").upper()
        suv_type = _optional_str(getattr(dataset, "SUVType", None))
        if units == "GML":
            unit, normalized_type = _suv_unit(suv_type)
            option = PixelUnitOption(
                unit_id=f"suv-{normalized_type.casefold()}",
                label=f"{'cm²/ml' if normalized_type == 'BSA' else 'g/ml'} ({unit})",
                unit=unit,
                scale_from_source=1.0,
            )
            return modality_pixels, PixelValueMeta(
                unit=unit,
                suv_type=normalized_type,
                source_unit=units,
                quantification="native",
                unit_id=option.unit_id,
                unit_options=(option,),
            ), 1.0

        if units == "BQML":
            scale, warning = DicomLoader._suvbw_scale(dataset)
            options = (
                PixelUnitOption(
                    unit_id="source",
                    label="Source (BQML)",
                    unit="Bq/ml",
                    scale_from_source=1.0,
                ),
                PixelUnitOption(
                    unit_id="kbqml",
                    label="kBq/ml",
                    unit="kBq/ml",
                    scale_from_source=0.001,
                ),
                PixelUnitOption(
                    unit_id="suvbw",
                    label="g/ml (SUVbw)",
                    unit="SUVbw",
                    scale_from_source=scale or 1.0,
                    available=scale is not None,
                    warning=warning,
                ),
            )
            available = {
                option.unit_id: option
                for option in options
                if option.available
            }
            default_unit_id = "suvbw" if scale is not None else "source"
            option = available.get(preferred_unit or "") or available[
                default_unit_id
            ]
            values = np.ascontiguousarray(
                modality_pixels * option.scale_from_source,
                dtype=np.float32,
            )
            is_suvbw = option.unit_id == "suvbw"
            return values, PixelValueMeta(
                unit=option.unit,
                suv_type="BW" if is_suvbw else None,
                source_unit=units,
                quantification=(
                    "derived"
                    if is_suvbw
                    else "unavailable"
                    if scale is None
                    else "native"
                ),
                warning=warning if scale is None else None,
                unit_id=option.unit_id,
                scale_from_source=option.scale_from_source,
                unit_options=options,
            ), option.scale_from_source

        warning = None
        quantification = "native"
        if not units:
            quantification = "unavailable"
            warning = _msg('text.0062')
        native_unit = _pet_native_unit(units)
        option = PixelUnitOption(
            unit_id="source",
            label=f"Source ({units})" if units else "Source",
            unit=native_unit,
            scale_from_source=1.0,
        )
        return modality_pixels, PixelValueMeta(
            unit=native_unit,
            source_unit=units or None,
            quantification=quantification,
            warning=warning,
            unit_id=option.unit_id,
            unit_options=(option,),
        ), 1.0

    @staticmethod
    def _suvbw_scale(
        dataset: FileDataset,
    ) -> tuple[float | None, str | None]:
        if (
            getattr(dataset, "RescaleSlope", None) is None
            or getattr(dataset, "RescaleIntercept", None) is None
        ):
            return None, _msg('text.0063')

        corrected = {
            value.upper()
            for value in _string_values(
                getattr(dataset, "CorrectedImage", None)
            )
        }
        missing_corrections = sorted({"ATTN", "DECY"} - corrected)
        if missing_corrections:
            return None, (
                _msg('text.0064') + "/".join(missing_corrections)
                + _msg('text.0065')
            )

        decay_correction = (
            _optional_str(getattr(dataset, "DecayCorrection", None)) or ""
        ).upper()
        if decay_correction not in {"START", "ADMIN"}:
            return None, _msg('text.0066')

        patient_weight_kg = _optional_float(
            getattr(dataset, "PatientWeight", None)
        )
        if patient_weight_kg is None or patient_weight_kg <= 0:
            return None, _msg('text.0067')

        item = _radiopharmaceutical_item(dataset)
        if item is None:
            return None, _msg('text.0068')
        total_dose_bq = _optional_float(
            getattr(item, "RadionuclideTotalDose", None)
        )
        half_life_seconds = _optional_float(
            getattr(item, "RadionuclideHalfLife", None)
        )
        if total_dose_bq is None or total_dose_bq <= 0:
            return None, _msg('text.0069')
        if half_life_seconds is None or half_life_seconds <= 0:
            return None, _msg('text.0070')

        acquisition = _acquisition_datetime(dataset)
        if acquisition is None:
            return None, _msg('text.0071')
        administration = _radiopharmaceutical_start_datetime(
            item,
            acquisition,
        )
        if administration is None:
            return None, _msg('text.0072')
        acquisition, administration = _comparable_datetimes(
            acquisition,
            administration,
        )
        elapsed_seconds = (acquisition - administration).total_seconds()
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            return None, _msg('text.0073')

        corrected_dose_bq = total_dose_bq
        if decay_correction == "START":
            corrected_dose_bq *= exp(
                -log(2.0) * elapsed_seconds / half_life_seconds
            )
        if not isfinite(corrected_dose_bq) or corrected_dose_bq <= 0:
            return None, _msg('text.0074')

        scale = patient_weight_kg * 1000.0 / corrected_dose_bq
        if not isfinite(scale) or scale <= 0:
            return None, _msg('text.0075')
        return scale, None

    @staticmethod
    def resolve_window(
        dataset: FileDataset,
        target_window: WindowLevel | None,
        modality_pixels: np.ndarray | None = None,
        pixel_value_meta: PixelValueMeta | None = None,
        value_scale: float = 1.0,
    ) -> WindowLevel:
        modality = (_optional_str(getattr(dataset, "Modality", None)) or "").upper()
        minimum_width = (
            0.01
            if pixel_value_meta is not None and pixel_value_meta.is_suv
            else 0.001
            if modality in ("PT", "MR")
            else 1.0
        )
        if target_window is not None:
            if modality == "PT":
                upper = max(
                    float(target_window.center)
                    + float(target_window.width) / 2.0,
                    minimum_width,
                )
                return WindowLevel(center=upper / 2.0, width=upper)
            return DicomLoader.normalize_window(
                target_window,
                minimum_width=minimum_width,
            )

        center = _optional_float(
            getattr(dataset, "WindowCenter", None)
        )
        width = _optional_float(
            getattr(dataset, "WindowWidth", None)
        )

        if (center is not None and width is not None
                and (modality != "MR" or (isfinite(center) and isfinite(width) and width >= minimum_width))):
            if modality == "PT":
                upper = (center + width / 2.0) * value_scale
                if isfinite(upper) and upper > minimum_width:
                    return WindowLevel(
                        center=upper / 2.0,
                        width=upper,
                    )
            else:
                return DicomLoader.normalize_window(
                    WindowLevel(center=center, width=width),
                    minimum_width=minimum_width,
                )

        if modality == "PT":
            if pixel_value_meta is not None and pixel_value_meta.is_suv:
                return WindowLevel(center=2.5, width=5.0)
            finite = (
                modality_pixels[np.isfinite(modality_pixels)]
                if modality_pixels is not None
                else np.asarray([], dtype=np.float32)
            )
            if finite.size:
                high = float(np.percentile(finite, 99.5))
                if isfinite(high) and high > minimum_width:
                    return WindowLevel(
                        center=high / 2.0,
                        width=high,
                    )
                maximum = float(np.max(finite))
                if isfinite(maximum) and maximum > 0:
                    upper = max(maximum, minimum_width)
                    return WindowLevel(center=upper / 2.0, width=upper)
            # An all-padding PET frame still uses the PET intensity model.
            # Falling through to CT's 40/400 default would expose a negative
            # lower bound and misleading WL/WW semantics.
            return WindowLevel(center=0.5, width=1.0)

        if modality == "MR" or (modality == "CT" and is_enhanced_ct(dataset)
                and str(getattr(dataset, "RescaleType", "")).upper() != "HU"):
            return automatic_mr_window(modality_pixels if modality_pixels is not None else np.array([]))

        return DicomLoader.normalize_window(
            WindowLevel(center=40.0, width=400.0),
            minimum_width=minimum_width,
        )

    @staticmethod
    def normalize_window(
        window: WindowLevel,
        *,
        minimum_width: float = 1.0,
    ) -> WindowLevel:
        return WindowLevel(
            center=float(window.center),
            width=max(float(window.width), minimum_width),
        )

    @staticmethod
    def apply_window(
        modality_pixels: np.ndarray,
        target_window: WindowLevel,
        inverted: bool,
        minimum_width: float = 1.0,
    ) -> np.ndarray:
        """Window any modality-valued 2D array, source stack or MPR plane."""
        effective_window = DicomLoader.normalize_window(
            target_window,
            minimum_width=minimum_width,
        )
        window_center = effective_window.center
        window_width = effective_window.width

        lower = window_center - window_width / 2
        upper = window_center + window_width / 2

        source_pixels = np.asarray(
            modality_pixels,
            dtype=np.float32,
        )
        valid_pixels = np.isfinite(source_pixels)
        displayed = np.clip(
            source_pixels,
            lower,
            upper,
        )
        displayed = (displayed - lower) / (upper - lower)
        if inverted:
            displayed = 1.0 - displayed
        displayed = np.where(
            valid_pixels,
            displayed,
            0.0,
        )

        image_8bit = (displayed * 255).astype(np.uint8)
        return np.ascontiguousarray(image_8bit)

    @staticmethod
    def extract_instance_meta(
        dataset: FileDataset,
    ) -> InstanceDisplayMeta:
        radiopharmaceutical_item = _radiopharmaceutical_item(dataset)
        return InstanceDisplayMeta(
            mr_parameters=read_mr_parameters(dataset),
            frame_index=getattr(dataset, "_voxenra_frame_index", None),
            photometric_interpretation=str(getattr(dataset, "PhotometricInterpretation", "")),
            instance_number=_optional_int(
                getattr(dataset, "InstanceNumber", None)
            ),
            sop_instance_uid=_optional_str(
                getattr(dataset, "SOPInstanceUID", None)
            ),
            manufacturer=_optional_str(
                getattr(dataset, "Manufacturer", None)
            ),
            kvp=_optional_float(getattr(dataset, "KVP", None)),
            tube_current_ma=_optional_float(
                getattr(dataset, "_voxenra_tube_current_ma", getattr(dataset, "XRayTubeCurrent", None))
            ),
            slice_thickness=_optional_float(
                getattr(dataset, "SliceThickness", None)
            ),
            rows=_optional_int(getattr(dataset, "Rows", None)),
            columns=_optional_int(getattr(dataset, "Columns", None)),
            pixel_spacing=_float_pair(
                getattr(dataset, "PixelSpacing", None),
            ),
            image_position=_float_triplet(
                getattr(dataset, "ImagePositionPatient", None),
            ),
            slice_location=_optional_float(
                getattr(dataset, "SliceLocation", None)
            ),
            radiopharmaceutical=(
                _optional_str(
                    getattr(
                        radiopharmaceutical_item,
                        "Radiopharmaceutical",
                        None,
                    )
                )
                if radiopharmaceutical_item is not None
                else None
            ),
            pet_units=_optional_str(getattr(dataset, "Units", None)),
            suv_type=_optional_str(getattr(dataset, "SUVType", None)),
            decay_correction=_optional_str(
                getattr(dataset, "DecayCorrection", None)
            ),
            corrected_image=_string_values(
                getattr(dataset, "CorrectedImage", None)
            ),
        )
