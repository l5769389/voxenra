import base64

import numpy as np
from PySide6.QtGui import QImage

from qt_dicom_viewer.core.segmentation_display import segmentation_rgba
from test_mpr_voi_controller import setup_voi, draw
from test_measurement_qml import qt_app
from test_mpr_voi_qml import settle


def test_outline_preserves_holes_islands_and_image_edges():
    mask = np.zeros((12, 15), bool)
    mask[:8, :8] = True
    mask[3:5, 3:5] = False
    mask[10, 12] = True
    before = mask.copy()
    outline = segmentation_rgba(mask, (20, 120, 240), "outline", 30)
    # Independent, explicit four-neighbour definition, including outside image.
    for y, x in np.ndindex(mask.shape):
        edge = mask[y, x] and any(
            not (0 <= yy < 12 and 0 <= xx < 15) or not mask[yy, xx]
            for yy, xx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)))
        assert outline[y, x, 3] == (255 if edge else 0)
    for opacity in (0, 30, 100):
        fill = segmentation_rgba(mask, (20, 120, 240), "fill", opacity)
        both = segmentation_rgba(mask, (20, 120, 240), "fill-outline", opacity)
        assert np.all(fill[mask, 3] == round(255*opacity/100))
        np.testing.assert_array_equal(both[..., 3], np.maximum(fill[..., 3], outline[..., 3]))
        assert not both[~mask, 3].any()
    np.testing.assert_array_equal(mask, before)
    assert not segmentation_rgba(np.zeros((2, 2), bool), (1, 2, 3)).any()


def test_display_does_not_resample_recalculate_or_mutate_masks(setup_voi, monkeypatch):
    c, v, _ = setup_voi
    draw(c, v); settle(c)
    result = c.evaluations[c.selectedId]
    before = result.mask.copy()
    revision = c._revision
    first = c.masks(v)[0]['source']
    import qt_dicom_viewer.ui.controller.tab.mpr_voi_controller as module
    import qt_dicom_viewer.ui.segmentation_overlay_renderer as renderer
    def unexpected(*args, **kwargs):
        raise AssertionError('Display-only change resampled or recalculated')
    monkeypatch.setattr(renderer, 'plane_mask', unexpected)
    monkeypatch.setattr(module, 'evaluate_voi', unexpected)
    dirty = []
    c.selectionChanged.connect(lambda: dirty.append(True))
    for mode in ('outline', 'fill', 'fill-outline'):
        c.setDisplayMode(mode)
        c.setFillOpacity(60)
        source = c.masks(v)[0]['source']
        image = QImage.fromData(base64.b64decode(source.split(',')[1]))
        assert not image.isNull()
        assert source != first
    assert dirty and c._revision == revision
    assert c.evaluations[c.selectedId] is result
    np.testing.assert_array_equal(result.mask, before)
    c.toggleVisible(c.selectedId)
    assert c.masks(v) == []


def test_display_defaults_and_invalid_workspace_settings(setup_voi):
    c, _, _ = setup_voi
    assert (c.displayMode, c.fillOpacity) == ('fill-outline', 30)
    c.restore_selection(dict(version=1))  # old workspace
    assert (c.displayMode, c.fillOpacity) == ('fill-outline', 30)
    c.setDisplayMode('outline'); c.setFillOpacity(74)
    saved = c.persistent_selection()
    c.restore_selection(dict(version=1, displayMode='bad', fillOpacity=float('nan')))
    c.setDisplayMode('bad'); c.setFillOpacity(101); c.setFillOpacity(-1)
    assert c.persistent_selection() == saved
    c.setDisplayMode('fill'); c.setFillOpacity(0)
    c.restore_selection(saved)
    assert (c.displayMode, c.fillOpacity) == ('outline', 74)
