"""验证 MPR 坐标架、视图补偿角和采样基之间的模型边界。"""

import numpy as np
import pytest

from voxplane.model import (
    MprFrame,
    MprGridSpec,
    MprGridAnchor,
    MprPlane,
    MprProjectionMode,
    MprProjectionSettings,
    MprSamplingBasis,
    MprState,
    MprViewRolls,
    MprViewGrids,
    MprViewAnchors,
)


def test_mpr_state_defaults_every_view_roll_to_zero() -> None:
    frame = MprFrame.standard_lps((1.0, 2.0, 3.0))

    state = MprState(frame=frame)

    assert state.frame is frame
    assert state.view_rolls.for_plane(MprPlane.AXIAL) == 0.0
    assert state.view_rolls.for_plane(MprPlane.CORONAL) == 0.0
    assert state.view_rolls.for_plane(MprPlane.SAGITTAL) == 0.0


def test_mpr_view_rolls_keep_each_view_independent() -> None:
    rolls = MprViewRolls(
        axial_radians=0.25,
        coronal_radians=-0.5,
        sagittal_radians=0.75,
    )

    assert rolls.for_plane(MprPlane.AXIAL) == 0.25
    assert rolls.for_plane(MprPlane.CORONAL) == -0.5
    assert rolls.for_plane(MprPlane.SAGITTAL) == 0.75


def test_mpr_view_grids_keep_each_view_independent() -> None:
    axial = MprGridSpec(100, 120, 0.8, 0.8)
    coronal = MprGridSpec(80, 120, 1.2, 0.8)
    sagittal = MprGridSpec(80, 100, 1.2, 0.8)
    grids = MprViewGrids(axial, coronal, sagittal)

    assert grids.for_plane(MprPlane.AXIAL) is axial
    assert grids.for_plane(MprPlane.CORONAL) is coronal
    assert grids.for_plane(MprPlane.SAGITTAL) is sagittal
    assert axial.row_extent == pytest.approx(99 * 0.8)
    assert axial.column_extent == pytest.approx(119 * 0.8)

    anchors = MprViewAnchors.centered(grids)
    assert anchors.axial == MprGridAnchor(59.5, 49.5)
    assert anchors.coronal == MprGridAnchor(59.5, 39.5)
    assert anchors.sagittal == MprGridAnchor(49.5, 39.5)


@pytest.mark.parametrize(
    ("rows", "columns", "row_spacing", "column_spacing"),
    (
        (0, 10, 1.0, 1.0),
        (10, 0, 1.0, 1.0),
        (10, 10, 0.0, 1.0),
        (10, 10, 1.0, float("nan")),
    ),
)
def test_mpr_grid_rejects_invalid_dimensions_or_spacing(
    rows: int,
    columns: int,
    row_spacing: float,
    column_spacing: float,
) -> None:
    with pytest.raises(ValueError):
        MprGridSpec(
            rows,
            columns,
            row_spacing,
            column_spacing,
        )


@pytest.mark.parametrize(
    "invalid_roll",
    (float("nan"), float("inf"), float("-inf")),
)
def test_mpr_view_rolls_reject_non_finite_values(
    invalid_roll: float,
) -> None:
    with pytest.raises(ValueError):
        MprViewRolls(axial_radians=invalid_roll)


def test_mpr_sampling_basis_accepts_orthonormal_patient_directions() -> None:
    basis = MprSamplingBasis(
        row_direction_patient=(0.0, 1.0, 0.0),
        column_direction_patient=(1.0, 0.0, 0.0),
        navigation_direction_patient=(0.0, 0.0, 1.0),
    )

    np.testing.assert_allclose(
        basis.row_direction_patient,
        (0.0, 1.0, 0.0),
    )


def test_mpr_projection_settings_resolve_each_effective_plane() -> None:
    settings = MprProjectionSettings(
        enabled=True,
        mode=MprProjectionMode.MEAN,
        axial_thickness_mm=12,
        sagittal_thickness_mm=8,
    )

    assert settings.effective_projection_for_plane(MprPlane.AXIAL) == (
        MprProjectionMode.MEAN,
        12,
    )
    assert settings.effective_projection_for_plane(MprPlane.CORONAL) == (
        None,
        0,
    )
    assert settings.thickness_for_plane(MprPlane.SAGITTAL) == 8


@pytest.mark.parametrize("thickness", [-1, 101, 1.5, True])
def test_mpr_projection_settings_reject_invalid_thickness(thickness) -> None:
    with pytest.raises(ValueError, match="thickness"):
        MprProjectionSettings(axial_thickness_mm=thickness)


@pytest.mark.parametrize(
    ("row", "column", "navigation"),
    (
        (
            (float("nan"), 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        (
            (1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        (
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
    ),
)
def test_mpr_sampling_basis_rejects_invalid_directions(
    row: tuple[float, float, float],
    column: tuple[float, float, float],
    navigation: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError):
        MprSamplingBasis(
            row_direction_patient=row,
            column_direction_patient=column,
            navigation_direction_patient=navigation,
        )
