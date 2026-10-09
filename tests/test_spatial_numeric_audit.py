"""Full-file analytic phantoms through the public scan/decode/build pipeline."""
import pytest
from spatial_audit.cases import CASES, generate
from spatial_audit.verify import verify_case

@pytest.mark.parametrize('case', CASES, ids=lambda c:c.name)
def test_spatial_numeric_phantom(tmp_path,case):
    generate(tmp_path,case)
    result=verify_case(tmp_path)
    assert result['status'] in ('pass','expected_unsupported')

@pytest.mark.parametrize('name',['ct-axial','ct-oblique','enhanced-ct-phases'])
def test_original_dicom_workspace_survives_process_restart(tmp_path,name):
    import os
    import subprocess
    import sys
    from pathlib import Path
    case=next(c for c in CASES if c.name==name)
    generate(tmp_path,case)
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONPATH=os.pathsep.join([str(root/'src'),str(root/'tests')]))
    for mode in ('write','read'):
        run=subprocess.run([sys.executable,'-m','spatial_audit.restart',mode,str(tmp_path)],env=env,
                           capture_output=True,text=True,timeout=45)
        assert run.returncode==0,run.stdout+run.stderr
