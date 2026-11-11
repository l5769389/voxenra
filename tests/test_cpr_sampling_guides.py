"""CPR guide geometry distinguishes real in-plane lines from projections."""
from dataclasses import replace
import numpy as np
import pytest
from voxplane.model.dicom_core import MprFrame, MprImageGeometry
from voxplane.ui.cpr_sampling_guides import project_sampling_line


def reference():
    return MprImageGeometry(rows=13, columns=11, row_spacing=2., column_spacing=3.,
        navigation_spacing=4., frame=MprFrame.standard_lps((12., 15., 20.)),
        image_origin_mpr=(-15., -12., 0.), row_direction_mpr=(0., 1., 0.),
        column_direction_mpr=(1., 0., 0.), navigation_direction_mpr=(0., 0., 1.))


@pytest.mark.parametrize('direction,projected', [((1., 0., 0.), False), ((0., 0., 1.), False),
                                               ((2**-.5, 0., 2**-.5), True)])
def test_sampling_line_is_projected_in_physical_space(direction, projected):
    geo = reference()
    guide = project_sampling_line(geo, (12., 15., 20.), direction, 20.)
    assert guide['centerColumn'] == pytest.approx(5)
    assert guide['centerRow'] == pytest.approx(6)
    assert guide['centerOnPlane']
    assert guide['projected'] is projected
    np.testing.assert_allclose([guide['startColumn'], guide['endColumn']],
                               [5 - 10*direction[0]/3, 5 + 10*direction[0]/3])
    assert guide['startRow'] == guide['endRow'] == pytest.approx(6)


def test_parallel_line_on_another_slice_is_labeled_as_projection():
    guide = project_sampling_line(reference(), (12., 15., 24.), (1., 0., 0.), 20.)
    assert guide['projected'] and not guide['centerOnPlane']


def test_perpendicular_point_on_another_slice_stays_a_labeled_projection():
    guide = project_sampling_line(reference(), (12., 15., 24.), (0., 0., 1.), 20.)
    assert guide['projected'] and not guide['centerOnPlane']
    assert guide['startColumn'] == guide['endColumn']
    assert guide['startRow'] == guide['endRow']


def test_rotated_reference_basis_preserves_physical_endpoints():
    geo = replace(reference(), row_direction_mpr=(-1., 0., 0.), column_direction_mpr=(0., 1., 0.))
    center = np.array((12., 15., 20.))
    direction = np.array((2**-.5, 2**-.5, 0.))
    guide = project_sampling_line(geo, center, direction, 20.)
    for prefix, sign in [('start', -1), ('end', 1)]:
        patient = geo.image_point_to_patient(column=guide[prefix+'Column'], row=guide[prefix+'Row'])
        np.testing.assert_allclose(patient, center + sign*10*direction)
    assert not guide['projected']
