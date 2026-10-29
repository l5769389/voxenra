from dataclasses import replace
from threading import Event

import numpy as np
import pytest

from qt_dicom_viewer.model.cpr import CprPath, CprSettings
from qt_dicom_viewer.model import MprPlane
from test_mpr_reslicer import _volume
from test_dicom_tags import qt_app, wait_until


def request(generation=1, **changes):
    from qt_dicom_viewer.ui.workers.cpr_render_task import CprRenderInput
    z, y, x = np.indices((21, 21, 21))
    volume = _volume(100*z + 10*y + x)
    path = CprPath("p", "Path", ((2, 10, 10), (18, 10, 10)))
    return CprRenderInput(**(dict(generation=generation, volume=volume, path=path,
        settings=CprSettings(width_mm=6, step_mm=.5), position_mm=4,
        reference_planes=(MprPlane.AXIAL, MprPlane.CORONAL),
        reference_centers=((10., 10., 10.), (10., 10., 10.)), cross_width_mm=6) | changes))


def test_compute_returns_real_reference_and_cross_section_at_requested_distance():
    from qt_dicom_viewer.ui.workers.cpr_render_task import compute_cpr
    result = compute_cpr(request())
    assert len(result.references) == 2
    assert result.curve.modality_pixels.shape == (13, 33)
    assert result.section.distance_mm == 4
    np.testing.assert_allclose(result.section.geometry.frame.center_patient, (6, 10, 10))
    assert result.references[0].modality_pixels[10, 10] == 1110


def test_reference_only_loading_and_preview_are_explicit():
    from qt_dicom_viewer.ui.workers.cpr_render_task import compute_cpr
    empty = compute_cpr(request(path=None))
    assert empty.curve is None and empty.section is None and len(empty.references) == 2
    preview = compute_cpr(request(preview=True))
    full = compute_cpr(request())
    assert preview.preview and not full.preview
    assert preview.curve.modality_pixels.size < full.curve.modality_pixels.size


def test_navigation_cache_never_reuses_different_path_at_same_revision_or_other_volume():
    from qt_dicom_viewer.ui.workers.cpr_render_task import compute_cpr
    req = request()
    first = compute_cpr(req)
    second = compute_cpr(replace(req, generation=2, position_mm=6, cache=first.cache))
    assert second.curve is first.curve
    changed = replace(req.path, control_points=((2, 11, 10), (18, 11, 10)))
    third = compute_cpr(replace(req, path=changed, cache=first.cache))
    assert third.curve is not first.curve
    np.testing.assert_allclose(third.curve.modality_pixels-first.curve.modality_pixels, 10)
    fourth = compute_cpr(replace(req, volume=replace(req.volume), cache=first.cache))
    assert fourth.curve is not first.curve


def test_full_result_recomputes_after_preview_and_reference_field_does_not_follow_in_plane():
    from qt_dicom_viewer.ui.workers.cpr_render_task import compute_cpr
    req = request()
    preview = compute_cpr(replace(req, preview=True))
    full = compute_cpr(replace(req, cache=preview.cache))
    assert full.curve is not preview.curve
    assert full.curve.settings == req.settings
    moved = compute_cpr(replace(req, reference_centers=((2., 5., 10.), (2., 10., 5.))))
    for first, second in zip(full.references, moved.references):
        assert first.geometry == second.geometry
        np.testing.assert_array_equal(first.modality_pixels, second.modality_pixels)


def test_queue_discards_cancelled_and_coalesces_to_latest_request(qt_app):
    from qt_dicom_viewer.ui.workers.cpr_render_task import CprRenderQueue, compute_cpr
    entered, release = Event(), Event()
    seen = []
    def slow(req):
        seen.append(req.generation)
        if req.generation == 1:
            entered.set()
            release.wait(3)
        return compute_cpr(req)
    queue = CprRenderQueue(compute=slow)
    results, failures = [], []
    queue.finished.connect(results.append)
    queue.failed.connect(lambda *args: failures.append(args))
    try:
        req = request()
        queue.submit(req)
        wait_until(entered.is_set)
        queue.submit(replace(req, generation=2))
        queue.submit(replace(req, generation=3))
        release.set()
        wait_until(lambda: len(results) == 1)
        assert results[0].generation == 3
        assert seen == [1, 3] and not failures
    finally:
        release.set()
        queue.close()


def test_close_during_job_never_publishes_to_closed_queue(qt_app):
    from qt_dicom_viewer.ui.workers.cpr_render_task import CprRenderQueue, compute_cpr
    entered, release = Event(), Event()
    def slow(req):
        entered.set()
        release.wait(3)
        return compute_cpr(req)
    queue = CprRenderQueue(compute=slow)
    results = []
    queue.finished.connect(results.append)
    queue.submit(request())
    wait_until(entered.is_set)
    queue.close()
    release.set()
    wait_until(lambda: not queue.running)
    assert not results


def test_current_failure_is_reported_and_queue_recovers(qt_app):
    from qt_dicom_viewer.ui.workers.cpr_render_task import CprRenderQueue, compute_cpr
    def fail_once(req):
        if req.generation == 1:
            raise ValueError("Invalid path")
        return compute_cpr(req)
    queue = CprRenderQueue(compute=fail_once)
    failures, results = [], []
    queue.failed.connect(lambda generation, message: failures.append((generation, message)))
    queue.finished.connect(results.append)
    try:
        req = request()
        queue.submit(req)
        wait_until(lambda: bool(failures))
        assert failures == [(1, "Invalid path")]
        queue.submit(replace(req, generation=2))
        wait_until(lambda: bool(results))
        assert results[0].generation == 2
    finally:
        queue.close()
