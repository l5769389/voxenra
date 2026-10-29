"""Patient-space invariants, with analytic expectations independent of CPR code."""
from dataclasses import replace
from threading import Event

import numpy as np
import pytest


def api():
    from qt_dicom_viewer.model.cpr import CprError, CprPath, CprSettings
    from qt_dicom_viewer.core.cpr_geometry import sample_centerline
    return CprError, CprPath, CprSettings, sample_centerline


def centerline(points, **options):
    _, Path, Settings, sample = api()
    return sample(Path("artery", "Path 1", points), Settings(**options))


def test_line_preserves_endpoints_actual_spacing_and_right_handed_basis():
    line = centerline(((1, 2, 3), (11.2, 2, 3)), step_mm=2)
    np.testing.assert_allclose(line.distances_mm, np.arange(7) * 1.7, atol=1e-12)
    np.testing.assert_allclose(line.points_patient[:, 0], 1 + np.arange(7) * 1.7)
    np.testing.assert_allclose(line.points_patient[:, 1:], np.tile([2, 3], (7, 1)))
    np.testing.assert_allclose(line.tangents_patient, np.tile([1, 0, 0], (7, 1)))
    np.testing.assert_allclose(line.laterals_patient, np.tile([0, 0, 1], (7, 1)))
    np.testing.assert_allclose(line.binormals_patient, np.tile([0, -1, 0], (7, 1)))
    assert line.spacing_mm == pytest.approx(1.7)
    assert line.length_mm == pytest.approx(10.2)
    assert (line.path_id, line.path_revision, line.algorithm_version) == ("artery", 1, 1)


def test_polyline_uses_physical_arc_length_without_shortcut_or_overshoot():
    line = centerline(((0, 0, 0), (3, 0, 0), (3, 4, 0)), step_mm=1)
    np.testing.assert_allclose(line.points_patient, [
        [0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0],
        [3, 1, 0], [3, 2, 0], [3, 3, 0], [3, 4, 0]])
    assert line.length_mm == 7
    np.testing.assert_allclose(line.tangents_patient[3:], np.tile([0, 1, 0], (5, 1)))


@pytest.mark.parametrize("points", [(), ((0, 0, 0),), ((0, 0, 0), (0, 0, 0)),
    ((0, 0, 0), (1e-5, 0, 0)), ((0, 0, 0), (.01, 0, 0)),
    ((0, 0, 0), (1, 0, 0), (0, 0, 0)),
    ((0, 0, 0), (float("nan"), 0, 0)), ((0, 0, 0), (float("inf"), 0, 0)),
    ((0, 0), (1, 1)), ((0, 0, 0), (10001, 0, 0)),
    tuple((i, 0, 0) for i in range(4097))])
def test_invalid_path_rejected_before_sampling(points):
    Error, Path, Settings, sample = api()
    with pytest.raises(Error):
        sample(Path("p", "Path", points), Settings())


@pytest.mark.parametrize("change", [{"revision": 0}, {"revision": True},
    {"algorithm_version": 2}, {"path_id": ""}])
def test_invalid_provenance_rejected(change):
    Error, Path, _, _ = api()
    with pytest.raises(Error):
        Path(**(dict(path_id="p", name="Path", control_points=((0, 0, 0), (1, 0, 0))) | change))


@pytest.mark.parametrize("change", [{"step_mm": 0}, {"step_mm": .049}, {"step_mm": float("nan")},
    {"step_mm": 11}, {"width_mm": 0}, {"width_mm": 501}, {"thickness_mm": -1},
    {"thickness_mm": 101}, {"angle_radians": float("inf")}, {"up_patient": (0, 0, 0)},
    {"up_patient": (1, 0)}, {"projection": "sum"}])
def test_invalid_settings_rejected(change):
    Error, _, Settings, _ = api()
    with pytest.raises(Error):
        Settings(**change)


def test_captured_path_and_geometry_cannot_change_through_caller_buffers():
    _, Path, Settings, sample = api()
    points = np.array([[0., 0, 0], [5, 0, 0]])
    path = Path("p", "Path", points)
    points[1] = [99, 0, 0]
    line = sample(path, Settings())
    assert line.length_mm == 5
    with pytest.raises(ValueError):
        line.points_patient[0, 0] = 99
    moved = replace(path, control_points=((0, 0, 0), (6, 0, 0)), revision=2)
    assert line.path_revision == 1 and moved.revision == 2


def test_parallel_initial_direction_fallback_and_rotation_are_deterministic():
    line = centerline(((0, 0, 0), (0, 0, 5)), angle_radians=np.pi / 2)
    np.testing.assert_allclose(line.laterals_patient, np.tile([0, 1, 0], (11, 1)), atol=1e-12)
    np.testing.assert_allclose(line.binormals_patient, np.tile([-1, 0, 0], (11, 1)), atol=1e-12)


def test_coarse_sampling_transports_through_every_unsampled_bend():
    # Nonplanar turn sequence; transporting only output tangents loses its roll.
    points = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 1, 1))
    coarse = centerline(points, step_mm=4, up_patient=(0, 1, 0))
    dense = centerline(points, step_mm=.25, up_patient=(0, 1, 0))
    np.testing.assert_allclose(coarse.laterals_patient[-1], dense.laterals_patient[-1], atol=1e-12)
    np.testing.assert_allclose(coarse.laterals_patient[-1], [0, 0, 1], atol=1e-12)


@pytest.mark.parametrize("pitch", [0., 3.])
def test_arc_and_helix_preserve_length_and_smooth_right_handed_frames(pitch):
    t = np.linspace(0, 1.5 * np.pi, 301)
    points = np.column_stack((10 * np.cos(t), 10 * np.sin(t), pitch * t))
    line = centerline(points, step_mm=.2)
    assert line.length_mm == pytest.approx(np.hypot(10, pitch) * 1.5 * np.pi, rel=.002)
    basis = np.stack((line.tangents_patient, line.laterals_patient, line.binormals_patient), axis=2)
    np.testing.assert_allclose(basis.transpose(0, 2, 1) @ basis, np.broadcast_to(np.eye(3), basis.shape), atol=1e-10)
    np.testing.assert_allclose(np.linalg.det(basis), 1, atol=1e-10)
    assert np.min(np.sum(line.laterals_patient[1:] * line.laterals_patient[:-1], axis=1)) > .99


def test_oversized_sampling_fails_without_allocating_the_requested_grid():
    Error, _, _, _ = api()
    with pytest.raises(Error, match="limit"):
        centerline(((0, 0, 0), (10000, 0, 0)), step_mm=.05)


def test_cancelled_geometry_does_not_return_a_partial_path():
    from qt_dicom_viewer.core.render_cancellation import render_cancellation
    cancelled = Event()
    cancelled.set()
    with render_cancellation(cancelled), pytest.raises(InterruptedError):
        centerline(((0, 0, 0), (10, 0, 0)))
