from dataclasses import replace

import numpy as np
import pytest

from voxplane.core.mpr_voi import (VoiRegion, automatic_depth, box_from_drag, circle_from_drag,
                                         editing_handles, evaluate_voi, plane_polygon, plane_mask)
from voxplane.core.mpr_reslicer import MprReslicer
from voxplane.core.mpr_rotation import axis_angle_rotation_matrix
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import MprPlane, MprFrame
from test_mpr_reslicer import _volume
from test_pet_fusion import paired_series


def test_native_statistics_depth_threshold_padding_and_negative_hu():
    pixels = np.arange(4*5*6, dtype=np.float32).reshape(4, 5, 6) - 100
    pixels[1, 2, 3] = np.nan
    volume = _volume(pixels, slice_spacing=3, row_spacing=2, column_spacing=.5)
    box = VoiRegion((1.5, 4, 4.5), tuple(map(tuple, np.eye(3))), (2, 6, 6))
    selected = pixels[1:3, 1:4, 1:5]
    values = selected[np.isfinite(selected)]
    result = evaluate_voi(volume, box)
    assert result.metrics["count"] == len(values)
    assert result.metrics["mean"] == pytest.approx(values.mean())
    assert result.metrics["sd"] == pytest.approx(values.std())
    assert result.metrics["volume"] == pytest.approx(len(values) * 3 * 2 * .5 / 1000)
    lower = evaluate_voi(volume, box, threshold=-40)
    assert lower.metrics["count"] == np.count_nonzero(values >= -40)
    assert lower.metrics["fraction"] == pytest.approx(np.count_nonzero(values >= -40) / len(values) * 100)
    percent = evaluate_voi(volume, box, threshold=50, percent=True)
    assert percent.threshold == pytest.approx((values.min() + values.max()) / 2)
    deep = evaluate_voi(volume, replace(box, size=(2, 6, 12)))
    assert deep.metrics["count"] > result.metrics["count"]
    empty = evaluate_voi(volume, box, threshold=1e10)
    assert empty.metrics["count"] == 0 and empty.metrics["volume"] == 0
    assert empty.metrics["mean"] is None


@pytest.mark.parametrize("plane", list(MprPlane))
def test_oblique_box_uses_patient_coordinates_and_three_plane_intersections(plane):
    volume = _volume(np.ones((11, 13, 15)), slice_spacing=2, row_spacing=1.5, column_spacing=.8)
    rotation = axis_angle_rotation_matrix((0, 0, 1), .37)
    frame = MprFrame(volume.geometry.center_patient, *map(tuple, rotation.T))
    geometry = MprReslicer().reslice(volume, plane, frame).geometry
    start = (geometry.columns/2 - 3, geometry.rows/2 - 2)
    end = (geometry.columns/2 + 3, geometry.rows/2 + 2)
    box = box_from_drag(geometry, start, end, 5.)
    evaluation = evaluate_voi(volume, box)
    # Independent exhaustive physical-coordinate oracle, including anisotropy.
    indices = np.indices(volume.modality_pixels.shape).reshape(3, -1).T
    affine = volume.geometry.voxel_to_patient
    local = (indices @ affine[:3, :3].T + affine[:3, 3] - box.center) @ np.asarray(box.axes).T
    expected = np.all((local >= -np.asarray(box.size)/2-1e-6) & (local < np.asarray(box.size)/2-1e-6), axis=1)
    assert evaluation.metrics["count"] == expected.sum()
    for other_plane in MprPlane:
        other = MprReslicer().reslice(volume, other_plane, frame).geometry
        polygon = plane_polygon(box, other)
        assert len(polygon) >= 3
        mask = plane_mask(evaluation, other)
        assert mask.shape == (other.rows, other.columns)
        assert mask.any()
    far = MprReslicer().reslice(volume, plane, replace(frame, center_patient=(1000., 1000., 1000.))).geometry
    assert plane_polygon(box, far) == []
    assert not plane_mask(evaluation, far).any()


def test_pet_real_suv_and_activity_domains_and_percent(paired_series):
    _, _, pet = paired_series
    volume = VolumeManager().get_or_build(pet)
    box = VoiRegion(volume.geometry.center_patient, tuple(map(tuple, np.eye(3))), (100, 100, 100))
    suv = evaluate_voi(volume, box, threshold=50, percent=True, pet=True)
    assert suv.threshold == pytest.approx(3)
    assert suv.metrics["count"] == 2
    activity = evaluate_voi(volume.in_unit("kbqml"), box, threshold=2.5, pet=True)
    assert activity.metrics["count"] == 1
    assert activity.metrics["mean"] == pytest.approx(3)
    assert suv.metrics["maximum"] == pytest.approx(6)


def test_outside_and_invalid_boxes():
    volume = _volume(np.ones((3, 4, 5)))
    box = VoiRegion((100, 100, 100), tuple(map(tuple, np.eye(3))), (2, 2, 2))
    result = evaluate_voi(volume, box)
    assert result.metrics["count"] == 0
    with pytest.raises(ValueError):
        replace(box, size=(0, 1, 1))
    with pytest.raises(ValueError):
        replace(box, center=(float("nan"), 0, 0))


def test_pet_threshold_uses_each_slices_true_calibration(paired_series):
    import pydicom
    _, _, pet = paired_series
    path = pet.instances[1].path
    ds = pydicom.dcmread(path)
    ds.RescaleSlope = 2
    ds.PatientWeight = 35
    ds.save_as(path, enforce_file_format=True)
    volume = VolumeManager().get_or_build(pet)
    box = VoiRegion(volume.geometry.center_patient, tuple(map(tuple, np.eye(3))), (100, 100, 100))
    suv = evaluate_voi(volume, box, threshold=5, pet=True)
    activity = evaluate_voi(volume.in_unit("kbqml"), box, threshold=2.5, pet=True)
    assert suv.metrics["count"] == 1
    assert suv.metrics["mean"] == pytest.approx(6)
    assert activity.metrics["count"] == 2
    assert activity.metrics["mean"] == pytest.approx(3.5)


def test_pet_without_reliable_suv_keeps_activity_units(paired_series):
    import pydicom
    _, _, pet = paired_series
    path = pet.instances[1].path
    ds = pydicom.dcmread(path)
    del ds.PatientWeight
    ds.save_as(path, enforce_file_format=True)
    volume = VolumeManager().get_or_build(pet)
    assert volume.pixel_value_meta.unit == "Bq/ml"
    assert all(o.unit_id != "suvbw" for o in volume.pixel_value_meta.unit_options if o.available)
    box = VoiRegion(volume.geometry.center_patient, tuple(map(tuple, np.eye(3))), (100, 100, 100))
    result = evaluate_voi(volume, box, threshold=2500, pet=True)
    assert result.metrics["count"] == 1
    assert result.metrics["mean"] == pytest.approx(3000)
    with pytest.raises(ValueError):
        volume.in_unit("suvbw")


def test_circle_drag_and_auto_depth_use_physical_dimensions():
    volume = _volume(np.ones((15, 25, 25)), row_spacing=2, column_spacing=.5, slice_spacing=3)
    g = MprReslicer().reslice(volume, MprPlane.AXIAL, MprFrame(volume.geometry.center_patient)).geometry
    # Deliberately unequal sampling distances: a horizontal or vertical gesture
    # with equal physical length must produce the same circle.
    g = replace(g, row_spacing=2., column_spacing=.5)
    a = circle_from_drag(g, (5., 6.), (11., 6.))
    b = circle_from_drag(g, (5., 6.), (5., 7.5))
    assert a == b and a.shape == "ellipsoid" and a.size == (6., 6., 6.)
    rect = box_from_drag(g, (0, 0), (64, 9), 1)
    assert automatic_depth(rect, 3) == 24
    assert automatic_depth(replace(rect, size=(1, 1, 1)), 3) == 3
    polygon = np.asarray(plane_polygon(a, g))
    assert np.ptp(polygon[:, 0]) * .5 == pytest.approx(6)
    assert np.ptp(polygon[:, 1]) * 2 == pytest.approx(6)
    assert len(editing_handles(a, g)) == 4


@pytest.mark.parametrize("plane", list(MprPlane))
def test_oblique_ellipsoid_voxels_and_exact_plane_sections(plane):
    pixels = np.arange(17*23*29, dtype=np.float32).reshape(17, 23, 29)
    pixels[8, 11, 14] = np.nan
    volume = _volume(pixels, slice_spacing=1.4, row_spacing=.7, column_spacing=.5)
    rotation = axis_angle_rotation_matrix((1, 0, 0), .43)
    region = VoiRegion(volume.geometry.center_patient, tuple(map(tuple, rotation.T)), (9, 9, 14), "ellipsoid")
    indices = np.indices(pixels.shape).reshape(3, -1).T
    matrix = volume.geometry.voxel_to_patient
    local = (indices @ matrix[:3, :3].T + matrix[:3, 3] - region.center) @ rotation
    inside = ((local / [4.5, 4.5, 7]) ** 2).sum(axis=1) <= 1 + 1e-9
    values = pixels.ravel()[inside & np.isfinite(pixels.ravel())]
    result = evaluate_voi(volume, region)
    assert result.metrics["count"] == values.size
    assert result.metrics["mean"] == pytest.approx(values.mean())
    assert result.metrics["volume"] == pytest.approx(values.size * 1.4 * .7 * .5 / 1000)
    g = MprReslicer().reslice(volume, plane, MprFrame(volume.geometry.center_patient)).geometry
    polygon = np.asarray(plane_polygon(region, g))
    assert len(polygon) == 128
    positions = (np.asarray(g.image_origin_patient) + polygon[:, :1] * g.column_spacing * g.column_direction_patient
                 + polygon[:, 1:] * g.row_spacing * g.row_direction_patient)
    boundary = (positions - region.center) @ rotation
    np.testing.assert_allclose(((boundary / [4.5, 4.5, 7]) ** 2).sum(axis=1), 1, atol=1e-8)
    assert plane_mask(result, g).any()


def test_sphere_sections_shrink_and_disappear_away_from_center():
    volume = _volume(np.ones((21, 21, 21)))
    center = volume.geometry.center_patient
    sphere = VoiRegion(center, tuple(map(tuple, np.eye(3))), (10, 10, 10), "ellipsoid")
    reslicer = MprReslicer()
    g = reslicer.reslice(volume, MprPlane.AXIAL, MprFrame(center)).geometry
    offset_g = replace(g, image_origin_mpr=tuple(np.asarray(g.image_origin_mpr) + [0, 0, 3]))
    section = np.asarray(plane_polygon(sphere, offset_g))
    assert np.ptp(section[:, 0]) * g.column_spacing == pytest.approx(8)
    assert editing_handles(sphere, offset_g) == []
    outside = replace(g, image_origin_mpr=tuple(np.asarray(g.image_origin_mpr) + [0, 0, 6]))
    assert plane_polygon(sphere, outside) == []
