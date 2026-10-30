from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .dicom_types import WindowLevel
from .dicom_core import Vector3
from .image_geometry import ImagePoint, Point, PointerPosition
from .measure import MeasureContext


@dataclass(frozen=True, slots=True)
class SliceIndexChange:
    slice_index: int


@dataclass(frozen=True, slots=True)
class WindowLevelChange:
    window: WindowLevel
    inverted: bool


@dataclass(frozen=True, slots=True)
class PanChange:
    offset_x: float
    offset_y: float


@dataclass(frozen=True, slots=True)
class ZoomChange:
    zoom: float


@dataclass(frozen=True, slots=True)
class RotationChange:
    degrees: float


@dataclass(frozen=True, slots=True)
class CrosshairCenterChange:
    position: ImagePoint


@dataclass(frozen=True, slots=True)
class CrosshairRotationChange:
    """一次十字线拖动产生的增量角，使用屏幕顺时针为正。"""

    angle_delta_radians: float


@dataclass(frozen=True, slots=True)
class Mpr3DRotationChange:
    """一次三维拖动产生的患者空间轴角增量。"""

    axis_patient: Vector3
    angle_delta_radians: float


InteractionResult: TypeAlias = (
    SliceIndexChange
    | WindowLevelChange
    | PanChange
    | ZoomChange
    | RotationChange
    | CrosshairCenterChange
    | CrosshairRotationChange
    | Mpr3DRotationChange
)


@dataclass(frozen=True, slots=True)
class WindowLevelContext:
    viewport_size: tuple[float, float]
    inverted: bool
    current_window: WindowLevel | None


@dataclass(frozen=True, slots=True)
class ScrollContext:
    slice_index: int
    slice_count: int


@dataclass(frozen=True, slots=True)
class PanContext:
    current_pan_x: float
    current_pan_y: float


@dataclass(frozen=True, slots=True)
class ZoomContext:
    viewport_size: tuple[float, float]
    current_zoom: float


@dataclass(frozen=True, slots=True)
class RotationContext:
    center: Point
    current_degrees: float


@dataclass(frozen=True, slots=True)
class CrosshairMoveContext:
    current_pan_x: float
    current_pan_y: float


@dataclass(frozen=True, slots=True)
class CrosshairRotationContext:
    center: ImagePoint
    row_spacing: float
    column_spacing: float


@dataclass(frozen=True, slots=True)
class Mpr3DRotationContext:
    """当前视图内旋转所需的中心、物理间距和切面法向。"""

    center: ImagePoint
    row_spacing: float
    column_spacing: float
    normal_direction_patient: Vector3


@dataclass(frozen=True, slots=True)
class PointerHoverContext:
    """指针 hover 命中测试所需的统一上下文。"""

    position: PointerPosition
    point_tolerance: float
    line_tolerance: float


OperationStartContext: TypeAlias = (
    WindowLevelContext
    | ScrollContext
    | PanContext
    | ZoomContext
    | RotationContext
    | MeasureContext
    | CrosshairMoveContext
    | CrosshairRotationContext
    | Mpr3DRotationContext
)


class CrosshairTargetKind(StrEnum):
    """指针命中的十字线几何部位。"""

    CENTER = "center"
    HORIZONTAL_LINE = "horizontalLine"
    VERTICAL_LINE = "verticalLine"
