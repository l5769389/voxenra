"""Optional external-environment checks; normal regression skips absent dependency."""
import json
import os
from pathlib import Path
import subprocess
import numpy as np
import pytest
from voxplane.core.nrrd_exchange import write_nrrd,read_nrrd

BRIDGE=Path(__file__).resolve().parents[1]/'src/voxplane/infrastructure/totalsegmentator_bridge.py'
PYTHON=Path(os.environ.get('VOXPLANE_TOTALSEG_PYTHON',str(Path.home()/'Applications/TotalSegmentator-Local/venv/bin/python')))

@pytest.mark.skipif(not PYTHON.is_file(),reason='Local TotalSegmentator Python is not installed')
@pytest.mark.parametrize('axes',[(2,1,0),(0,2,1)])
@pytest.mark.parametrize('reverse',[False,True])
def test_external_nifti_roundtrip_preserves_asymmetric_volume(tmp_path,axes,reverse):
    assert BRIDGE.is_file(), 'External bridge is not implemented'
    pixels=np.arange(5*7*9,dtype=np.float32).reshape(5,7,9)*.125-1024
    c,s=np.cos(.37),np.sin(.37)
    rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]])
    affine=np.eye(4);affine[:3,:3]=rotation[:,axes]*np.array([2.4,.7,.9])
    if reverse:affine[:3,0]*=-1
    affine[:3,3]=[-23,14,51]
    write_nrrd(tmp_path/'source.nrrd',pixels,affine)
    r=subprocess.run([str(PYTHON),str(BRIDGE),'roundtrip',str(tmp_path)],capture_output=True,text=True,timeout=60)
    assert r.returncode==0,r.stderr
    actual,matrix,_=read_nrrd(tmp_path/'roundtrip.nrrd')
    np.testing.assert_array_equal(actual,pixels)
    from voxplane.core.local_segmentation import same_grid
    assert same_grid(actual.shape,matrix,pixels.shape,affine)


@pytest.mark.skipif(not PYTHON.is_file(), reason='Local exchange Python is not installed')
def test_external_nifti_has_independent_ras_coordinates_and_asymmetric_markers(tmp_path):
    """Read the one-way NIfTI with nibabel, never through our NRRD importer."""
    pixels = np.zeros((5, 7, 9), np.float32)
    pixels[2, 3, 4] = 123
    pixels[0, 1, 8] = 47
    pixels[4, 6, 0] = -19
    # Input axes are (z,y,x), patient convention LPS.
    affine = np.array([[0, 0, .9, -23], [0, -.7, 0, 14],
                       [2.4, 0, 0, 51], [0, 0, 0, 1.]])
    write_nrrd(tmp_path / 'source.nrrd', pixels, affine)
    script = '''
import importlib.util, pathlib, sys
import nibabel as nib
import numpy as np
spec = importlib.util.spec_from_file_location('bridge', sys.argv[1])
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
root = pathlib.Path(sys.argv[2])
bridge.to_nifti(root)
image = nib.load(root / 'source.nii.gz')
assert image.shape == (9, 7, 5)
# NIfTI voxel axes are (x,y,z), world convention RAS. These literal
# expectations come from the declared source geometry, not the bridge.
np.testing.assert_allclose(image.affine,
    [[-.9, 0, 0, 23], [0, .7, 0, -14], [0, 0, 2.4, 51], [0, 0, 0, 1]], atol=1e-6)
data = image.get_fdata()
assert data[4, 3, 2] == 123
assert data[8, 1, 0] == 47
assert data[0, 6, 4] == -19
assert np.count_nonzero(data) == 3
np.testing.assert_allclose((image.affine @ [4, 3, 2, 1])[:3], [19.4, -11.9, 55.8], atol=1e-6)
'''
    run = subprocess.run([str(PYTHON), '-c', script, str(BRIDGE), str(tmp_path)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
