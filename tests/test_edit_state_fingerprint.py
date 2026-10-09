import base64
from dataclasses import replace
import zlib

import numpy as np
import pytest

from qt_dicom_viewer.core.workspace_state import dumps, loads, encode, fingerprint
from qt_dicom_viewer.ui.workspace_snapshot import edit_signature


def test_masks_keep_portable_encoding_and_content_changes_are_detected(monkeypatch):
    mask = np.random.default_rng(5).random((7, 13, 17)) > .6
    for value in (mask, np.asfortranarray(mask), mask[:, ::-1, ::2]):
        legacy = {"$mask": base64.b64encode(zlib.compress(np.packbits(value.reshape(-1)).tobytes())).decode(),
                  "shape": list(value.shape)}
        assert encode(value) == legacy
        np.testing.assert_array_equal(loads(dumps(value)), value)
        assert fingerprint(value) == fingerprint(value.copy())
    original = fingerprint(mask)
    # No compression during signatures, including nested containers.
    monkeypatch.setattr(zlib, 'compress', lambda *a: pytest.fail('signature compressed a mask'))
    assert fingerprint(mask) == original
    state = {'views': {}, 'voi': [{'mask': mask, 'visible': True}]}
    before = edit_signature(state)
    mask[2, 3, 4] = not mask[2, 3, 4]
    assert edit_signature(state) != before  # Same array identity, different voxels.
    mask[2, 3, 4] = not mask[2, 3, 4]
    assert edit_signature(state) == before
    state['voi'][0]['visible'] = False
    assert edit_signature(state) != before
    assert fingerprint(mask.reshape(13, 7, 17)) != original


def test_signature_preserves_type_and_metadata_distinctions():
    from qt_dicom_viewer.model import ImagePoint
    for a, b in (([1, 2], (1, 2)),
                 (ImagePoint(1., 2.), ImagePoint(2., 1.)),
                 ({'name': 'one'}, {'name': 'two'}),
                 ({'phase': 0}, {'phase': 1}),
                 (np.eye(4), np.eye(4) * 2)):
        assert fingerprint(a) != fingerprint(b)
        assert fingerprint(a) == fingerprint(loads(dumps(a)))
    with pytest.raises(ValueError):
        fingerprint(np.ones((33,), np.float64))
    with pytest.raises(ValueError):
        fingerprint({'$maskDigest': 'untrusted'})


def test_signature_ignores_roi_statistics_but_not_geometry():
    from qt_dicom_viewer.model.measure import RoiMeasurement, RoiMetrics, MeasurementKind
    from qt_dicom_viewer.model import ImagePoint
    roi = RoiMeasurement('roi', 'series', 'sop', 0, MeasurementKind.RECT,
                         (ImagePoint(1., 2.), ImagePoint(4., 6.)), RoiMetrics())
    state = {'views': {'a': {'measurements': {'roi': roi}}}}
    signature = edit_signature(state)
    state['views']['a']['measurements']['roi'] = replace(roi, metrics=replace(roi.metrics, mean=100.))
    assert edit_signature(state) == signature
    state['views']['a']['measurements']['roi'] = replace(roi, points=(roi.points[0], ImagePoint(5., 6.)))
    assert edit_signature(state) != signature
