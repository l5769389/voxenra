from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import TypeAlias

import numpy as np

from .dicom_types import ImageGeometryMeta
from .image_geometry import ImagePoint


class AnglePointIndex(IntEnum):
    START = 0
    VERTEX = 1
    END = 2


class LinePointIndex(IntEnum):
    START = 0
    END = 1


class MeasurementKind(StrEnum):
    LENGTH = "length"
    ARROW = "arrow"
    ANGLE = "angle"
    RECT = "rect"
    ELLIPSE = "ellipse"
    CURVE = "curve"
    FREEHAND = "freehand"


class EditTargetKind(StrEnum):
    """描述命中部位，不描述拖动动作；不同部位可以执行相同的整体移动。"""

    CONTROL_POINT = "controlPoint"
    OUTLINE = "outline"
    INTERIOR = "interior"
    LABEL = "label"


@dataclass(frozen=True, slots=True)
class MeasurementEditTarget:
    """index：控制点编号或直线边编号；椭圆轮廓、内部、标签不使用编号。

    长度控制点：起点 0、终点 1；角度：起点 0、顶点 1、终点 2。
    ROI 控制点：按 roi_corners 的顺序编号 0～3。
    轮廓边：长度为 0，角度为 0～1，矩形为 0～3（含闭合边）。
    """

    kind: EditTargetKind
    index: int | None = None


@dataclass(frozen=True, slots=True)
class MeasurementHit:
    """所属测量 + 命中部位 + 部位内编号。

    distance 是到控制点/轮廓的图像像素距离；包含型命中（内部、标签）为 0。
    不同部位按优先级选择，不跨部位比较距离。
    """

    measurement_id: str
    target: MeasurementEditTarget
    distance: float


@dataclass(frozen=True, slots=True)
class MeasurementLabelRegion:
    """QML 提供的标签矩形，使用视口坐标，不能当作图像坐标参与轮廓计算。"""

    measurement_id: str
    x: float
    y: float
    width: float
    height: float


@dataclass(slots=True)
class LengthMeasurementDraft:
    measurement_id: str
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    points: list[ImagePoint]
    length_mm: float
    kind: MeasurementKind = MeasurementKind.LENGTH


@dataclass(slots=True)
class AngleMeasurementDraft:
    measurement_id: str
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    points: list[ImagePoint]
    angle: float


@dataclass(frozen=True, slots=True)
class RoiMetrics:
    """面积是完整轮廓的几何面积；统计值只来自 ROI 内有效像素中心。"""

    width_mm: float | None = None
    height_mm: float | None = None
    area_mm2: float | None = None
    pixel_count: int = 0
    mean: float | None = None
    std: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    perimeter_mm: float | None = None


@dataclass(slots=True)
class RoiMeasurementDraft:
    measurement_id: str
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    kind: MeasurementKind
    points: list[ImagePoint]
    metrics: RoiMetrics
    smooth: bool = False


MeasurementDraft: TypeAlias = (
    LengthMeasurementDraft
    | AngleMeasurementDraft
    | RoiMeasurementDraft
)


@dataclass(frozen=True, slots=True)
class LengthMeasurement:
    measurement_id: str
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    points: tuple[ImagePoint, ...]
    length_mm: float
    kind: MeasurementKind = MeasurementKind.LENGTH


@dataclass(frozen=True, slots=True)
class AngleMeasurement:
    measurement_id: str
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    points: tuple[ImagePoint, ...]
    angle: float


@dataclass(frozen=True, slots=True)
class RoiMeasurement:
    measurement_id: str
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    kind: MeasurementKind
    points: tuple[ImagePoint, ...]
    metrics: RoiMetrics
    smooth: bool = False


Measurement: TypeAlias = (
    LengthMeasurement
    | AngleMeasurement
    | RoiMeasurement
)


@dataclass(frozen=True, slots=True)
class MeasureContext:
    measurement_kind: MeasurementKind
    series_uid: str
    sop_instance_uid: str
    slice_index: int
    geometry: ImageGeometryMeta
    endpoint_tolerance: float
    line_tolerance: float
    # 引用当前原始/重采样的模态像素，不是调窗后的显示灰度；操作只读。
    modality_pixels: np.ndarray | None = None
    pixel_unit: str = ""


@dataclass(slots=True)
class CreateMeasurementTransaction:
    context: MeasureContext
    draft: MeasurementDraft
    target: MeasurementEditTarget


@dataclass(slots=True)
class EditMeasurementTransaction:
    context: MeasureContext
    draft: MeasurementDraft
    target: MeasurementEditTarget


MeasurementTransaction: TypeAlias = (
    CreateMeasurementTransaction
    | EditMeasurementTransaction
)
