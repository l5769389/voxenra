import math

from voxplane.core.geometry_2d import (
    image_point_distance_mm,
    point_distance,
    point_to_segment_distance,
)
from voxplane.model import ImagePoint


def test_point_distance_uses_image_coordinates() -> None:
    assert point_distance(
        ImagePoint(column=1.0, row=2.0),
        ImagePoint(column=4.0, row=6.0),
    ) == 5.0


def test_point_to_segment_distance_projects_and_clamps() -> None:
    start = ImagePoint(column=0.0, row=0.0)
    end = ImagePoint(column=10.0, row=0.0)

    assert point_to_segment_distance(
        ImagePoint(column=4.0, row=3.0),
        start,
        end,
    ) == 3.0
    assert point_to_segment_distance(
        ImagePoint(column=13.0, row=4.0),
        start,
        end,
    ) == 5.0


def test_point_to_zero_length_segment_uses_endpoint() -> None:
    endpoint = ImagePoint(column=1.0, row=1.0)

    assert point_to_segment_distance(
        ImagePoint(column=4.0, row=5.0),
        endpoint,
        endpoint,
    ) == 5.0


def test_image_point_distance_mm_applies_axis_spacing() -> None:
    distance = image_point_distance_mm(
        ImagePoint(column=0.0, row=0.0),
        ImagePoint(column=4.0, row=3.0),
        row_spacing=2.0,
        column_spacing=0.5,
    )

    assert distance is not None
    assert math.isclose(distance, math.sqrt(40.0))


def test_image_point_distance_mm_rejects_invalid_spacing() -> None:
    assert image_point_distance_mm(
        ImagePoint(column=0.0, row=0.0),
        ImagePoint(column=1.0, row=1.0),
        row_spacing=0.0,
        column_spacing=1.0,
    ) is None
