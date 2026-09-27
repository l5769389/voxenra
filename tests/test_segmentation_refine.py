from dataclasses import replace
import numpy as np
import pytest
from qt_dicom_viewer.core.segmentation_refine import brush, connected_component
from test_mpr_reslicer import _volume
from test_mpr_voi_controller import setup_voi, draw
from test_measurement_qml import qt_app
from test_mpr_voi_qml import settle


def full(mask, offset, shape):
    result = np.zeros(shape, bool)
    result[tuple(slice(a,a+b) for a,b in zip(offset, mask.shape))] = mask
    return result


def test_physical_sphere_and_slice_on_anisotropic_rotated_grid():
    v = _volume(np.zeros((11,21,31)), slice_spacing=2.5, row_spacing=.7, column_spacing=.4,
        origin=(10.,-20.,30.))
    g=v.geometry
    center=(g.voxel_to_patient @ [5,10,15,1])[:3]
    empty=np.zeros((1,1,1),bool)
    mask,offset=brush(empty,(5,10,15),g,v.modality_pixels.shape,center,center,4)
    indices=np.indices(v.modality_pixels.shape).reshape(3,-1).T
    points=indices@g.voxel_to_patient[:3,:3].T+g.voxel_to_patient[:3,3]
    expected=(np.linalg.norm(points-center,axis=1)<=2+1e-9).reshape(v.modality_pixels.shape)
    np.testing.assert_array_equal(full(mask,offset,expected.shape),expected)
    normal=np.asarray(g.slice_index_direction_patient)
    mask,offset=brush(empty,(5,10,15),g,v.modality_pixels.shape,center,center,8,normal=normal)
    actual=full(mask,offset,expected.shape)
    assert np.flatnonzero(actual.any(axis=(1,2))).tolist()==[5]


def test_capsules_have_no_gaps_and_erase_only_selected_mask():
    v=_volume(np.zeros((7,20,20)))
    g=v.geometry
    a,b=[(g.voxel_to_patient@[3,10,x,1])[:3] for x in (3,16)]
    mask,offset=brush(np.zeros((1,1,1),bool),(3,10,3),g,v.modality_pixels.shape,a,b,3)
    before=mask.copy()
    erased,new_offset=brush(mask,offset,g,v.modality_pixels.shape,a,b,3,erase=True)
    assert not erased.any()
    np.testing.assert_array_equal(mask,before)
    assert full(mask,offset,v.modality_pixels.shape)[3,10,3:17].all()


def test_face_connected_island_excludes_corner_touching_component():
    mask=np.zeros((8,9,10),bool)
    mask[1:4,1:4,1:4]=True
    mask[4:6,4:6,4:6]=True
    result=connected_component(mask,(2,2,2))
    assert result.sum()==27 and mask.sum()==35
    with pytest.raises(ValueError): connected_component(mask,(0,0,0))


def test_refine_preview_cancel_commit_and_empty_then_repaint(setup_voi):
    c,v,t=setup_voi
    c.newSegment()
    c.begin(v,4,4,.1)
    c.update(v,6,4)
    assert not c.records
    assert c.masks(v)
    c.cancel()
    assert not c.records and not c.masks(v)
    c.begin(v,4,4,.1); c.finish(v,6,4)
    record=c.records[0]
    assert 'mask' in record and record['mask'].sum()>0
    c.setEditMode('erase'); c.setBrushDiameter(100)
    c.begin(v,5,5,.1); c.finish(v,5,5)
    assert c.evaluations[c.selectedId].metrics['count']==0
    assert c.evaluations[c.selectedId].metrics['mean'] is None
    c.setEditMode('paint'); c.setBrushDiameter(3)
    c.begin(v,5,5,.1); c.finish(v,5,5)
    assert c.evaluations[c.selectedId].metrics['count']>0
    assert c.selectedId==record['id']


def test_threshold_edit_converts_only_on_commit_and_phase_cancels(setup_voi):
    c,v,t=setup_voi
    draw(c,v); settle(c)
    original=c.records[0]
    c.setEditMode('paint')
    c.begin(v,5,5,.1)
    c.cancel()
    assert 'mask' not in c.records[0]
    c.begin(v,5,5,.1); c.finish(v,5,5)
    assert c.records[0]['id']==original['id'] and 'mask' in c.records[0]
    c.begin(v,5,5,.1)
    c.set_phase(1,ready=False)
    c.finish(v,7,7)
    assert c._draft is None and len(c.records)==1


def test_relative_diameter_uses_each_view_and_freezes_for_stroke(setup_voi):
    c, v, _ = setup_voi
    c.newSegment()
    c.setBrushRelative(True)
    assert c.brushPercent == 3
    assert c.brush_diameter_for_view(v) is None
    v._brush_view_metrics = (2., 400.)
    assert c.brush_diameter_for_view(v) == 6
    c.begin(v, 4, 4, .1)
    assert c._draft['diameter'] == 6
    # Resizing/zooming cannot change the physical radius of a stroke in flight.
    v._brush_view_metrics = (4., 400.)
    c.update(v, 5, 4)
    assert c._draft['diameter'] == 6
    c.cancel()
    c.begin(v, 4, 4, .1)
    assert c._draft['diameter'] == 3
    c.cancel()
    from types import SimpleNamespace
    other = SimpleNamespace(_brush_view_metrics=(2., 800.))
    assert c.brush_diameter_for_view(other) == 12
    c.setBrushPercent(26)
    assert c.brushPercent == 3
    c.setBrushRelative(False)
    c.setBrushDiameter(100)
    c.setBrushDiameter(101)
    assert c.brushDiameter == c.brush_diameter_for_view(v) == 100
    c.setBrushRelative(True)
    assert c.brushPercent == 3


def test_new_segments_use_unused_colors_and_keep_preview_color(setup_voi):
    c, v, _ = setup_voi
    colors = set()
    for i in range(10):
        c.newSegment()
        c.begin(v, 4, 4, .1)
        preview = c._draft['color']
        assert preview.lower() not in colors
        c.finish(v, 5, 4)
        assert c.records[-1]['color'] == preview
        colors.add(preview.lower())
        if i == 0:
            c.records[0]['color'] = preview.upper()
            c.toggleVisible(c.records[0]['id'])
    # Editing an existing mask must retain its assigned color.
    c.select(c.records[-1]['id'])
    c.setEditMode('erase')
    before = c.records[-1]['color']
    c.begin(v, 4, 4, .1)
    assert c._draft['color'] == before
    c.finish(v, 5, 4)
    assert c.records[-1]['color'] == before


def test_refinement_selection_legacy_and_invalid_fields_are_safe(setup_voi):
    c, v, _ = setup_voi
    c.newSegment(); c.begin(v, 4, 4, .1); c.finish(v, 5, 4)
    c.setEditMode('erase'); c.setBrushDiameter(12)
    before = c.persistent_selection()
    for state in (None, [], {}, {'version': 99}):
        c.restore_selection(state)
        assert c.persistent_selection() == before
    c.restore_selection(dict(version=1, mode='delete', selected='missing', diameter=float('nan'),
                             percent=10000, relative='yes', enabled=0))
    assert c.persistent_selection() == before
    c.begin(v, 4, 4, .1)
    assert c._draft
    c.restore_selection(before)
    assert c._draft is None and c.persistent_selection() == before
