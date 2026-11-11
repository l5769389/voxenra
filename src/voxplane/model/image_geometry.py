from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

@dataclass(frozen=True, slots=True)
class Offset:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class ImagePoint:
    column: float
    row: float

@dataclass(frozen=True, slots=True)
class PointerPosition:
    viewport: Point  # 视口坐标
    image: ImagePoint | None  # 图像坐标




@dataclass(frozen=True, slots=True)
class DragUpdateEvent:
    start_position: PointerPosition
    current_position: PointerPosition
    step_offset: Offset
    total_offset: Offset