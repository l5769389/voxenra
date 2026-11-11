"""MPR 旋转中仅涉及坐标架部分的可执行规则。

这些测试有意停留在 ``MprFrame`` 数学层：

* 3D 旋转保持 Frame 中心不变，并对三根轴应用同一个患者空间旋转。
* 十字线旋转以操作平面的法线为轴，因此 Axial 保持 W 不变，
  Coronal 保持 V 不变，Sagittal 保持 U 不变。
* 所有结果仍然是正交、右手的坐标架。

Viewport 采样补偿、重采样、Controller 和 QML 不在本测试模块范围内。
"""

from math import pi

import numpy as np
import pytest

from voxplane.core.mpr_rotation import (
    axis_angle_rotation_matrix,
    resolve_sampling_basis,
    rotate_crosshair_state,
    rotate_mpr_frame_about_axis,
    rotate_mpr_frame_about_plane_normal,
    rotate_mpr_state_3d,
)
from voxplane.model import MprPlane, MprState, MprViewRolls
from voxplane.model.dicom_core import MprFrame


def _basis(frame: MprFrame) -> np.ndarray:
    return np.column_stack(
        (
            frame.u_direction_patient,
            frame.v_direction_patient,
            frame.w_direction_patient,
        )
    )


def test_3d_rotation_keeps_center_and_rotates_every_frame_axis() -> None:
    """3D 旋转对 U、V、W 应用同一个患者空间旋转。"""
    frame = MprFrame.standard_lps((12.0, 22.0, 32.0))
    axis = (1.0, 2.0, 3.0)
    angle = 0.37
    rotation = axis_angle_rotation_matrix(axis, angle)

    rotated = rotate_mpr_frame_about_axis(frame, axis, angle)

    assert rotated.center_patient == frame.center_patient
    np.testing.assert_allclose(
        _basis(rotated),
        rotation @ _basis(frame),
        atol=1e-12,
    )


@pytest.mark.parametrize(
    ("plane", "expected_u", "expected_v", "expected_w"),
    (
        (
            MprPlane.AXIAL,
            (0.0, 1.0, 0.0),
            (-1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        (
            MprPlane.CORONAL,
            (0.0, 0.0, -1.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ),
        (
            MprPlane.SAGITTAL,
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, -1.0, 0.0),
        ),
    ),
)

def test_crosshair_rotation_uses_the_displayed_plane_normal(
    plane: MprPlane,
    expected_u: tuple[float, float, float],
    expected_v: tuple[float, float, float],
    expected_w: tuple[float, float, float],
) -> None:
    """正向 90 度旋转遵循患者空间右手规则。"""
    frame = MprFrame.standard_lps((4.0, 5.0, 6.0))

    rotated = rotate_mpr_frame_about_plane_normal(
        frame,
        plane,
        pi / 2.0,
    )

    assert rotated.center_patient == frame.center_patient
    np.testing.assert_allclose(
        rotated.u_direction_patient,
        expected_u,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        rotated.v_direction_patient,
        expected_v,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        rotated.w_direction_patient,
        expected_w,
        atol=1e-12,
    )


def test_plane_normal_is_resolved_from_the_current_frame() -> None:
    """平面旋转使用倾斜 Frame 的当前轴，而不是固定 LPS 轴。"""
    initial = MprFrame.standard_lps((7.0, 8.0, 9.0))
    oblique = rotate_mpr_frame_about_axis(
        initial,
        (1.0, 1.0, 0.5),
        0.61,
    )
    axial_axis = np.asarray(oblique.w_direction_patient)
    expected_rotation = axis_angle_rotation_matrix(axial_axis, -0.42)

    rotated = rotate_mpr_frame_about_plane_normal(
        oblique,
        MprPlane.AXIAL,
        -0.42,
    )

    np.testing.assert_allclose(
        _basis(rotated),
        expected_rotation @ _basis(oblique),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        rotated.w_direction_patient,
        oblique.w_direction_patient,
        atol=1e-12,
    )


def test_rotated_frame_remains_orthonormal_and_right_handed() -> None:
    frame = MprFrame.standard_lps((1.0, 2.0, 3.0))
    rotated = rotate_mpr_frame_about_axis(
        frame,
        (2.0, -4.0, 1.0),
        1.23,
    )
    basis = _basis(rotated)

    np.testing.assert_allclose(
        basis.T @ basis,
        np.eye(3),
        atol=1e-12,
    )
    np.testing.assert_allclose(np.linalg.det(basis), 1.0, atol=1e-12)


def test_rotation_followed_by_its_inverse_restores_the_frame() -> None:
    frame = MprFrame.standard_lps((3.0, 4.0, 5.0))
    axis = (-2.0, 1.0, 0.5)
    angle = 0.83

    rotated = rotate_mpr_frame_about_axis(frame, axis, angle)
    restored = rotate_mpr_frame_about_axis(rotated, axis, -angle)

    assert restored.center_patient == frame.center_patient
    np.testing.assert_allclose(_basis(restored), _basis(frame), atol=1e-12)


def test_axis_length_does_not_change_the_rotation() -> None:
    unit_axis_rotation = axis_angle_rotation_matrix((0.0, 0.0, 1.0), 0.5)
    scaled_axis_rotation = axis_angle_rotation_matrix((0.0, 0.0, 8.0), 0.5)

    np.testing.assert_allclose(
        scaled_axis_rotation,
        unit_axis_rotation,
        atol=1e-12,
    )


@pytest.mark.parametrize(
    ("axis", "angle"),
    (
        ((0.0, 0.0, 0.0), 0.5),
        ((float("nan"), 0.0, 1.0), 0.5),
        ((0.0, 0.0, 1.0), float("inf")),
    ),
)
def test_axis_angle_rotation_rejects_invalid_inputs(
    axis: tuple[float, float, float],
    angle: float,
) -> None:
    with pytest.raises(ValueError):
        axis_angle_rotation_matrix(axis, angle)


@pytest.mark.parametrize(
    "source_plane",
    (MprPlane.AXIAL, MprPlane.CORONAL, MprPlane.SAGITTAL),
)
def test_crosshair_rotation_keeps_source_sampling_basis(
    source_plane: MprPlane,
) -> None:
    """十字线旋转后，源视图的 Frame 旋转与补偿角完全抵消。"""
    state = MprState(MprFrame.standard_lps((1.0, 2.0, 3.0)))
    before = resolve_sampling_basis(state, source_plane)

    rotated = rotate_crosshair_state(state, source_plane, 0.43)
    after = resolve_sampling_basis(rotated, source_plane)

    np.testing.assert_allclose(
        after.row_direction_patient,
        before.row_direction_patient,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        after.column_direction_patient,
        before.column_direction_patient,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        after.navigation_direction_patient,
        before.navigation_direction_patient,
        atol=1e-12,
    )


def test_axial_crosshair_rotation_changes_the_other_two_views() -> None:
    state = MprState(MprFrame.standard_lps((1.0, 2.0, 3.0)))
    rotated = rotate_crosshair_state(state, MprPlane.AXIAL, 0.43)

    for plane in (MprPlane.CORONAL, MprPlane.SAGITTAL):
        before = resolve_sampling_basis(state, plane)
        after = resolve_sampling_basis(rotated, plane)
        assert not np.allclose(
            after.navigation_direction_patient,
            before.navigation_direction_patient,
        )

    assert rotated.view_rolls.axial_radians == pytest.approx(-0.43)
    assert rotated.view_rolls.coronal_radians == 0.0
    assert rotated.view_rolls.sagittal_radians == 0.0


def test_3d_state_rotation_preserves_view_rolls() -> None:
    rolls = MprViewRolls(0.1, -0.2, 0.3)
    state = MprState(
        MprFrame.standard_lps((1.0, 2.0, 3.0)),
        rolls,
    )

    rotated = rotate_mpr_state_3d(
        state,
        (1.0, 2.0, 3.0),
        0.5,
    )

    assert rotated.view_rolls == rolls
    assert rotated.frame.center_patient == state.frame.center_patient
    assert not np.allclose(_basis(rotated.frame), _basis(state.frame))


def test_3d_rotation_about_axial_normal_is_in_plane_in_axial_view() -> None:
    """绕 Axial 法向旋转时，Axial 法向不变而平面内两轴旋转。"""
    state = MprState(MprFrame.standard_lps((1.0, 2.0, 3.0)))
    axial_before = resolve_sampling_basis(state, MprPlane.AXIAL)

    rotated = rotate_mpr_state_3d(
        state,
        axial_before.navigation_direction_patient,
        0.43,
    )
    axial_after = resolve_sampling_basis(rotated, MprPlane.AXIAL)

    np.testing.assert_allclose(
        axial_after.navigation_direction_patient,
        axial_before.navigation_direction_patient,
        atol=1e-12,
    )
    assert not np.allclose(
        axial_after.row_direction_patient,
        axial_before.row_direction_patient,
    )
    assert not np.allclose(
        axial_after.column_direction_patient,
        axial_before.column_direction_patient,
    )

    for plane in (MprPlane.CORONAL, MprPlane.SAGITTAL):
        before = resolve_sampling_basis(state, plane)
        after = resolve_sampling_basis(rotated, plane)
        assert not np.allclose(
            after.navigation_direction_patient,
            before.navigation_direction_patient,
        )
