from .display_mapping import DisplayMappingIntent
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .dicom_models import (
    MprPlane,
    MprProjectionMode,
    TabType,
    ViewportType,
)
from .dicom_types import PixelSpacing, WindowLevel, MrParameters


@dataclass(frozen=True, slots=True)
class DisplayStyle:
    color_map: str = "grayscale"
    no_data_color: str = "#000000"


@dataclass(frozen=True, slots=True)
class ViewportDisplaySettings:
    show_window_annotations: bool = True
    hide_sensitive_info: bool = False
    show_scale_bar: bool = True
    show_color_bar: bool = False
    show_dicom_overlay: bool = True
    show_localizer: bool = True
    fit_to_window: bool = True


class ViewportTransformAction(StrEnum):
    ROTATE_CLOCKWISE_90 = "rotate:cw90"
    ROTATE_COUNTERCLOCKWISE_90 = "rotate:ccw90"
    MIRROR_HORIZONTAL = "rotate:mirror-h"
    MIRROR_VERTICAL = "rotate:mirror-v"


@dataclass(frozen=True, slots=True)
class DicomInstanceMeta:
    path: Path
    patient_name: str
    patient_id: str
    study_description: str
    study_instance_uid: str
    series_description: str
    series_instance_uid: str
    series_number: int | None
    instance_number: int | None
    sop_instance_uid: str
    pixel_spacing: PixelSpacing | None
    modality: str
    rows: int | None
    columns: int | None
    transfer_syntax: str
    image_position_patient: (
        tuple[float, float, float] | None
    )
    image_orientation_patient: (
        tuple[float, float, float, float, float, float]
        | None
    )
    slice_thickness: float | None
    patient_sex: str = ""
    patient_age: str = ""
    acquisition_datetime: str = ""
    kvp: float | None = None
    tube_current_ma: float | None = None
    study_date: str = ""
    study_time: str = ""
    patient_id_issuer: str = ""
    sop_class_uid: str = ""
    photometric_interpretation: str = ""
    pet_series_type: tuple[str, ...] = ()
    pet_units: str = ""
    pet_suv_type: str = ""
    pet_corrected_image: tuple[str, ...] = ()
    pet_decay_correction: str = ""
    pet_2d_supported: bool = False
    pet_2d_support_error: str = ""
    frame_of_reference_uid: str = ""
    phase_values: tuple[tuple[str, int | float | str], ...] = ()
    number_of_temporal_positions: int | None = None
    number_of_phases: int | None = None
    number_of_frames: int = 1
    samples_per_pixel: int = 1
    mr_parameters: MrParameters | None = None
    frame_index: int | None = None
    mr_dimension_indices: tuple = ()
    mr_support_error: str = ""
    ct_frame_group: tuple = ()
    ct_dimension_indices: tuple = ()
    ct_support_error: str = ""
    media_storage_sop_instance_uid: str = ""

    @property
    def file_identity(self) -> tuple[str, str]:
        # Some exports reuse the dataset UID while retaining distinct file-meta
        # UIDs. Keep both source values; never rewrite the diagnostic metadata.
        return (self.sop_instance_uid,
                self.media_storage_sop_instance_uid or self.sop_instance_uid)

    @property
    def frame_identity(self) -> tuple[str, str, int | None]:
        return (*self.file_identity, self.frame_index)

    def phase_value(self, keyword: str) -> int | float | str | None:
        return next(
            (
                value
                for candidate_keyword, value in self.phase_values
                if candidate_keyword == keyword
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class DicomPhaseRecord:
    phase_identifier: int
    instances: tuple[DicomInstanceMeta, ...]

    @property
    def dicom_file_count(self) -> int:
        return len(self.instances)

@dataclass(frozen=True, slots=True)
class DicomSeriesRecord:
    patient_name: str
    patient_id: str
    study_description: str
    study_instance_uid: str
    series_description: str
    series_instance_uid: str
    series_number: int | None
    modality: str
    instances: tuple[DicomInstanceMeta, ...]
    study_date: str = ""
    study_time: str = ""
    patient_id_issuer: str = ""
    phases: tuple[DicomPhaseRecord, ...] = ()
    phase_source_keyword: str | None = None
    sop_class_uid: str = ""
    number_of_frames: int = 1
    photometric_interpretation: str = ""
    pet_series_type: tuple[str, ...] = ()
    pet_units: str = ""
    pet_suv_type: str = ""
    pet_corrected_image: tuple[str, ...] = ()
    pet_decay_correction: str = ""
    pet_2d_supported: bool = False
    pet_2d_support_error: str = ""
    frame_of_reference_uid: str = ""

    @property
    def dicom_file_count(self) -> int:
        return len(self.instances)

    @property
    def first_file(self) -> Path | None:
        return self.instances[0].path if self.instances else None

    @property
    def rows(self) -> int | None:
        return self.instances[0].rows if self.instances else None

    @property
    def columns(self) -> int | None:
        return self.instances[0].columns if self.instances else None

    @property
    def phase_identifiers(self) -> tuple[int, ...]:
        return tuple(
            phase.phase_identifier
            for phase in self.phases
        )

    @property
    def phase_count(self) -> int:
        return len(self.phases)

    @property
    def initial_phase_identifier(self) -> int | None:
        return next(
            (
                phase.phase_identifier
                for phase in self.phases
                if phase.instances
                and phase.instances[0].series_instance_uid
                    == self.series_instance_uid
            ),
            None,
        )

    @property
    def supports_four_d(self) -> bool:
        if len(self.phases) < 2:
            return False
        if any(
            instance.number_of_frames != 1
            for phase in self.phases
            for instance in phase.instances
        ):
            return False

        phase_lengths = {len(phase.instances) for phase in self.phases}
        if len(phase_lengths) != 1 or next(iter(phase_lengths)) < 2:
            return False

        return (
            self.phase_source_keyword is not None
            and self.initial_phase_identifier is not None
        )

    def phase_by_identifier(
        self,
        phase_identifier: int,
    ) -> DicomPhaseRecord | None:
        return next(
            (
                phase
                for phase in self.phases
                if phase.phase_identifier == phase_identifier
            ),
            None,
        )

    @property
    def display_name(self) -> str:
        parts: list[str] = []

        if self.series_number is not None:
            parts.append(f"Series {self.series_number}")

        if self.series_description:
            parts.append(self.series_description)

        if self.modality:
            parts.append(self.modality)

        return " / ".join(parts) or "Unnamed Series"


@dataclass(frozen=True)
class DicomFolderScanResult:
    folder: Path
    total_file_count: int
    dicom_file_count: int
    skipped_file_count: int
    series: list[DicomSeriesRecord]


@dataclass(frozen=True)
class DicomFolderScanSnapshot:
    folder: Path
    total_file_count: int
    dicom_file_count: int
    skipped_file_count: int
    series: list[DicomSeriesRecord]
    existing_file_count: int = 0

@dataclass(frozen=True, slots=True)
class SeriesDisplayMeta:
    patient_name: str
    patient_id: str
    study_description: str
    series_description: str
    modality: str
    series_uid: str
    phase_identifiers: tuple[int, ...] = ()
    supports_four_d: bool = False
    initial_phase_identifier: int | None = None
    slice_count: int = 0
    rows: int | None = None
    columns: int | None = None
    pixel_spacing: PixelSpacing | None = None
    series_number: int | None = None
    patient_sex: str = ""
    patient_age: str = ""
    acquisition_datetime: str = ""
    kvp: float | None = None
    tube_current_ma: float | None = None
    slice_thickness: float | None = None
    mr_parameters: MrParameters | None = None
    study_uid: str = ""
    frame_of_reference_uid: str = ""
    slice_geometries: tuple = ()
    supports_ct_analysis: bool = True
    is_color: bool = False
    color_calibrated: bool = False


@dataclass(frozen=True, slots=True)
class ViewportConfig:
    viewport_id: str
    tab_id: str
    viewport_type: ViewportType
    series_uid: str
    series_meta: SeriesDisplayMeta
    role: str = "image"

@dataclass(frozen=True)
class ViewportState:
    slice_index: int | None # None为了mpr请求的时候能够直接被设置为居中位置。
    slice_count: int | None
    window: WindowLevel | None = None
    width: float = 1.0
    height: float = 0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    rotation_degrees: float = 0.0
    horizontal_flip: bool = False
    vertical_flip: bool = False
    inverted: bool = False
    display_mapping: DisplayMappingIntent = field(default_factory=DisplayMappingIntent)
    display_style: DisplayStyle = field(
        default_factory=DisplayStyle
    )
    display_settings: ViewportDisplaySettings = field(
        default_factory=ViewportDisplaySettings
    )


@dataclass(frozen=True, slots=True)
class TabConfig:
    tab_id: str
    tab_label: str
    tab_type: TabType
    series_metas: tuple[SeriesDisplayMeta, ...]


class ToolBehavior(StrEnum):
    INTERACTION = "interaction" # 只触发长期功能
    PANEL = "panel"    # 只打开面板
    INTERACTION_PANEL = "interactionPanel" # 触发长期功能且打开面板
    COMMAND = "command"  # 一次性命令，比如reset
    TOGGLE = "toggle"  # 独立状态，不替换当前交互或面板


class InteractionType(StrEnum):
    SEGMENTATION = "mpr:segmentation"
    VOI = "mpr:voi"
    SERVICE_MTF = "service:mtf"
    SERVICE_FWHM = "service:fwhm"
    SERVICE_QA = "service:qa"
    NONE = ""
    WINDOW = "window"
    SCROLL = "scroll"
    PAN = "pan"
    ZOOM = "zoom"
    MEASURE_LENGTH = "measure:length"
    ANNOTATE_ARROW = "annotate:arrow"
    MEASURE_ANGLE = "measure:angle"
    MEASURE_RECT = "measure:rect"
    MEASURE_ELLIPSE = "measure:ellipse"
    MEASURE_CURVE = "measure:curve"
    MEASURE_FREEHAND = "measure:freehand"
    ANNOTATE_TEXT = "annotate:text"
    MPR_ROTATE_3D = "mpr:rotate3d"
    VOLUME_ROTATE = "volume:rotate"
    VOLUME_CROP = "volume:crop"

@dataclass(frozen=True, slots=True)
class WindowPreset:
    preset_id: str
    label: str
    center: float
    width: float
    modality: str = "CT"


@dataclass(frozen=True, slots=True)
class CrosshairColor:
    horizontal: str
    vertical: str


@dataclass(frozen=True, slots=True)
class CrosshairStyle:
    color: CrosshairColor
    centerGap: int = 14
    lineWidth: int= 1


@dataclass(frozen=True, slots=True)
class MprProjectionSettings:
    enabled: bool = False
    mode: MprProjectionMode = MprProjectionMode.MIP
    axial_thickness_mm: int = 0
    coronal_thickness_mm: int = 0
    sagittal_thickness_mm: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("MPR projection enabled must be a boolean")
        if not isinstance(self.mode, MprProjectionMode):
            raise ValueError("Invalid MPR projection mode")
        for thickness in (
            self.axial_thickness_mm,
            self.coronal_thickness_mm,
            self.sagittal_thickness_mm,
        ):
            if (
                isinstance(thickness, bool)
                or not isinstance(thickness, int)
                or not 0 <= thickness <= 100
            ):
                raise ValueError(
                    "MPR projection thickness must be an integer "
                    "between 0 and 100 mm"
                )

    def thickness_for_plane(self, plane: MprPlane) -> int:
        match plane:
            case MprPlane.AXIAL:
                return self.axial_thickness_mm
            case MprPlane.CORONAL:
                return self.coronal_thickness_mm
            case MprPlane.SAGITTAL:
                return self.sagittal_thickness_mm
            case _:
                raise ValueError(f"Unsupported MPR plane: {plane}")

    def effective_projection_for_plane(
        self,
        plane: MprPlane,
    ) -> tuple[MprProjectionMode | None, int]:
        thickness = self.thickness_for_plane(plane)
        if not self.enabled or thickness == 0:
            return None, 0
        return self.mode, thickness
