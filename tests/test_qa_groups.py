from dataclasses import replace
import numpy as np
import pytest
from voxplane.core.water_qa import analyze_water_phantom, measure_qa_rois, resize_qa_rois
from voxplane.model.water_qa import WaterQaRoi
from test_water_qa import water_image


def test_noise_has_independent_sampling_and_normalization():
    p = water_image()
    r = analyze_water_phantom(p, (1, 1))
    regions = {roi.key: roi for roi in r.rois}
    small, noise = regions['center'], regions['noise']
    assert small.radius_mm == pytest.approx(r.phantom.radius_mm*.1)
    assert noise.radius_mm == pytest.approx(r.phantom.radius_mm*.4)
    y, x = np.indices(p.shape)
    expected = p[(x-noise.column)**2+(y-noise.row)**2 <= noise.radius_mm**2].astype(float)
    assert r.noise_hu == pytest.approx(expected.std())
    assert r.noise_percent == pytest.approx(expected.std()/10)
    settings = replace(r.settings, noise_diameter_mm=100)
    edited = measure_qa_rois(p, (1,1), r.phantom, settings, resize_qa_rois(r, settings, (1,1)))
    assert edited.rois[:5] == r.rois[:5]
    assert edited.water_ct_hu == r.water_ct_hu
    assert edited.uniformity_hu == r.uniformity_hu
    without_center = measure_qa_rois(p, (1,1), r.phantom, settings, tuple(i for i in edited.rois if i.key != 'center'))
    assert without_center.water_ct_hu is None
    assert without_center.noise_hu == edited.noise_hu


def test_air_independent_of_water_and_padding_is_not_air():
    p = water_image()
    p[:10,:] = np.nan
    r = analyze_water_phantom(p, (1,1))
    air = WaterQaRoi('air-1','Air 1',30,30,10,0,0,0,0,0,0,None,group='air')
    added = measure_qa_rois(p, (1,1), r.phantom, r.settings, r.rois+(air,))
    assert added.rois[-1].mean_hu == -1000
    assert added.rois[-1].delta_center_hu is None
    assert added.noise_hu == r.noise_hu and added.uniformity_hu == r.uniformity_hu
    with pytest.raises(ValueError):
        measure_qa_rois(p, (1,1), r.phantom, r.settings, (replace(air,row=12),))
    with pytest.raises(ValueError):
        measure_qa_rois(p, (1,1), r.phantom, r.settings, (replace(air,column=204,row=149),))
    independent = measure_qa_rois(p, (1,1), None, r.settings, (air,))
    assert independent.rois[0].mean_hu == -1000 and independent.water_ct_hu is None

from test_water_qa_controller import qa_view, wait_qa
from test_measurement_qml import qt_app


def test_groups_preserve_results_and_only_active_group_is_editable(qa_view, qt_app):
    qa = qa_view[0].qaController
    qa.activate(); wait_qa(qt_app, qa)
    original = qa.currentResult
    assert len(qa.roiItems) == 5
    qa.setActiveGroup('noise')
    assert [r['key'] for r in qa.roiItems] == ['noise']
    assert not qa.deleteRoi('center')
    qa.setActiveDiameterMm(90); wait_qa(qt_app, qa)
    assert qa.currentResult['rois'][:5] == original['rois'][:5]
    assert qa.currentResult['noise_hu'] != original['noise_hu']
    qa.setActiveGroup('uniformity')
    assert qa.activeDiameterMm == original['settings']['roi_diameter_mm']
    assert qa.currentResult['rois'][:5] == original['rois'][:5]
    qa.setActiveGroup('air'); wait_qa(qt_app, qa); qa.placeAirRoi()
    assert qa.begin_drag(30,30)
    assert not qa.placingAir and not qa.dragging
    assert qa.roiItems[0]['meanHu'] == -1000
    assert qa.currentResult['water_ct_hu'] == original['water_ct_hu']
    qa.setActiveGroup('noise')
    before = qa.currentResult
    qa.regenerateRois(); wait_qa(qt_app, qa)
    assert [r for r in qa.currentResult['rois'] if r['group'] != 'noise'] == [r for r in before['rois'] if r['group'] != 'noise']
    from voxplane.core.workspace_state import encode, decode
    saved = qa.currentResult
    # Older saved reference-display preferences must not expose other groups.
    qa.restore_state(decode(encode({**qa.persistent_state(), 'showOtherGroups': True})))
    assert len(qa.roiItems) == 1
    assert qa.activeGroup == 'noise' and qa.currentResult == saved


def test_legacy_noise_is_not_relabelled_as_large_roi_before_recalculation(qa_view, qt_app):
    from voxplane.core.workspace_state import encode, decode
    qa = qa_view[0].qaController
    qa.activate(); wait_qa(qt_app,qa)
    old = qa._result
    center = next(r for r in old.rois if r.key == 'center')
    qa._result = replace(old, rois=tuple(r for r in old.rois if r.group != 'noise'),
                         protocol_version=1,noise_hu=center.std_hu,noise_percent=None,
                         settings=replace(old.settings,noise_diameter_mm=None))
    qa._settings = qa._result.settings
    qa._remember_result()
    # Exercise the on-disk 2.5 schema, not a legacy-shaped current dataclass.
    saved = encode(qa.persistent_state())
    def legacy_fields(value):
        if isinstance(value, dict):
            removed = {"WaterQaSettings": ("noise_diameter_mm", "air_diameter_mm"),
                       "WaterQaRoi": ("group",),
                       "WaterQaResult": ("noise_percent", "protocol_version")}
            for field in removed.get(value.get("$type"), ()):
                value["fields"].pop(field)
            for child in value.values():
                legacy_fields(child)
        elif isinstance(value, list):
            for child in value:
                legacy_fields(child)
    legacy_fields(saved)
    qa.reset()
    qa.restore_state(decode(saved))
    assert qa._result.protocol_version == 1
    assert qa._result.noise_hu == center.std_hu
    assert all(roi.group == 'uniformity' for roi in qa._result.rois)
    qa.setActiveGroup('noise')
    assert '旧版' in qa.notice and not qa.roiItems
    qa.setActiveGroup('uniformity')
    qa.deleteRoi('left')
    assert qa._result.protocol_version == 1 and qa._result.noise_hu == center.std_hu
    qa.analyze(); wait_qa(qt_app,qa)
    assert qa._result.protocol_version == 2
    assert 'noise' in [r.key for r in qa._result.rois]
    assert 'left' not in [r.key for r in qa._result.rois]
