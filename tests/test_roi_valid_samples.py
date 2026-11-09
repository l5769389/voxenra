"""Out-of-image ROI geometry remains intact; only valid samples affect intensity."""
import numpy as np
import pytest

from qt_dicom_viewer.core.measurement_geometry import roi_metrics
from qt_dicom_viewer.model import ImagePoint, MeasurementKind


@pytest.mark.parametrize('kind,points,expected,area', [
    (MeasurementKind.RECT, [(-2, -2), (2, 2)], [1, 2, 4, 5, 6, 8, 9, 10], 16),
    (MeasurementKind.ELLIPSE, [(-2, -2), (2, 2)], [1, 2, 4, 5, 8], 4 * np.pi),
    (MeasurementKind.FREEHAND, [(-2, -2), (3, -2), (-2, 3)], [1, 4], 12.5),
])
def test_partial_roi_uses_only_finite_in_shape_image_pixels(kind, points, expected, area):
    pixels = np.arange(16, dtype=float).reshape(4, 4)
    pixels[0, 0] = np.nan
    pixels[3, :] = np.inf
    result = roi_metrics([ImagePoint(*p) for p in points], kind, pixels,
                         row_spacing=2, column_spacing=.5, unit='HU')
    assert result.pixel_count == len(expected)
    assert result.mean == pytest.approx(np.mean(expected))
    assert result.std == pytest.approx(np.std(expected))
    assert (result.minimum, result.maximum) == (min(expected), max(expected))
    assert result.area_mm2 == pytest.approx(area)
    assert result.unit == 'HU'


@pytest.mark.parametrize('kind', [MeasurementKind.RECT, MeasurementKind.ELLIPSE, MeasurementKind.FREEHAND])
def test_roi_without_any_valid_pixels_has_no_fabricated_statistics(kind):
    points = [ImagePoint(-2, -2), ImagePoint(2, 2)] if kind != MeasurementKind.FREEHAND else [
        ImagePoint(-2, -2), ImagePoint(3, -2), ImagePoint(-2, 3)
    ]
    result = roi_metrics(points, kind, np.full((4, 4), np.nan), row_spacing=1, column_spacing=1)
    assert result.area_mm2 > 0
    assert result.pixel_count == 0
    assert result.mean is result.std is result.minimum is result.maximum is None
