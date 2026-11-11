"""MPR 坐标架在患者空间中的纯旋转数学。"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite

import numpy as np

from voxplane.model.dicom_core import (
    MprFrame,
    MprGridAnchor,
    MprGridSpec,
    MprSamplingBasis,
    MprState,
    MprViewRolls,
    MprViewAnchors,
    Vector3,
)
from voxplane.model.dicom_models import MprPlane

def axis_angle_rotation_matrix(
    axis_patient: Vector3,
    angle_radians: float,
) -> np.ndarray:
    """返回遵循右手规则的患者空间旋转矩阵。

    ``axis_patient`` 是患者 LPS 坐标中的方向，向量长度会被忽略；
    ``angle_radians`` 表示绕归一化旋转轴、遵循右手规则的弧度角。
    函数会检查输入、归一化旋转轴，再用 Rodrigues 公式
    构造旋转矩阵。
    """
    axis = np.asarray(axis_patient, dtype=np.float64)
    if axis.shape != (3,) or not np.all(np.isfinite(axis)):
        raise ValueError("Rotation axis must be a finite 3D vector")
    if not isfinite(angle_radians):
        raise ValueError("Rotation angle must be finite")

    axis_norm = float(np.linalg.norm(axis))
    if axis_norm <= np.finfo(np.float64).eps:
        raise ValueError("Rotation axis must be non-zero")

    x, y, z = axis / axis_norm
    cosine = float(np.cos(angle_radians))
    sine = float(np.sin(angle_radians))
    one_minus_cosine = 1.0 - cosine

    return np.asarray(
        (
            (
                cosine + x * x * one_minus_cosine,
                x * y * one_minus_cosine - z * sine,
                x * z * one_minus_cosine + y * sine,
            ),
            (
                y * x * one_minus_cosine + z * sine,
                cosine + y * y * one_minus_cosine,
                y * z * one_minus_cosine - x * sine,
            ),
            (
                z * x * one_minus_cosine - y * sine,
                z * y * one_minus_cosine + x * sine,
                cosine + z * z * one_minus_cosine,
            ),
        ),
        dtype=np.float64,
    )


def rotate_mpr_frame_about_axis(
    frame: MprFrame,
    axis_patient: Vector3,
    angle_radians: float,
) -> MprFrame:
    """让 MPR 坐标架绕一条穿过自身中心的患者空间轴旋转。

    中心保持不变；U、V、W 同时应用相同的患者空间旋转，
    因而三根轴之间的相对方向保持不变。
    """
    rotation = axis_angle_rotation_matrix(
        axis_patient,
        angle_radians,
    )
    basis = np.column_stack(
        (
            frame.u_direction_patient,
            frame.v_direction_patient,
            frame.w_direction_patient,
        )
    )
    rotated_basis = rotation @ basis

    return MprFrame(
        center_patient=frame.center_patient,
        u_direction_patient=_vector3(rotated_basis[:, 0]),
        v_direction_patient=_vector3(rotated_basis[:, 1]),
        w_direction_patient=_vector3(rotated_basis[:, 2]),
    )


def rotate_mpr_frame_about_plane_normal(
    frame: MprFrame,
    plane: MprPlane,
    angle_radians: float,
) -> MprFrame:
    """让坐标架绕指定 MPR 平面的当前法线旋转。

    Axial 使用 W，Coronal 使用 V，Sagittal 使用 U。旋转轴从传入的
    Frame 中取得，因此该函数同样适用于已经倾斜的 MPR 坐标架。
    """
    match plane:
        case MprPlane.AXIAL:
            axis_patient = frame.w_direction_patient
        case MprPlane.CORONAL:
            axis_patient = frame.v_direction_patient
        case MprPlane.SAGITTAL:
            axis_patient = frame.u_direction_patient
        case _:
            raise ValueError(f"Unsupported MPR plane: {plane}")

    return rotate_mpr_frame_about_axis(
        frame,
        axis_patient,
        angle_radians,
    )


def rotate_mpr_state_3d(
    state: MprState,
    axis_patient: Vector3,
    angle_radians: float,
) -> MprState:
    """执行真正的三维旋转：整个 MPR 坐标架同步旋转。

    三个视图自身已有的平面内补偿角保持不变。因为 Frame 的 U/V/W
    全部旋转，所以 Axial、Coronal、Sagittal 都需要重新采样。
    """
    return MprState(
        frame=rotate_mpr_frame_about_axis(
            state.frame,
            axis_patient,
            angle_radians,
        ),
        view_rolls=state.view_rolls,
        view_grids=state.view_grids,
        view_anchors=state.view_anchors,
    )


def rotate_crosshair_state(
    state: MprState,
    source_plane: MprPlane,
    angle_radians: float,
) -> MprState:
    """旋转十字线，同时保持发起旋转的视图采样平面不变。

    先让共享 Frame 绕源视图法线旋转 ``angle_radians``，使另外两个
    正交平面跟着变化；再给源视图增加相反的平面内补偿角。两次旋转
    在源视图中相互抵消，因此其最终采样基轴不变。
    """
    rotated_frame = rotate_mpr_frame_about_plane_normal(
        state.frame,
        source_plane,
        angle_radians,
    )
    compensated_rolls = _add_view_roll(
        state,
        source_plane,
        -angle_radians,
    )
    return MprState(
        frame=rotated_frame,
        view_rolls=compensated_rolls,
        view_grids=state.view_grids,
        view_anchors=state.view_anchors,
    )


def resolve_sampling_basis(
    state: MprState,
    plane: MprPlane,
) -> MprSamplingBasis:
    """解析一个视图最终用于重采样的患者空间基轴。

    先从共享 Frame 得到该视图的标准 row/column/navigation 方向，
    再让 row 和 column 绕 navigation 应用该视图自己的补偿角。
    """
    row_mpr, column_mpr, navigation_mpr = _canonical_plane_axes(plane)
    frame = state.frame
    row_patient = np.asarray(
        frame.direction_to_patient(row_mpr),
        dtype=np.float64,
    )
    column_patient = np.asarray(
        frame.direction_to_patient(column_mpr),
        dtype=np.float64,
    )
    navigation_patient = np.asarray(
        frame.direction_to_patient(navigation_mpr),
        dtype=np.float64,
    )

    roll = state.view_rolls.for_plane(plane)
    if roll != 0.0:
        rotation = axis_angle_rotation_matrix(
            _vector3(navigation_patient),
            roll,
        )
        row_patient = rotation @ row_patient
        column_patient = rotation @ column_patient

    return MprSamplingBasis(
        row_direction_patient=_vector3(row_patient),
        column_direction_patient=_vector3(column_patient),
        navigation_direction_patient=_vector3(navigation_patient),
    )


def move_mpr_state_center(
    state: MprState,
    center_patient: Vector3,
) -> MprState:
    """移动 MPR 中心，同时保持各视图的网格采样原点连续。

    新中心在每个视图 row/column 方向上的位移会累加到
    该视图的 anchor。因此源视图平面内拖动时影像保持不动，
    只有十字线移到新的网格索引。
    """
    center = np.asarray(center_patient, dtype=np.float64)
    if center.shape != (3,) or not np.all(np.isfinite(center)):
        raise ValueError("MPR center must be a finite 3D point")

    previous_center = np.asarray(
        state.frame.center_patient,
        dtype=np.float64,
    )
    delta_patient = center - previous_center
    grids = state.view_grids
    anchors = state.view_anchors
    if grids is not None:
        anchors = anchors or MprViewAnchors.centered(grids)
        anchors = MprViewAnchors(
            axial=_translated_anchor(
                state,
                MprPlane.AXIAL,
                anchors.axial,
                grids.axial,
                delta_patient,
            ),
            coronal=_translated_anchor(
                state,
                MprPlane.CORONAL,
                anchors.coronal,
                grids.coronal,
                delta_patient,
            ),
            sagittal=_translated_anchor(
                state,
                MprPlane.SAGITTAL,
                anchors.sagittal,
                grids.sagittal,
                delta_patient,
            ),
        )

    return MprState(
        frame=replace(
            state.frame,
            center_patient=_vector3(center),
        ),
        view_rolls=state.view_rolls,
        view_grids=grids,
        view_anchors=anchors,
    )


def _translated_anchor(
    state: MprState,
    plane: MprPlane,
    anchor: MprGridAnchor,
    grid: MprGridSpec,
    delta_patient: np.ndarray,
) -> MprGridAnchor:
    basis = resolve_sampling_basis(state, plane)
    row_delta = float(
        np.dot(delta_patient, basis.row_direction_patient)
    )
    column_delta = float(
        np.dot(delta_patient, basis.column_direction_patient)
    )
    return MprGridAnchor(
        column=anchor.column + column_delta / grid.column_spacing,
        row=anchor.row + row_delta / grid.row_spacing,
    )


def _add_view_roll(
    state: MprState,
    plane: MprPlane,
    delta_radians: float,
) -> MprViewRolls:
    rolls = state.view_rolls
    match plane:
        case MprPlane.AXIAL:
            return replace(
                rolls,
                axial_radians=rolls.axial_radians + delta_radians,
            )
        case MprPlane.CORONAL:
            return replace(
                rolls,
                coronal_radians=rolls.coronal_radians + delta_radians,
            )
        case MprPlane.SAGITTAL:
            return replace(
                rolls,
                sagittal_radians=rolls.sagittal_radians + delta_radians,
            )
        case _:
            raise ValueError(f"Unsupported MPR plane: {plane}")


def _canonical_plane_axes(
    plane: MprPlane,
) -> tuple[Vector3, Vector3, Vector3]:
    """返回图像向下、向右、翻到下一层的 MPR 局部方向。"""
    match plane:
        case MprPlane.AXIAL:
            return (
                (0.0, 1.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
            )
        case MprPlane.CORONAL:
            return (
                (0.0, 0.0, -1.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            )
        case MprPlane.SAGITTAL:
            return (
                (0.0, 0.0, -1.0),
                (0.0, 1.0, 0.0),
                (1.0, 0.0, 0.0),
            )
        case _:
            raise ValueError(f"Unsupported MPR plane: {plane}")


def _vector3(vector: np.ndarray) -> Vector3:
    return (
        float(vector[0]),
        float(vector[1]),
        float(vector[2]),
    )
