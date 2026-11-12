import base64
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QImage

from voxplane.core.mpr_voi import plane_mask, VoiEvaluation
from voxplane.ui.segmentation_overlay_renderer import SegmentationOverlayRenderer
from test_mpr_voi_controller import setup_voi, draw
from test_measurement_qml import qt_app
from test_mpr_voi_qml import settle


@pytest.mark.parametrize('half_offset', [-1e-6, 0., 1e-6])
@pytest.mark.parametrize('oblique', [False, True])
def test_blocked_sampling_is_pixel_identical_across_boundaries_and_oblique_planes(half_offset, oblique):
    # Native voxel coordinates equal patient coordinates in this independent
    # phantom. An asymmetric periodic mask supplies foreground AND background
    # along every block seam; the z origin straddles the nearest-neighbor tie.
    z, y, x = np.indices((4, 8, 8))
    mask = (z + 2*y + 3*x) % 5 < 2
    result = VoiEvaluation(mask, np.array([2, 3, 1]),
                           SimpleNamespace(patient_to_voxel=np.eye(4)), {}, None, (0, 1))
    tilt = .1 if oblique else 0.
    row_y = np.sqrt(1 - tilt**2)
    plane = SimpleNamespace(rows=701, columns=419, row_spacing=.01, column_spacing=.02,
                            image_origin_patient=(3.5 + half_offset, 3., 1.),
                            row_direction_patient=(tilt, row_y, 0.), column_direction_patient=(0., 0., 1.))
    rows, cols = np.indices((701, 419))
    # Analytic lattice oracle: no production transform or sampling helper.
    iz = np.floor(3.5 + half_offset + rows*.01*tilt + .5).astype(int) - 2
    iy = np.floor(rows*.01*row_y + .5).astype(int)
    ix = np.floor(cols*.02 + .5).astype(int)
    expected = ((iz + 2*iy + 3*ix) % 5 < 2) & (ix < 8) & (iy < 8) & (iz < 4)
    for seam in (156, 312, 468, 624):
        for row in (seam - 1, seam):
            assert expected[row].any() and (~expected[row]).any(), 'Fixture must exercise each side of every seam'
    before = result.mask.copy()
    np.testing.assert_array_equal(plane_mask(result, plane), expected)
    np.testing.assert_array_equal(result.mask, before)


def test_empty_cropped_mask_has_no_plane_foreground():
    result = VoiEvaluation(np.zeros((0, 0, 0), bool), np.array([2, 3, 1]),
                           SimpleNamespace(patient_to_voxel=np.eye(4)), {}, None, (0, 1))
    plane = SimpleNamespace(rows=701, columns=419, row_spacing=.01, column_spacing=.02,
                            image_origin_patient=(3.5, 3., 1.),
                            row_direction_patient=(0., 1., 0.), column_direction_patient=(0., 0., 1.))
    actual = plane_mask(result, plane)
    assert actual.shape == (701, 419)
    assert not actual.any()


def test_cache_validates_pixels_offset_geometry_style_and_keeps_bound(setup_voi, monkeypatch):
    c, view, _ = setup_voi
    draw(c, view); settle(c)
    result, plane = c.evaluations[c.selectedId], view._plane_geometry
    renderer = SegmentationOverlayRenderer(max_entries=2, max_bytes=1024**2)
    import voxplane.ui.segmentation_overlay_renderer as module
    actual = module.plane_mask
    calls = []
    def sample(*args):
        calls.append(True)
        return actual(*args)
    monkeypatch.setattr(module, 'plane_mask', sample)
    def source(evaluation=result, g=plane, view_id='a', mode='fill-outline', opacity=30):
        return renderer.source(view_id, 'segment', evaluation, g, '#34bbcc', mode, opacity)
    first = source()
    assert source(replace(result)) == first and len(calls) == 1
    assert source(opacity=60) != first and len(calls) == 1
    assert source(mode='outline') != first and len(calls) == 1
    replacement = replace(result, mask=~result.mask)
    assert source(replacement) != first and len(calls) == 2
    shifted = replace(result, offset=result.offset + 1)
    source(shifted)
    assert len(calls) == 3
    source(replace(shifted, geometry=replace(result.geometry, origin_patient=(10., 0., 0.))))
    assert len(calls) == 4
    source(g=replace(plane, column_spacing=.5))
    assert len(calls) == 5
    source(view_id='b'); source(view_id='c')
    assert len(renderer._entries) == 2
    assert renderer._bytes == sum(e.display_bytes for e in renderer._entries.values())
    renderer.retain(set())
    assert not renderer._entries and renderer._bytes == 0
    tiny = SegmentationOverlayRenderer(max_bytes=1)
    image = tiny.source('a', 'segment', result, plane, '#34bbcc', 'fill', 30)
    assert not QImage.fromData(base64.b64decode(image.split(',')[1])).isNull()
    assert not tiny._entries


def test_display_cache_does_not_retain_obsolete_volume_masks(setup_voi):
    import gc
    from weakref import ref
    c, view, _ = setup_voi
    draw(c, view); settle(c)
    temporary = replace(c.evaluations[c.selectedId], mask=np.ones((30, 40, 50), bool))
    reference = ref(temporary.mask)
    renderer = SegmentationOverlayRenderer()
    renderer.source('a', 'segment', temporary, view._plane_geometry, '#34bbcc', 'fill', 30)
    del temporary
    gc.collect()
    assert reference() is None
    assert renderer._entries  # The small, completed 2D display remains reusable.


def test_repeated_brush_preview_reads_reuse_sample_but_new_stroke_and_cancel_do_not(setup_voi, monkeypatch):
    c, view, _ = setup_voi
    c.newSegment(); c.begin(view, 3, 3, .1)
    before = c.masks(view)
    import voxplane.ui.segmentation_overlay_renderer as module
    actual = module.plane_mask
    calls = []
    def sample(*args):
        calls.append(True)
        return actual(*args)
    monkeypatch.setattr(module, 'plane_mask', sample)
    for _ in range(5):
        assert c.masks(view) == before
    assert not calls
    c.update(view, 7, 7)
    assert c.masks(view) != before and len(calls) == 1
    c.finish(view, 7, 7)
    committed = c.masks(view)
    c.setEditMode('erase'); c.begin(view, 3, 3, .1)
    assert c.masks(view) != committed
    c.cancel()
    assert c.masks(view) == committed
    c.newSegment(); c.begin(view, 3, 3, .1)
    draft_id = c._draft['id']
    c.masks(view)
    c.cancel()
    assert all(key[1] != draft_id for key in c._mask_renderer._entries)
