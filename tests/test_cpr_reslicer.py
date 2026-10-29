"""Numerical acceptance of curved and planar sampling, not screenshots."""
from dataclasses import replace
from threading import Event

import numpy as np
import pytest

from qt_dicom_viewer.model.cpr import CprError, CprPath, CprSettings
from qt_dicom_viewer.core.cpr_geometry import sample_centerline
from test_mpr_reslicer import _volume


def reslicer(**kwargs):
    from qt_dicom_viewer.core.cpr_reslicer import CprReslicer
    return CprReslicer(**kwargs)


def path(points=((0, 3, 5), (10, 3, 5))):
    return CprPath("p", "Path", points, revision=3)


def ramp_volume():
    z, y, x = np.indices((11, 7, 11))
    return _volume((100 * z + 10 * y + x).astype(np.float32))


def test_straight_cpr_matches_existing_axial_mpr_and_keeps_provenance():
    from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
    from qt_dicom_viewer.model import MprPlane
    volume = ramp_volume()
    volume.fingerprint = "source-v1"
    result = reslicer().reslice(volume, path(), CprSettings(step_mm=1, width_mm=6, up_patient=(0, 1, 0)))
    expected = MprReslicer().reslice(volume, MprPlane.AXIAL)
    np.testing.assert_allclose(result.modality_pixels, expected.modality_pixels, atol=1e-5)
    np.testing.assert_allclose(result.offsets_mm, np.arange(-3, 4))
    assert result.row_spacing_mm == 1
    assert result.centerline.path_revision == 3
    assert result.source_fingerprint == "source-v1" and result.series_uid == volume.series_uid
    assert result.modality_pixels.dtype == np.float32
    with pytest.raises(ValueError):
        result.modality_pixels[0, 0] = 9
    # No false uniform patient-space affine for the curved result.
    assert not hasattr(result, "image_index_to_patient")


def test_rotating_about_centerline_selects_the_orthogonal_longitudinal_plane():
    result = reslicer().reslice(ramp_volume(), path(), CprSettings(
        step_mm=1, width_mm=6, up_patient=(0, 1, 0), angle_radians=np.pi / 2))
    np.testing.assert_allclose(result.modality_pixels,
        100 * np.arange(2, 9)[:, None] + 30 + np.arange(11)[None, :], atol=1e-5)


def test_oblique_anisotropic_volume_reproduces_an_analytic_patient_space_field():
    angle = .63
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0],
                         [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    origin = np.array([12., -21., 8.])
    z, y, x = np.indices((13, 17, 21))
    patient = origin + np.stack((x * .7, y * 1.3, z * 2.1), axis=-1) @ rotation.T
    pixels = patient @ np.array([2., -3., .5]) + 40
    volume = _volume(pixels, origin=tuple(origin), column_spacing=.7, row_spacing=1.3,
        slice_spacing=2.1, row_direction=tuple(rotation[:, 0]), column_direction=tuple(rotation[:, 1]))
    c0 = origin + rotation @ [2.1, 10.4, 10.5]
    c1 = origin + rotation @ [11.9, 10.4, 10.5]
    result = reslicer(block_points=17).reslice(volume, path((tuple(c0), tuple(c1))),
        CprSettings(step_mm=.6, width_mm=5, up_patient=tuple(rotation[:, 1])))
    # Independent physical line and transverse direction, not output geometry.
    centers = c0 + np.linspace(0, 9.8, 18)[:, None] * rotation[:, 0]
    offsets = np.linspace(-2.5, 2.5, 11)
    expected_points = centers[None, :, :] + offsets[:, None, None] * rotation[:, 1]
    np.testing.assert_allclose(result.modality_pixels, expected_points @ [2., -3., .5] + 40, atol=2e-4)


@pytest.mark.parametrize("projection,expected", [("mip", 20.), ("mean", 15.)])
def test_slab_projects_only_valid_samples_near_volume_boundary(projection, expected):
    # B = -Y; offsets -2..2 at center Y=1 include Y=-1 (outside).
    pixels = np.broadcast_to(np.arange(3)[None, :, None] * 10., (7, 3, 7)).copy()
    pixels[:, 0] = np.nan
    volume = _volume(pixels)
    result = reslicer(block_points=3).reslice(volume, path(((0, 1, 3), (6, 1, 3))),
        CprSettings(step_mm=1, width_mm=2, projection=projection, thickness_mm=4))
    np.testing.assert_allclose(result.modality_pixels, expected)


@pytest.mark.parametrize("projection", ["thin", "mip", "mean"])
def test_all_missing_slab_stays_nan_and_zero_slab_matches_thin(projection):
    volume = _volume(np.full((7, 3, 7), np.nan, dtype=np.float32))
    result = reslicer().reslice(volume, path(((0, 1, 3), (6, 1, 3))),
        CprSettings(step_mm=1, width_mm=2, projection=projection, thickness_mm=4))
    assert np.isnan(result.modality_pixels).all()
    zero = reslicer().reslice(ramp_volume(), path(), CprSettings(step_mm=1, width_mm=2, projection=projection))
    np.testing.assert_allclose(zero.modality_pixels, 100 * np.arange(4, 7)[:, None] + 30 + np.arange(11))


def test_path_outside_in_the_middle_preserves_holes_and_arc_distances():
    volume = _volume(np.full((11, 7, 11), -100., dtype=np.float32))
    result = reslicer().reslice(volume, path(((2, 2, 5), (2, -3, 5), (8, -3, 5), (8, 2, 5))),
        CprSettings(step_mm=1, width_mm=2))
    assert result.centerline.length_mm == 16
    expected = [-100.] * 3 + [np.nan] * 11 + [-100.] * 3
    np.testing.assert_allclose(result.modality_pixels[1], expected, equal_nan=True)


def test_cross_section_has_real_plane_spacing_and_unchanged_historical_source():
    volume = ramp_volume()
    volume.fingerprint = "before"
    line = sample_centerline(path(), CprSettings(step_mm=1, up_patient=(0, 1, 0)))
    section = reslicer().cross_section(volume, line, 4, width_mm=4, step_mm=1)
    np.testing.assert_allclose(section.modality_pixels, 100 * np.arange(3, 8)[:, None] + 10 * np.arange(1, 6) + 4)
    geo = section.geometry
    np.testing.assert_allclose(geo.image_point_to_patient(column=2, row=2), [4, 3, 5])
    np.testing.assert_allclose(geo.image_point_to_patient(column=3, row=2), [4, 4, 5])
    np.testing.assert_allclose(geo.image_point_to_patient(column=2, row=3), [4, 3, 6])
    np.testing.assert_allclose(geo.iop_normal_direction_patient, [1, 0, 0])
    assert (section.path_id, section.path_revision, section.distance_mm, section.algorithm_version) == ("p", 3, 4., 1)
    volume.fingerprint = "after"
    assert section.source_fingerprint == "before"
    assert not section.modality_pixels.flags.writeable


def test_known_tube_cross_section_diameter_within_one_output_pixel():
    z, y, x = np.indices((41, 81, 81))
    pixels = np.where((x * .25 - 10) ** 2 + (y * .25 - 10) ** 2 <= 25, 100., 0.)
    volume = _volume(pixels, origin=(-10, -10, -5), slice_spacing=.25, row_spacing=.25, column_spacing=.25)
    line = sample_centerline(path(((0, 0, -4), (0, 0, 4))), CprSettings(step_mm=.5))
    section = reslicer().cross_section(volume, line, 8, width_mm=16, step_mm=.25)
    diameter = np.count_nonzero(section.modality_pixels[32] >= 50) * section.geometry.column_spacing
    assert diameter == pytest.approx(10, abs=.25)
    np.testing.assert_allclose(section.geometry.image_point_to_patient(column=32, row=32), [0, 0, 0])


def test_requested_spacing_is_not_used_as_scale_when_grid_extent_needs_rounding():
    line = sample_centerline(path(), CprSettings())
    section = reslicer().cross_section(ramp_volume(), line, 8, width_mm=5, step_mm=.6)
    assert section.modality_pixels.shape == (11, 11)
    assert section.geometry.row_spacing == .5
    assert section.geometry.column_spacing == .5


def test_blocks_are_bounded_share_the_volume_and_match_one_large_block(monkeypatch):
    from qt_dicom_viewer.core import cpr_reslicer
    sample = cpr_reslicer.sample_volume
    volume = ramp_volume()
    # Negative strides must not cause a hidden contiguous copy of the source.
    volume.modality_pixels = volume.modality_pixels[::-1, :, ::-1]
    before = volume.modality_pixels.copy()
    seen = []
    def observe(pixels, *coordinates):
        assert pixels is volume.modality_pixels
        seen.append(np.broadcast_arrays(*coordinates)[0].size)
        return sample(pixels, *coordinates)
    monkeypatch.setattr(cpr_reslicer, "sample_volume", observe)
    settings = CprSettings(step_mm=.5, width_mm=4, projection="mean", thickness_mm=2)
    small = reslicer(block_points=7).reslice(volume, path(), settings)
    assert seen and max(seen) <= 7
    seen.clear()
    line = small.centerline
    section = reslicer(block_points=7).cross_section(volume, line, 6, width_mm=4, step_mm=.5)
    assert max(seen) <= 7
    large = reslicer().reslice(volume, path(), settings)
    np.testing.assert_array_equal(small.modality_pixels, large.modality_pixels)
    np.testing.assert_array_equal(section.modality_pixels,
        reslicer().cross_section(volume, line, 6, width_mm=4, step_mm=.5).modality_pixels)
    np.testing.assert_array_equal(volume.modality_pixels, before)


@pytest.mark.parametrize("settings", [
    CprSettings(step_mm=.05, width_mm=500),
    CprSettings(step_mm=.05, width_mm=200),
    CprSettings(step_mm=.05, width_mm=2, projection="mip", thickness_mm=100),
    CprSettings(step_mm=.05, width_mm=40, projection="mean", thickness_mm=20)])
def test_requests_exceeding_grid_slab_or_work_limits_are_rejected_before_sampling(settings, monkeypatch):
    from qt_dicom_viewer.core import cpr_reslicer
    def forbidden(*args):
        pytest.fail("Oversized request reached voxel sampling")
    monkeypatch.setattr(cpr_reslicer, "sample_volume", forbidden)
    with pytest.raises(CprError, match="limit"):
        reslicer().reslice(ramp_volume(), path(((0, 0, 0), (200, 0, 0))), settings)


@pytest.mark.parametrize("change", [{"rows": 8}, {"slice_spacing": 0},
    {"origin_patient": (np.nan, 0, 0)}, {"slice_index_direction_patient": (1, 0, 0)}])
def test_invalid_volume_geometry_fails_clearly(change):
    volume = ramp_volume()
    volume.geometry = replace(volume.geometry, **change)
    with pytest.raises(CprError):
        reslicer().reslice(volume, path(), CprSettings())


@pytest.mark.parametrize("index", [-1, 9999, 1.5, True])
def test_invalid_cross_section_index_is_rejected(index):
    line = sample_centerline(path(), CprSettings())
    with pytest.raises(CprError):
        reslicer().cross_section(ramp_volume(), line, index, width_mm=4, step_mm=1)


@pytest.mark.parametrize("section", [False, True])
def test_cancellation_during_sampling_discards_partial_result(section, monkeypatch):
    from qt_dicom_viewer.core import cpr_reslicer
    from qt_dicom_viewer.core.render_cancellation import render_cancellation
    event = Event()
    sample = cpr_reslicer.sample_volume
    calls = []
    def cancel_after_block(*args):
        calls.append(1)
        result = sample(*args)
        event.set()
        return result
    monkeypatch.setattr(cpr_reslicer, "sample_volume", cancel_after_block)
    line = sample_centerline(path(), CprSettings())
    volume = ramp_volume()
    before = volume.modality_pixels.copy()
    with render_cancellation(event), pytest.raises(InterruptedError):
        if section:
            reslicer(block_points=7).cross_section(volume, line, 4, width_mm=4, step_mm=.5)
        else:
            reslicer(block_points=7).reslice(volume, path(), CprSettings(width_mm=4))
    assert len(calls) == 1
    np.testing.assert_array_equal(volume.modality_pixels, before)


@pytest.mark.parametrize("spacing", [1e-310, 1e-308])
def test_near_zero_volume_spacing_is_rejected_without_overflow(spacing):
    volume = ramp_volume()
    volume.geometry = replace(volume.geometry, row_spacing=spacing,
                              column_spacing=spacing, slice_spacing=spacing)
    with np.errstate(all="raise"), pytest.raises(CprError):
        reslicer().reslice(volume, path(), CprSettings(projection="mip", thickness_mm=100))
