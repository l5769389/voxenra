"""QA resizing and conservative external-air placement on original HU pixels."""
from dataclasses import replace
import numpy as np
import pytest

from voxplane.core.water_qa import analyze_water_phantom, find_external_air_roi
from test_water_qa import water_image
from test_water_qa_controller import qa_view, wait_qa, water_render, deliver_frame
from test_measurement_qml import qt_app
from test_qa_edit_history import qa_work


def air_image(spacing=(1, 1), shape=(320, 400), center=(204.2, 149.4)):
    pixels = water_image(shape, spacing, center)
    air = pixels == -1000
    pixels[air] = np.random.default_rng(31).normal(-995, 12, air.sum())
    return pixels


@pytest.mark.parametrize('spacing,shape,center', [((1, 1), (320, 400), (204.2,149.4)),
    ((.7,.5), (400,512), (260,190))])
def test_auto_air_avoids_phantom_support_padding_and_measures_unfiltered_samples(spacing, shape, center):
    pixels = air_image(spacing, shape, center)
    pixels[:12] = np.nan
    pixels[-25:] = 250  # Table/support, not air.
    result = analyze_water_phantom(pixels, spacing)
    before = pixels.copy()
    roi = find_external_air_roi(pixels, spacing, result.phantom)
    assert roi is not None and roi.group == 'air'
    y,x = np.indices(shape)
    mask = ((x-roi.column)*spacing[1])**2 + ((y-roi.row)*spacing[0])**2 <= roi.radius_mm**2
    values = pixels[mask].astype(float)
    assert roi.pixel_count == len(values)
    assert roi.mean_hu == pytest.approx(values.mean())
    assert roi.std_hu == pytest.approx(values.std())
    distance = np.hypot((roi.column-result.phantom.column)*spacing[1], (roi.row-result.phantom.row)*spacing[0])
    assert distance > result.phantom.radius_mm+roi.radius_mm+3
    assert np.isfinite(values).all() and (values < -700).all()
    np.testing.assert_array_equal(pixels, before)


def test_auto_air_declines_constant_fill_unknown_phantom_and_too_large_circle():
    pixels = water_image()
    result = analyze_water_phantom(pixels, (1,1))
    assert find_external_air_roi(pixels, (1,1), result.phantom) is None
    pixels = air_image()
    assert find_external_air_roi(pixels, (1,1), None) is None
    assert find_external_air_roi(pixels, (1,1), result.phantom, 300) is None


def test_auto_air_once_per_slice_and_user_deletion_is_preserved(qa_view, qt_app):
    view, _ = qa_view
    qa = view.qaController
    frame = water_render(view, pixels=air_image())
    deliver_frame(view, frame)
    qa.activate(); wait_qa(qt_app, qa)
    initial = qa.currentResult
    qa.setActiveGroup('air'); wait_qa(qt_app, qa)
    assert len(qa.roiItems) == 1 and qa.roiItems[0]['key'] == 'air-1'
    assert qa.currentResult['rois'][:-1] == initial['rois']
    assert qa.deleteRoi('air-1')
    saved = qa.persistent_state()
    qa.setActiveGroup('noise'); qa.setActiveGroup('air')
    assert not qa.roiItems and qa.status == 'ready'
    qa.restore_state(saved)
    assert not qa.roiItems
    deliver_frame(view, water_render(view, index=1, pixels=air_image()))
    qa.analyze()  # Restored documents do not auto-analyze previously unsaved slices.
    wait_qa(qt_app, qa)
    assert len(qa.roiItems) == 1
    deliver_frame(view, frame)
    assert not qa.roiItems


@pytest.mark.parametrize('axis,sign', [(0,1),(1,1),(0,-1),(1,-1)])
def test_selected_handle_resizes_only_one_circle_on_release_and_undo_redo(qa_work, axis, sign):
    _, _, _, qa, history = qa_work
    before = qa.currentResult
    roi = qa._result.rois[0]
    qa.select_at(roi.column, roi.row)
    p = [roi.column, roi.row]
    p[axis] += sign*roi.radius_mm  # Fixture has 1 mm pixels.
    qa.begin_drag(*p)
    assert qa.dragging and qa._resize_handle
    p[axis] += sign*4
    qa.update_drag(*p)
    assert qa.currentResult == before
    assert qa.roiItems[0]['radiusColumn'] == pytest.approx(roi.radius_mm+4)
    qa.end_drag(*p); history.capture()
    resized = qa.currentResult
    assert not qa.error
    assert resized['rois'][0]['radius_mm'] == pytest.approx(roi.radius_mm+4)
    for actual, previous in zip(resized['rois'][1:], before['rois'][1:]):
        assert {k:v for k,v in actual.items() if k != 'delta_center_hu'} == {k:v for k,v in previous.items() if k != 'delta_center_hu'}
    assert resized['rois'][0]['column'] == roi.column and resized['rois'][0]['row'] == roi.row
    history.undo(); assert qa.currentResult == before
    history.redo(); assert qa.currentResult == resized


def test_handle_cancel_and_large_center_after_removing_peripheral_circles(qa_work):
    _, _, _, qa, _ = qa_work
    for key in ('left','right','top','bottom'):
        assert qa.deleteRoi(key)
    before = qa.currentResult
    roi = qa._result.rois[0]
    qa.select_at(roi.column, roi.row)
    qa.begin_drag(roi.column+roi.radius_mm, roi.row)
    qa.update_drag(roi.column+500, roi.row)
    assert qa.roiItems[0]['radiusColumn'] > 90
    qa.cancel_drag()
    assert qa.currentResult == before
    qa.begin_drag(roi.column+roi.radius_mm, roi.row)
    qa.end_drag(roi.column+80, roi.row)
    assert not qa.error and qa.currentResult['rois'][0]['radius_mm'] == pytest.approx(80)
    assert qa.currentResult['uniformity_hu'] is None


def test_auto_air_no_candidate_does_not_add_undo_entry(qa_work, qt_app):
    _, _, _, qa, history = qa_work
    qa.setActiveGroup('air'); wait_qa(qt_app, qa); history.capture()
    assert not qa.roiItems and not history.canUndo
    assert '手动' in qa.notice


def test_air_parameter_maximum_respects_phantom_clearance(qa_view, qt_app):
    qa = qa_view[0].qaController
    qa.activate(); wait_qa(qt_app, qa)
    phantom = qa._result.phantom
    qa.setActiveGroup('air'); wait_qa(qt_app, qa)
    qa.placeAirRoi()
    assert qa.begin_drag(phantom.column + phantom.radius_mm + 15, phantom.row)
    assert len(qa.roiItems) == 1
    assert qa.maximumRoiDiameterMm == pytest.approx(30)
    qa.setActiveDiameterMm(40); wait_qa(qt_app, qa)
    assert qa.status == 'ready' and not qa.error
    assert next(r.radius_mm for r in qa._result.rois if r.group == 'air') <= 15
    qa.setActiveDiameterMm(28); wait_qa(qt_app, qa)
    assert qa.status == 'ready' and not qa.error
    assert next(r.radius_mm for r in qa._result.rois if r.group == 'air') == pytest.approx(14)
