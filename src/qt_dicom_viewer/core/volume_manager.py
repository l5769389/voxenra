from __future__ import annotations
from qt_dicom_viewer.i18n import message as _msg

import logging
from dataclasses import replace
from collections import OrderedDict
from hashlib import sha256

import numpy as np
import pydicom

from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.render_cancellation import check_render_cancelled
from qt_dicom_viewer.model import (
    DicomInstanceMeta,
    DicomSeriesRecord,
    InstanceDisplayMeta,
    WindowLevel,
    PixelValueMeta,
)
from qt_dicom_viewer.model.dicom_core import (
    DicomVolume,
    VolumeGeometry,
)

logger = logging.getLogger(__name__)


class VolumeBuildError(RuntimeError):
    pass


class VolumeManager:
    def __init__(self, maximum_cache_bytes: int = 1024 * 1024 * 1024) -> None:
        self._maximum_cache_bytes = max(0, int(maximum_cache_bytes))
        self._volumes_by_series_uid: OrderedDict[
            tuple[str, int | None], DicomVolume
        ] = OrderedDict()

    @property
    def cache_bytes(self):
        # SUV/modality often reference the same allocation. Count it once.
        buffers = {}
        for volume in self._volumes_by_series_uid.values():
            for array in (volume.modality_pixels, volume.source_pixels, volume.suv_pixels):
                if array is not None:
                    buffers[id(array)] = array.nbytes
        return sum(buffers.values())

    def _trim_cache(self):
        # Retain one oversized volume: otherwise three MPR planes would decode
        # the same large series repeatedly. Live views own their references;
        # eviction only releases the worker cache's reference.
        while len(self._volumes_by_series_uid) > 1 and self.cache_bytes > self._maximum_cache_bytes:
            self._volumes_by_series_uid.popitem(last=False)

    def get_volume(
        self,
        series_uid: str,
        phase_identifier: int | None = None,
    ) -> DicomVolume | None:
        key = (series_uid, phase_identifier)
        volume = self._volumes_by_series_uid.get(key)
        if volume is not None:
            self._volumes_by_series_uid.move_to_end(key)
        return volume

    def get_or_build(
        self,
        series: DicomSeriesRecord,
        phase_identifier: int | None = None,
    ) -> DicomVolume:
        check_render_cancelled()
        instances = series.instances
        if phase_identifier is not None:
            phase = series.phase_by_identifier(phase_identifier)
            if phase is None:
                raise VolumeBuildError(
                    "Unknown temporal phase: "
                    f"series_uid={series.series_instance_uid} "
                    f"phase={phase_identifier}"
                )
            instances = phase.instances

        fingerprint = series_fingerprint(replace(series, instances=instances))
        cached = self.get_volume(
            series.series_instance_uid,
            phase_identifier,
        )
        if cached is not None and cached.fingerprint == fingerprint:
            logger.debug(
                "Using cached volume: series_uid=%s phase=%s",
                series.series_instance_uid,
                phase_identifier,
            )
            return cached

        logger.info(
            "Building volume: series_uid=%s phase=%s instances=%d",
            series.series_instance_uid,
            phase_identifier,
            len(instances),
        )

        volume = self._build_volume(series, instances=instances)
        check_render_cancelled()
        volume.fingerprint = fingerprint
        self._volumes_by_series_uid[
            (series.series_instance_uid, phase_identifier)
        ] = volume
        self._trim_cache()
        return volume

    # DICOM instances
    #     → 解码 PixelData
    #     → Slope / Intercept 转换为模态值
    #     → 根据空间位置排序
    #     → 校验矩阵、间距和方向
    #     → stack 为 (slice, row, column)
    #     → 建立体素坐标到患者物理坐标的映射
    #     → 提取 Axial / Coronal / Sagittal

    @staticmethod
    def _validate_instances(instances:tuple[DicomInstanceMeta,...]):
        if len(instances) < 2:
            raise VolumeBuildError(
                "MPR requires at least two DICOM instances"
            )

        first = instances[0]

        if first.rows is None or first.columns is None:
            raise VolumeBuildError(
                "DICOM Rows or Columns is missing"
            )

        if first.pixel_spacing is None:
            raise VolumeBuildError(
                "DICOM PixelSpacing is missing"
            )

        if first.image_orientation_patient is None:
            raise VolumeBuildError(
                "DICOM ImageOrientationPatient is missing"
            )


    def _build_volume(
        self,
        series: DicomSeriesRecord,
        *,
        instances: tuple[DicomInstanceMeta, ...] | None = None,
    ) -> DicomVolume:
        instances = series.instances if instances is None else instances
        from qt_dicom_viewer.core.mr import validate_mr_series
        validate_mr_series(replace(series, instances=instances), volume=True)
        from qt_dicom_viewer.core.ct import ct_series_error
        if error := ct_series_error(replace(series, instances=instances), volume=True):
            raise VolumeBuildError(error)
        if any(i.samples_per_pixel > 1 or i.photometric_interpretation == "PALETTE COLOR" for i in instances):
            raise VolumeBuildError(_msg("viewer.colorVolumeUnsupported"))
        self._validate_instances(instances=instances)
        from qt_dicom_viewer.core.volume_view import validate_volume_series
        from qt_dicom_viewer.core.pet import validate_pet_2d_series
        validate_volume_series(replace(series, instances=instances))
        validate_pet_2d_series(series)
        if len({i.frame_of_reference_uid for i in instances}) != 1:
            raise VolumeBuildError(_msg('text.0151'))
        first = instances[0]


        orientation = np.asarray(
            first.image_orientation_patient,
            dtype=np.float64,
        )

        # DICOM IOP 前三项是列索引增加方向，后三项是行索引增加方向。
        column_index_direction = self._normalize(orientation[:3])
        row_index_direction = self._normalize(orientation[3:])

        slice_index_direction = self._normalize(
            np.cross(column_index_direction, row_index_direction)
        )

        positioned_instances: list[
            tuple[float, DicomInstanceMeta]
        ] = []

        for instance in instances:
            check_render_cancelled()
            self._validate_instance_geometry(
                instance=instance,
                rows=first.rows,
                columns=first.columns,
                row_spacing=first.pixel_spacing.row,
                column_spacing=first.pixel_spacing.column,
                orientation=orientation,
            )

            position = np.asarray(
                instance.image_position_patient,
                dtype=np.float64,
            )

            # 将切片位置投影到切片法向量上。
            spatial_position = float(
                np.dot(position, slice_index_direction)
            )

            positioned_instances.append(
                (spatial_position, instance)
            )

        positioned_instances.sort(
            key=lambda item: item[0]
        )

        spatial_positions = np.asarray(
            [
                position
                for position, _ in positioned_instances
            ],
            dtype=np.float64,
        )

        position_differences = np.diff(spatial_positions)

        if np.any(np.abs(position_differences) < 1e-6):
            raise VolumeBuildError(
                "Series contains duplicate slice positions"
            )

        slice_spacing = float(
            np.median(np.abs(position_differences))
        )

        if slice_spacing <= 0:
            raise VolumeBuildError(
                "Invalid slice spacing"
            )

        frames: list[np.ndarray] = []
        source_frames: list[np.ndarray] = []
        value_metas: list[PixelValueMeta] = []
        source_meta = None
        reference_dataset = None
        loader = DicomLoader()
        default_window: WindowLevel | None = None
        pet_windows: list[WindowLevel] = []
        pet_source_windows: list[WindowLevel] = []
        representative_meta: InstanceDisplayMeta | None = None

        for _, instance in positioned_instances:
            check_render_cancelled()
            dataset, modality_pixels = loader.read_frame(instance.path, instance.frame_index)

            if modality_pixels.ndim != 2:
                raise VolumeBuildError(
                    f"Only single-frame 2D instances are currently "
                    f"supported: path={instance.path}"
                )

            if modality_pixels.shape != (first.rows, first.columns):
                raise VolumeBuildError(
                    f"Inconsistent pixel matrix: path={instance.path} "
                    f"shape={modality_pixels.shape}"
                )

            source_frames.append(modality_pixels)
            display_pixels, value_meta, value_scale = loader.to_display_values(dataset, modality_pixels)
            value_metas.append(value_meta)
            if reference_dataset is None:
                reference_dataset = dataset
                if series.modality.upper() == "PT":
                    _, source_meta, _ = loader.to_display_values(dataset, modality_pixels, preferred_unit="source")
            if default_window is None:
                default_window = loader.resolve_window(
                    dataset=dataset,
                    target_window=None,
                    modality_pixels=display_pixels,
                    pixel_value_meta=value_meta,
                    value_scale=value_scale,
                )
                representative_meta = loader.extract_instance_meta(
                    dataset
                )

            if series.modality.upper() == "PT":
                pet_windows.append(loader.resolve_window(dataset, None, display_pixels,
                                                          value_meta, value_scale))
                if source_meta is not None:
                    pet_source_windows.append(loader.resolve_window(dataset, None, modality_pixels,
                                                                     source_meta, 1.0))

            frames.append(display_pixels)

        value_meta = value_metas[0]
        if series.modality.upper() == "MR" and len({m.unit for m in value_metas}) != 1:
            raise VolumeBuildError(_msg("mr.mixedUnits"))
        if series.modality.upper() == "PT":
            if len({m.source_unit for m in value_metas}) != 1:
                raise VolumeBuildError(_msg('text.0152'))
            if value_meta.source_unit == "BQML":
                warning = next((m.warning for m in value_metas if m.quantification == "unavailable"), None)
                if warning:
                    options = tuple(replace(o, available=False, warning=warning)
                                    if o.unit_id == "suvbw" else o
                                    for o in source_meta.unit_options)
                    source_meta = replace(source_meta, unit="Bq/ml", unit_id="source",
                                          scale_from_source=1.0, suv_type=None,
                                          quantification="unavailable", warning=warning,
                                          unit_options=options)
                    value_meta = source_meta
                    frames = source_frames
                    pet_windows = pet_source_windows
                elif not np.allclose([m.scale_from_source for m in value_metas], value_meta.scale_from_source,
                                     rtol=1e-6, atol=0):
                    warning = _msg('text.0153')
                    value_meta = replace(value_meta, warning=warning)
                    source_meta = replace(source_meta, warning=warning)
            elif len({(m.unit, m.suv_type) for m in value_metas}) != 1:
                raise VolumeBuildError(_msg('text.0154'))
            # A first slice with little uptake may carry a very narrow DICOM
            # window. Choose a single range covering the per-slice presets in
            # the final quantitative domain, then keep it fixed while browsing.
            upper = max(window.center + window.width / 2 for window in pet_windows)
            default_window = WindowLevel(upper / 2, upper)

        # 体数据轴顺序：(slice, row, column)
        check_render_cancelled()
        volume_pixels = np.ascontiguousarray(
            np.stack(frames, axis=0),
            dtype=np.float32,
        )

        if series.modality.upper() == "MR":
            # Source VOI values describe individual acquired frames, not a
            # reconstructed plane. A peripheral slice can have a tiny range.
            from qt_dicom_viewer.core.mr import automatic_mr_window
            default_window = automatic_mr_window(volume_pixels)

        first_ordered_instance = positioned_instances[0][1]
        origin = first_ordered_instance.image_position_patient

        if origin is None:
            raise VolumeBuildError(
                "First ordered instance has no position"
            )

        if default_window is None or representative_meta is None:
            raise VolumeBuildError(
                "Could not determine the volume display metadata"
            )

        return DicomVolume(
            modality_pixels=volume_pixels,
            geometry=VolumeGeometry(
                slice_count=volume_pixels.shape[0],
                rows=volume_pixels.shape[1],
                columns=volume_pixels.shape[2],
                row_spacing=first.pixel_spacing.row,
                column_spacing=first.pixel_spacing.column,
                slice_spacing=slice_spacing,
                origin_patient=origin,
                slice_index_direction_patient=self._to_vector3(
                    slice_index_direction
                ),
                row_index_direction_patient=self._to_vector3(
                    row_index_direction
                ),
                column_index_direction_patient=self._to_vector3(
                    column_index_direction
                ),
            ),
            series_uid=series.series_instance_uid,
            default_window=default_window,
            representative_instance_meta=representative_meta,
            suv_pixels=volume_pixels if value_meta.is_suv else None,
            suv_value_meta=value_meta if value_meta.is_suv else None,
            pixel_value_meta=value_meta,
            source_pixels=(np.ascontiguousarray(np.stack(source_frames), dtype=np.float32)
                           if value_meta.source_unit == "BQML" else None),
            source_value_meta=source_meta,
        )

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        length = float(np.linalg.norm(vector))

        if length <= 1e-8:
            raise VolumeBuildError(
                "Invalid zero-length direction vector"
            )

        return vector / length

    @staticmethod
    def _to_vector3(
            vector: np.ndarray,
    ) -> tuple[float, float, float]:
        if vector.shape != (3,):
            raise ValueError(
                f"Expected a 3D vector, got shape={vector.shape}"
            )

        return (
            float(vector[0]),
            float(vector[1]),
            float(vector[2]),
        )

    @staticmethod
    def _validate_instance_geometry(
        instance: DicomInstanceMeta,
        rows: int,
        columns: int,
        row_spacing: float,
        column_spacing: float,
        orientation: np.ndarray,
    ) -> None:
        if instance.rows != rows or instance.columns != columns:
            raise VolumeBuildError(
                f"Inconsistent Rows/Columns: path={instance.path}"
            )

        if instance.pixel_spacing is None:
            raise VolumeBuildError(
                f"Missing PixelSpacing: path={instance.path}"
            )

        if not np.allclose(
            [
                instance.pixel_spacing.row,
                instance.pixel_spacing.column,
            ],
            [row_spacing, column_spacing],
            rtol=1e-4,
            atol=1e-5,
        ):
            raise VolumeBuildError(
                f"Inconsistent PixelSpacing: path={instance.path}"
            )

        if instance.image_orientation_patient is None:
            raise VolumeBuildError(
                f"Missing ImageOrientationPatient: "
                f"path={instance.path}"
            )

        if not np.allclose(
            instance.image_orientation_patient,
            orientation,
            rtol=1e-4,
            atol=1e-5,
        ):
            raise VolumeBuildError(
                f"Inconsistent ImageOrientationPatient: "
                f"path={instance.path}"
            )

        if instance.image_position_patient is None:
            raise VolumeBuildError(
                f"Missing ImagePositionPatient: "
                f"path={instance.path}"
            )


def series_fingerprint(series: DicomSeriesRecord) -> str:
    entries = []
    for item in series.instances:
        check_render_cancelled()
        stat = item.path.stat()
        entries.append((item.sop_instance_uid, item.frame_index, item.image_position_patient,
                        item.image_orientation_patient, item.rows, item.columns,
                        item.pixel_spacing, item.frame_of_reference_uid,
                        str(item.path), stat.st_size, stat.st_mtime_ns))
    return sha256(repr(entries).encode()).hexdigest()
