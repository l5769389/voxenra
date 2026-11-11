import math

import numpy as np
import pytest

from voxplane.core.measurement_geometry import angle_degrees, roi_metrics
from voxplane.model import ImagePoint, MeasurementKind


def test_angle_uses_physical_spacing_not_screen_or_pixel_angle():
    points = [ImagePoint(1, 0), ImagePoint(0, 0), ImagePoint(1, 1)]
    assert angle_degrees(points, row_spacing=2, column_spacing=1) == pytest.approx(63.43494882)
    assert angle_degrees(points, row_spacing=1, column_spacing=1) == pytest.approx(45)


@pytest.mark.parametrize("points, expected", [
    ([(1, 0), (0, 0), (0, 1)], 90),
    ([(1, 0), (0, 0), (-1, 0)], 180),
    ([(1, 0), (0, 0), (2, 0)], 0),
    ([(0, 0), (0, 0), (2, 0)], None),
])
def test_angle_degenerate_and_collinear_cases(points, expected):
    result = angle_degrees([ImagePoint(*p) for p in points], row_spacing=1, column_spacing=1)
    assert result == expected


def test_rect_metrics_use_center_inclusion_and_anisotropic_spacing():
    pixels = np.arange(9, dtype=float).reshape(3, 3)
    result = roi_metrics([ImagePoint(-.5, -.5), ImagePoint(2.5, 2.5)],
                         MeasurementKind.RECT, pixels, row_spacing=2, column_spacing=.5, unit="HU")
    assert (result.width_mm, result.height_mm, result.area_mm2) == (1.5, 6, 9)
    assert result.pixel_count == 9
    assert (result.mean, result.minimum, result.maximum) == (4, 0, 8)
    assert result.std == pytest.approx(math.sqrt(60 / 9))
    assert result.unit == "HU"


def test_ellipse_uses_its_mask_not_the_whole_bounding_rectangle():
    pixels = np.arange(25, dtype=float).reshape(5, 5)
    pixels[0, 0] = 10000  # 此点位于包围矩形内，却在椭圆外。
    result = roi_metrics([ImagePoint(0, 0), ImagePoint(4, 4)], MeasurementKind.ELLIPSE,
                         pixels, row_spacing=1, column_spacing=1)
    expected = [2, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18, 22]
    assert result.area_mm2 == pytest.approx(4 * math.pi)
    assert result.pixel_count == 13
    assert result.mean == 12
    assert result.std == pytest.approx(np.std(expected))
    assert (result.minimum, result.maximum) == (2, 22)


@pytest.mark.parametrize("kind", [MeasurementKind.RECT, MeasurementKind.ELLIPSE])
def test_roi_reversed_drag_and_invalid_pixels(kind):
    pixels = np.array([[np.nan, 2], [np.inf, 4]])
    result = roi_metrics([ImagePoint(1.5, 1.5), ImagePoint(-.5, -.5)], kind,
                         pixels, row_spacing=1, column_spacing=1)
    assert result.pixel_count == 2
    assert (result.mean, result.std, result.minimum, result.maximum) == (3, 1, 2, 4)


def test_outside_roi_has_geometry_but_no_fake_zero_statistics():
    result = roi_metrics([ImagePoint(-100, -100), ImagePoint(-10, -10)], MeasurementKind.RECT,
                         np.ones((2, 2)), row_spacing=1, column_spacing=1)
    assert result.area_mm2 == 8100
    assert result.pixel_count == 0
    assert result.mean is result.std is result.minimum is result.maximum is None


def test_huge_roi_only_allocates_mask_for_existing_image():
    result = roi_metrics([ImagePoint(-1e9, -1e9), ImagePoint(1e9, 1e9)], MeasurementKind.ELLIPSE,
                         np.ones((3, 3)), row_spacing=1, column_spacing=1)
    assert result.pixel_count == 9


def test_missing_physical_spacing_does_not_invent_millimeters():
    result = roi_metrics([ImagePoint(0, 0), ImagePoint(1, 1)], MeasurementKind.RECT,
                         np.ones((2, 2)), row_spacing=0, column_spacing=1)
    assert result.area_mm2 is None
    assert result.mean == 1
    assert angle_degrees([ImagePoint(1, 0), ImagePoint(0, 0), ImagePoint(0, 1)],
                         row_spacing=0, column_spacing=1) is None
