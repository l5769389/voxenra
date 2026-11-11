from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians, sin, sqrt
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ImageEdgeDirectionLabels:
    top: str = ""
    right: str = ""
    bottom: str = ""
    left: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "left": self.left,
        }


def patient_direction_to_label(
    direction: Sequence[float],
    *,
    component_threshold: float = 1e-4,
) -> str:
    """将患者 LPS 方向向量转换为 DICOM 方向标签。

    对于 BIPED 患者，LPS 三个正轴分别指向左侧、后侧和头侧。
    斜位方向可以包含多个字母，并按照归一化分量的绝对值从大到小排列。
    """
    if len(direction) != 3:
        raise ValueError("Patient direction must contain three components")
    if not 0.0 <= component_threshold < 1.0:
        raise ValueError("Component threshold must be in [0, 1)")

    x, y, z = (float(component) for component in direction)
    if not all(isfinite(component) for component in (x, y, z)):
        return ""

    length = sqrt(x * x + y * y + z * z)
    if length <= 1e-12:
        return ""

    normalized = (x / length, y / length, z / length)
    components = [
        (abs(normalized[0]), "L" if normalized[0] >= 0.0 else "R"),
        (abs(normalized[1]), "P" if normalized[1] >= 0.0 else "A"),
        (abs(normalized[2]), "H" if normalized[2] >= 0.0 else "F"),
    ]
    components.sort(key=lambda component: component[0], reverse=True)

    return "".join(
        label
        for magnitude, label in components
        if magnitude > component_threshold
    )


def displayed_image_edge_labels(
    image_orientation_patient: Sequence[float],
    *,
    rotation_degrees: float = 0.0,
    horizontal_flip: bool = False,
    vertical_flip: bool = False,
) -> ImageEdgeDirectionLabels:
    """计算显示图像上、右、下、左四条边对应的患者方向标签。

    IOP 的第一个方向向量指向图像列索引增加方向，第二个方向向量指向
    图像行索引增加方向。显示变换按照先镜像、后正角度旋转的顺序应用；
    在 QML 的屏幕坐标系中，正角度表现为顺时针旋转。
    """
    if len(image_orientation_patient) != 6:
        raise ValueError("Image Orientation Patient must contain six values")

    orientation = tuple(
        float(component)
        for component in image_orientation_patient
    )
    if not all(isfinite(component) for component in orientation):
        return ImageEdgeDirectionLabels()
    if not isfinite(rotation_degrees):
        return ImageEdgeDirectionLabels()

    column_direction = orientation[:3]
    row_direction = orientation[3:]
    angle = radians(rotation_degrees % 360.0)
    cosine = cos(angle)
    sine = sin(angle)
    horizontal_sign = -1.0 if horizontal_flip else 1.0
    vertical_sign = -1.0 if vertical_flip else 1.0

    # screen_to_image = flip @ inverse(rotation)。下面的系数表示屏幕向右和
    # 屏幕向下在未变换图像坐标系中的方向。
    right_column = horizontal_sign * cosine
    right_row = -vertical_sign * sine
    down_column = horizontal_sign * sine
    down_row = vertical_sign * cosine

    right_patient = tuple(
        column_direction[index] * right_column
        + row_direction[index] * right_row
        for index in range(3)
    )
    bottom_patient = tuple(
        column_direction[index] * down_column
        + row_direction[index] * down_row
        for index in range(3)
    )

    return ImageEdgeDirectionLabels(
        top=patient_direction_to_label(
            tuple(-component for component in bottom_patient)
        ),
        right=patient_direction_to_label(right_patient),
        bottom=patient_direction_to_label(bottom_patient),
        left=patient_direction_to_label(
            tuple(-component for component in right_patient)
        ),
    )
