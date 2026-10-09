import base64
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QImage

from qt_dicom_viewer.core.mpr_voi import plane_mask, VoiEvaluation
from qt_dicom_viewer.ui.segmentation_overlay_renderer import SegmentationOverlayRenderer
from test_mpr_voi_controller import setup_voi, draw
from test_measurement_qml import qt_app
from test_mpr_voi_qml import settle


def legacy_full_plane(evaluation, geometry):
    """Frozen pre-refactor vectorized oracle, including half-voxel rounding."""
    rows, cols = np.indices((geometry.rows, geometry.columns), dtype=np.float32)
    inverse = evaluation.geometry.patient_to_voxel
    origin = inverse[:3, :3] @ geometry.image_origin_patient + inverse[:3, 3]
    u = inverse[:3, :3] @ np.asarray(geometry.column_direction_patient) * geometry.column_spacing
    v = inverse[:3, :3] @ np.asarray(geometry.row_direction_patient) * geometry.row_spacing
    index = np.floor(origin[:, None, None] + u[:, None, None] * cols
                     + v[:, None, None] * rows + .5).astype(int) - evaluation.offset[:, None, None]
    inside = np.all((index >= 0) & (index < np.asarray(evaluation.mask.shape)[:, None, None]), axis=0)
    result = np.zeros(rows.shape, dtype=bool)
    result[inside] = evaluation.mask[tuple(index[:, inside])]
    return result


@pytest.mark.parametrize('origin', [(0., 0., 0.), (.5, -.5, .5), (-7.11, 5.27, 2.6)])
@pytest.mark.parametrize('oblique', [False, True])
def test_blocked_sampling_is_pixel_identical_across_boundaries_and_oblique_planes(setup_voi, origin, oblique):
    _, view, _ = setup_voi
    rng = np.random.default_rng(42)
    result = VoiEvaluation(rng.random((4, 5, 6)) > .3, np.array([2, 3, 1]),
                           view._voi_volume.geometry, {}, None, (0, 1))
    # Subvoxel spacing and a large plane exercise multiple row blocks.
    axes = np.linalg.qr(rng.normal(size=(3, 3)))[0] if oblique else np.eye(3)
    plane = SimpleNamespace(rows=701, columns=419, row_spacing=.021, column_spacing=.017,
                            image_origin_patient=origin,
                            row_direction_patient=axes[:, 1], column_direction_patient=axes[:, 0])
    before = result.mask.copy()
    np.testing.assert_array_equal(plane_mask(result, plane), legacy_full_plane(result, plane))
    np.testing.assert_array_equal(result.mask, before)
    result.mask = np.zeros((0, 0, 0), bool)
    assert not plane_mask(result, plane).any()


def test_cache_validates_pixels_offset_geometry_style_and_keeps_bound(setup_voi, monkeypatch):
    c, view, _ = setup_voi
    draw(c, view); settle(c)
    result, plane = c.evaluations[c.selectedId], view._plane_geometry
    renderer = SegmentationOverlayRenderer(max_entries=2, max_bytes=1024**2)
    import qt_dicom_viewer.ui.segmentation_overlay_renderer as module
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
    import qt_dicom_viewer.ui.segmentation_overlay_renderer as module
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
