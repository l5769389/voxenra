import pytest

from voxplane.core.patient_orientation import (
    ImageEdgeDirectionLabels,
    displayed_image_edge_labels,
    patient_direction_to_label,
)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ((1.0, 0.0, 0.0), "L"),
        ((-1.0, 0.0, 0.0), "R"),
        ((0.0, 1.0, 0.0), "P"),
        ((0.0, -1.0, 0.0), "A"),
        ((0.0, 0.0, 1.0), "H"),
        ((0.0, 0.0, -1.0), "F"),
    ],
)
def test_patient_direction_to_label_uses_lps_axes(
    direction: tuple[float, float, float],
    expected: str,
) -> None:
    assert patient_direction_to_label(direction) == expected


def test_patient_direction_to_label_preserves_oblique_components() -> None:
    assert patient_direction_to_label((0.8, 0.6, 0.0)) == "LP"
    assert patient_direction_to_label((-0.3, -0.4, 0.5)) == "HAR"


def test_patient_direction_to_label_ignores_numeric_noise() -> None:
    assert patient_direction_to_label((1.0, 1e-8, -1e-9)) == "L"


def test_patient_direction_to_label_returns_empty_for_invalid_vector() -> None:
    assert patient_direction_to_label((0.0, 0.0, 0.0)) == ""
    assert patient_direction_to_label((float("nan"), 0.0, 0.0)) == ""


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (
            (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            ImageEdgeDirectionLabels("A", "L", "P", "R"),
        ),
        (
            (1.0, 0.0, 0.0, 0.0, 0.0, -1.0),
            ImageEdgeDirectionLabels("H", "L", "F", "R"),
        ),
        (
            (0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
            ImageEdgeDirectionLabels("H", "P", "F", "A"),
        ),
    ],
)
def test_displayed_image_edge_labels_supports_standard_mpr_planes(
    orientation: tuple[float, ...],
    expected: ImageEdgeDirectionLabels,
) -> None:
    assert displayed_image_edge_labels(orientation) == expected


def test_displayed_image_edge_labels_applies_clockwise_rotation() -> None:
    labels = displayed_image_edge_labels(
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        rotation_degrees=90.0,
    )

    assert labels == ImageEdgeDirectionLabels("R", "A", "L", "P")


def test_displayed_image_edge_labels_applies_flips_before_rotation() -> None:
    orientation = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    assert displayed_image_edge_labels(
        orientation,
        horizontal_flip=True,
    ) == ImageEdgeDirectionLabels("A", "R", "P", "L")
    assert displayed_image_edge_labels(
        orientation,
        vertical_flip=True,
    ) == ImageEdgeDirectionLabels("P", "L", "A", "R")
    assert displayed_image_edge_labels(
        orientation,
        rotation_degrees=90.0,
        horizontal_flip=True,
    ) == ImageEdgeDirectionLabels("L", "A", "R", "P")


def test_displayed_image_edge_labels_keeps_oblique_information() -> None:
    labels = displayed_image_edge_labels(
        (0.8, 0.6, 0.0, -0.6, 0.8, 0.0)
    )

    assert labels == ImageEdgeDirectionLabels("AL", "LP", "PR", "RA")
