from copy import deepcopy

import numpy as np
import pytest

from voxplane.model.cpr import CprPath, CprSettings, CprError


def api():
    from voxplane.core.cpr_session import default_cpr_session, path_record, unpack_path, validate_cpr_session
    return default_cpr_session, path_record, unpack_path, validate_cpr_session


def test_source_fingerprint_keeps_published_2_5_identity_after_product_rename():
    from test_mpr_reslicer import _volume
    from voxplane.core.cpr_session import volume_content_fingerprint

    volume = _volume(np.arange(24).reshape(2, 3, 4), origin=(10., 20., 30.),
                     slice_spacing=2.5, row_spacing=.8, column_spacing=.6)
    # Golden value produced by the released v2.5.0 implementation, not this code.
    expected = "6896e1783fcb87666a74b7b9dcb9bba4b3f9fea4a7ed406cfeeda7188f9ffb8c"
    assert volume_content_fingerprint(volume) == expected
    volume.modality_pixels[0, 0, 0] += 1
    assert volume_content_fingerprint(volume) != expected


def test_session_roundtrip_retains_paths_settings_source_and_incomplete_draft():
    from voxplane.core.workspace_state import dumps, loads
    default, pack, unpack, validate = api()
    state = default("series", "frame")
    state["source"]["fingerprint"] = "hash"
    path = CprPath("a", "Artery", ((1, 2, 3), (5, 6, 7)), revision=3)
    settings = CprSettings(angle_radians=.4, projection="mean", thickness_mm=2)
    state.update(paths=[pack(path, settings)], selected="a", draft=((1, 1, 1),),
                 referenceCenters=((3, 4, 5), (6, 7, 8)))
    restored = validate(loads(dumps(validate(state))))
    assert unpack(restored["paths"][0]) == (path, settings)
    assert restored["source"] == state["source"]
    assert restored["draft"] == ((1., 1., 1.),)
    assert restored["referenceCenters"] == ((3., 4., 5.), (6., 7., 8.))


@pytest.mark.parametrize("field,value", [("selected", "missing"), ("positionMm", -1),
    ("positionMm", np.nan), ("algorithmVersion", 99), ("crossWidthMm", 0),
    ("referencePlanes", ("axial", "invalid")), ("referenceCenters", ((1, 2, 3), (1, 2))),
    ("draft", ((0, 0, np.inf),)), ("paths", ["invalid"]), ("focusedRole", "invalid")])
def test_invalid_restored_session_is_rejected_atomically(field, value):
    default, _, _, validate = api()
    state = default("series", "frame")
    state[field] = value
    before = deepcopy(state)
    with pytest.raises((CprError, ValueError)):
        validate(state)
    assert repr(state) == repr(before)


def test_duplicate_path_ids_and_source_identity_are_not_silently_accepted():
    default, pack, _, validate = api()
    state = default("series", "frame")
    record = pack(CprPath("a", "Artery", ((0, 0, 0), (5, 0, 0))), CprSettings())
    state.update(paths=[record, record], selected="a")
    with pytest.raises(CprError):
        validate(state)
    state = default("series", "frame")
    state["source"]["seriesUid"] = ""
    with pytest.raises(CprError):
        validate(state)


def test_normalized_session_does_not_alias_mutable_input():
    default, pack, _, validate = api()
    state = default("series", "frame")
    record = pack(CprPath("a", "Artery", ((0, 0, 0), (5, 0, 0))), CprSettings())
    state.update(paths=[record], selected="a")
    result = validate(state)
    state["source"]["fingerprint"] = "changed"
    state["paths"][0]["name"] = "changed"
    assert result["source"]["fingerprint"] == ""
    assert result["paths"][0]["name"] == "Artery"
