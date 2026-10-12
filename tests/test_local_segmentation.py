from dataclasses import replace
import json
import numpy as np
import pytest
from test_mpr_reslicer import _volume
from qt_dicom_viewer.model import PixelValueMeta
from qt_dicom_viewer.core.nrrd_exchange import write_nrrd


def ct():
    return replace(_volume(np.arange(8*9*10).reshape(8,9,10), origin=(-20,12,31),
        slice_spacing=2.5,row_spacing=.7,column_spacing=.8), pixel_value_meta=PixelValueMeta(unit='HU'))


def api():
    from qt_dicom_viewer.core import local_segmentation
    return local_segmentation


def test_ct_input_rejects_non_hu_shear_and_nonfinite():
    v=ct(); api().validate_input(v,'CT')
    for bad,modality in [(v,'MR'),(replace(v,pixel_value_meta=PixelValueMeta()),'CT'),
        (replace(v,geometry=replace(v.geometry,slice_index_direction_patient=(.1,0,1))),'CT'),
        (replace(v,modality_pixels=np.full(v.modality_pixels.shape,np.nan)),'CT')]:
        with pytest.raises(ValueError): api().validate_input(bad,modality)


def output(root,v,shift=0):
    mask=np.zeros(v.modality_pixels.shape,np.uint8); mask[1:4,2:5,3:7]=1
    affine=v.geometry.voxel_to_patient.copy();affine[0,3]+=shift
    write_nrrd(root/'liver.nrrd',mask,affine)
    write_nrrd(root/'spleen.nrrd',np.zeros_like(mask),affine)
    manifest={'protocol':1,'version':'2.18.0','model':'total-fast-297','device':'cpu',
        'completed_at':'2026-10-10T00:00:00Z','outputs':{'liver':'liver.nrrd','spleen':'spleen.nrrd'}}
    (root/'result.json').write_text(json.dumps(manifest))
    return mask


def test_complete_result_is_cropped_and_empty_organs_reported(tmp_path):
    v=ct();mask=output(tmp_path,v)
    records,ev,empty=api().read_results(tmp_path,v,['liver','spleen'],phase='phase1')
    assert empty==['spleen'] and len(records)==1
    r=records[0]
    assert r['phase']=='phase1' and r['mask'].shape==(3,3,4)
    assert ev[r['id']].metrics['count']==int(mask.sum())
    assert r['automatic_segmentation']['version']=='2.18.0'
    from qt_dicom_viewer.core.workspace_state import dumps,loads
    restored=loads(dumps({'voi':records}))['voi'][0]
    assert restored['automatic_segmentation']==r['automatic_segmentation']
    np.testing.assert_array_equal(restored['mask'],r['mask'])


def test_wrong_grid_partial_and_nonbinary_results_rejected(tmp_path):
    v=ct();output(tmp_path,v,.01)
    with pytest.raises(ValueError): api().read_results(tmp_path,v,['liver','spleen'])
    output(tmp_path,v);(tmp_path/'spleen.nrrd').unlink()
    with pytest.raises((ValueError,OSError)):api().read_results(tmp_path,v,['liver','spleen'])
    output(tmp_path,v)
    write_nrrd(tmp_path/'liver.nrrd',np.full(v.modality_pixels.shape,2,np.uint8),v.geometry.voxel_to_patient)
    with pytest.raises(ValueError):api().read_results(tmp_path,v,['liver','spleen'])
