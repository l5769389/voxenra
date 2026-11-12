"""A slice brush must paint the layer selected by the overlay at half voxels."""
from types import SimpleNamespace

import numpy as np
import pytest

from voxplane.core.segmentation_refine import brush
from voxplane.core.mpr_voi import plane_mask
from test_mpr_reslicer import _volume


@pytest.mark.parametrize('axis', [0, 1, 2])
@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('position,want', [(4.49999, 4), (4.5, 5), (4.50001, 5)])
@pytest.mark.parametrize('rotated', [False, True])
def test_brush_layer_agrees_with_visible_plane(axis, sign, position, want, rotated):
    rotation = np.array([[0., -1, 0], [1, 0, 0], [0, 0, 1]]) if rotated else np.eye(3)
    volume = _volume(np.zeros((11, 11, 11)), slice_spacing=2, row_spacing=.8,
                     column_spacing=.6, origin=(10, -20, 30),
                     row_direction=tuple(rotation[:, 0]), column_direction=tuple(rotation[:, 1]),
                     slice_direction=tuple(rotation[:, 2]))
    g = volume.geometry
    index = np.array([5., 5., 5.]); index[axis] = position
    point = (g.voxel_to_patient @ [*index, 1])[:3]
    normal = g.voxel_to_patient[:3, axis].copy()
    normal /= np.linalg.norm(normal)
    mask, offset = brush(np.zeros((1, 1, 1), bool), (5, 5, 5), g, (11, 11, 11),
                         point, point, 3, normal=normal * sign)
    occupied = np.argwhere(mask) + offset
    assert mask.any()
    assert set(occupied[:, axis]) == {want}
    plane = SimpleNamespace(image_origin_patient=point, column_direction_patient=(1, 0, 0),
                            row_direction_patient=(0, 1, 0), column_spacing=1., row_spacing=1.,
                            columns=1, rows=1)
    evaluation = SimpleNamespace(mask=mask, offset=np.asarray(offset), geometry=g)
    assert plane_mask(evaluation, plane)[0, 0]
    erased, _ = brush(mask, offset, g, (11, 11, 11), point, point, 3,
                      normal=-normal * sign, erase=True)
    assert not erased.any(), 'Reversing the view normal must erase the same voxels'


def test_oblique_brush_is_invariant_under_normal_reversal():
    volume = _volume(np.zeros((11, 11, 11)))
    point = np.array([5., 5., 4.5])
    normal = np.array([1., 1., 2.]); normal /= np.linalg.norm(normal)
    painted = []
    for sign in (1, -1):
        mask, offset = brush(np.zeros((1, 1, 1), bool), (5, 5, 5), volume.geometry,
                             (11, 11, 11), point, point, 5, normal=sign * normal)
        painted.append({tuple(x) for x in np.argwhere(mask) + offset})
    assert painted[0]
    assert painted[0] == painted[1]


@pytest.mark.parametrize('plane_name', ['AXIAL', 'CORONAL', 'SAGITTAL'])
def test_default_even_volume_brush_has_visible_preview_and_result(setup_voi, plane_name):
    import base64
    from PySide6.QtGui import QImage
    from voxplane.core.mpr_reslicer import MprReslicer
    from voxplane.model import MprPlane, MprFrame
    controller, viewport, _ = setup_voi
    volume = _volume(np.full((10, 10, 10), 500.))
    viewport._voi_volume = volume
    viewport._plane_geometry = MprReslicer().reslice(
        volume, getattr(MprPlane, plane_name), MprFrame(volume.geometry.center_patient)).geometry
    controller.set_source(volume)
    controller.newSegment()
    controller.setBrushDiameter(3)
    controller.begin(viewport, 4, 4, .1)
    controller.update(viewport, 5, 4)

    def assert_visible():
        sources = controller.masks(viewport)
        assert len(sources) == 1
        image = QImage.fromData(base64.b64decode(sources[0]['source'].split(',')[1]))
        assert not image.isNull()
        assert any(image.pixelColor(x, y).alpha() for y in range(image.height())
                   for x in range(image.width()))
    assert_visible()
    controller.finish(viewport, 5, 4)
    assert controller.evaluations[controller.selectedId].metrics['count'] > 0
    assert_visible()


from test_mpr_voi_controller import setup_voi
from test_measurement_qml import qt_app


@pytest.mark.parametrize('sign', [1, -1])
def test_oblique_slab_boundary_retains_visible_brush_center(sign):
    volume = _volume(np.zeros((11, 11, 11)))
    point = np.array([1.3, 1.4, 5.])
    mask, offset = brush(np.zeros((1, 1, 1), bool), (5, 1, 1), volume.geometry,
                         (11, 11, 11), point, point, 3, normal=np.array([.6, .8, 0])*sign)
    plane = SimpleNamespace(image_origin_patient=point, column_direction_patient=(0, 0, 1),
                            row_direction_patient=(.8, -.6, 0), column_spacing=1., row_spacing=1.,
                            columns=1, rows=1)
    evaluation = SimpleNamespace(mask=mask, offset=np.asarray(offset), geometry=volume.geometry)
    assert plane_mask(evaluation, plane)[0, 0]
