from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import TypeAlias

import numpy as np

from .dicom_core import (
    MprFrame,
    MprGridAnchor,
    MprGridSpec,
    MprImageGeometry,
    MprViewGrids,
    DicomVolume,
)
from .dicom_models import (
    MprPlane,
    MprProjectionMode,
    TwoDViewType,
    ViewportType,
)
from .dicom_types import FrameDisplayMeta, WindowLevel
from .display_mapping import DisplayMappingIntent
from .dicom_core import MprState


@dataclass(frozen=True, slots=True, kw_only=True)
class VolumeLoadRequest:
    request_id: str
    viewport_id: str
    series_uid: str
    value_unit: str | None = None
    cancel_event: Event | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class VolumeLoadResult:
    response_id: str
    viewport_id: str
    series_uid: str
    volume: DicomVolume

# 为什么基础类使用 kw_only=True
# 这样所有字段都必须显式按名称传递：
# kw_only=True 还能避免 dataclass 继承时常见的字段顺序问题，例如基础类有默认值，而子类又添加没有默认值的字段。
@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class _RenderRequestBase:
    request_id: str
    viewport_id: str
    series_uid: str
    window: WindowLevel | None
    inverted: bool
    color_map: str = "grayscale"
    display_mapping: DisplayMappingIntent = field(default_factory=DisplayMappingIntent)
    cancel_event: Event | None = field(default=None, compare=False, repr=False)


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class StackRenderRequest(_RenderRequestBase):
    slice_index: int
    value_unit: str | None = None

    @property
    def view_type(self) -> ViewportType:
        return TwoDViewType.STACK


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class MontageRenderRequest(_RenderRequestBase):
    slice_index: int

    @property
    def view_type(self) -> ViewportType:
        return TwoDViewType.MONTAGE


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class MprRenderRequest(_RenderRequestBase):
    plane: MprPlane
    mpr_frame: MprFrame | None
    phase_identifier: int | None = None
    view_roll_radians: float = 0.0
    mpr_grid: MprGridSpec | None = None
    mpr_grid_anchor: MprGridAnchor | None = None
    projection_mode: MprProjectionMode | None = None
    slab_thickness_mm: float = 0.0
    value_unit: str | None = None

    @property
    def view_type(self) -> ViewportType:
        return self.plane


@dataclass(frozen=True, slots=True, kw_only=True)
class PetBatchRenderRequest:
    request_id: str
    viewport_id: str  # owning tab; one coalesced request per linked group
    series_uid: str  # PET
    viewports: tuple[tuple[str, str], ...]
    ct_series_uid: str | None = None
    state: MprState | None = None
    plane: MprPlane = MprPlane.AXIAL
    value_unit: str | None = None
    pet_window: WindowLevel | None = None
    ct_window: WindowLevel | None = None
    ct_inverted: bool = False
    transform: tuple[float, ...] = tuple(np.eye(4).ravel())
    opacity: float = 0.5
    pet_color_map: str = "grayscale"
    fusion_color_map: str = "hotIron"
    preview: bool = False
    interaction_id: str = ""
    interaction_kind: str = ""  # registration / locator; preview only means reduced MIP sampling
    interaction_final: bool = False
    revision: int = 0
    # Assigned by RenderService; not part of display intent or equality.
    cancel_event: Event | None = field(default=None, compare=False, repr=False)


RenderRequest: TypeAlias = (
    StackRenderRequest
    | MontageRenderRequest
    | MprRenderRequest
    | VolumeLoadRequest
    | PetBatchRenderRequest
)


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class _RenderResultBase:
    response_id: str
    viewport_id: str
    series_uid: str
    view_type: ViewportType
    image: np.ndarray | None
    modality_pixel: np.ndarray | None
    frame_meta: FrameDisplayMeta


@dataclass(frozen=True, slots=True, kw_only=True)
class MprRenderResult(_RenderResultBase):
    mpr_frame: MprFrame | None
    plane_geometry: MprImageGeometry | None
    volume: DicomVolume | None = None
    phase_identifier: int | None = None
    projection_mode: MprProjectionMode | None = None
    slab_thickness_mm: float = 0.0
    mpr_view_grids: MprViewGrids | None = None
    content_key: tuple | None = None  # immutable sampling + display identity, independent of cursor position


@dataclass(frozen=True, slots=True, kw_only=True)
class StackRenderResult(_RenderResultBase):
    ...


@dataclass(frozen=True, slots=True, kw_only=True)
class MontageRenderResult(_RenderResultBase):
    slice_index: int

    @property
    def image_key(self) -> str:
        return f"{self.viewport_id}:slice:{self.slice_index}"


@dataclass(frozen=True, slots=True, kw_only=True)
class PetMipRenderResult(MprRenderResult):
    peak_positions: np.ndarray
    preview: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class PetBatchRenderResult:
    response_id: str
    viewport_id: str
    series_uid: str
    frames: tuple[MprRenderResult, ...]
    state: MprState
    pet_volume: DicomVolume
    ct_volume: DicomVolume | None
    pet_window: WindowLevel
    ct_window: WindowLevel | None
    ct_samples: np.ndarray | None = None
    warning: str = ""
    request: PetBatchRenderRequest | None = None


RenderResult: TypeAlias = (
    StackRenderResult
    | MontageRenderResult
    | MprRenderResult
    | VolumeLoadResult
    | PetBatchRenderResult
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderFailure:
    request_id: str
    viewport_id: str
    error: Exception
