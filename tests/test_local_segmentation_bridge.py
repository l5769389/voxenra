"""Optional external-environment checks; normal regression skips absent dependency."""
import json
import os
from pathlib import Path
import subprocess
import numpy as np
import pytest
from qt_dicom_viewer.core.nrrd_exchange import write_nrrd,read_nrrd

BRIDGE=Path(__file__).resolve().parents[1]/'src/qt_dicom_viewer/infrastructure/totalsegmentator_bridge.py'
PYTHON=Path(os.environ.get('VOXENRA_TOTALSEG_PYTHON',str(Path.home()/'Applications/TotalSegmentator-Local/venv/bin/python')))

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
    from qt_dicom_viewer.core.local_segmentation import same_grid
    assert same_grid(actual.shape,matrix,pixels.shape,affine)
