"""Standalone external-Python bridge. Never imports Voxenra or runs on its GUI thread."""
import datetime
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import sys

MODEL = 'Dataset297_TotalSegmentator_total_3mm_1559subj'
TRAINER = 'nnUNetTrainer_4000epochs_NoMirroring__nnUNetPlans__3d_fullres'


def event(kind, **values):
    print('VOXENRA_EVENT ' + json.dumps(dict(event=kind, **values)), flush=True)


def configure(root, weights):
    home = root / 'runtime'
    home.mkdir(exist_ok=True)
    (home / 'config.json').write_text(json.dumps(dict(totalseg_id='voxenra_local',
        send_usage_stats=False, prediction_counter=0, statistics_disclaimer_shown=True)))
    os.environ.update(TOTALSEG_HOME_DIR=str(home), TOTALSEG_WEIGHTS_PATH=str(weights),
        MPLCONFIGDIR=str(home / 'matplotlib'), PYTORCH_ENABLE_MPS_FALLBACK='1')


def model_status(weights):
    folder = weights / MODEL / TRAINER
    issues = []
    for name in ('plans.json', 'dataset.json', 'fold_0/checkpoint_final.pth'):
        path = folder / name
        try:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError('missing or empty')
            if name.endswith('.json'):
                if path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('configuration too large')
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or not data:
                    raise ValueError('invalid model configuration')
        except (OSError, ValueError, UnicodeError) as error:
            issues.append(f'{name}: {error}')
    return dict(ready=not issues, issues=issues)


def capabilities(weights):
    import torch
    import SimpleITK  # Required for geometry-preserving exchange.
    import nibabel
    from totalsegmentator.python_api import totalsegmentator, get_task_config
    from totalsegmentator.map_to_binary import class_map
    parameters = inspect.signature(totalsegmentator).parameters
    if not {'task','fast','robust_crop','roi_subset','device','nr_thr_resamp','nr_thr_saving'} <= set(parameters):
        raise RuntimeError('Unsupported TotalSegmentator API')
    config=get_task_config('total', fast=True, quiet=True)
    if not isinstance(config,dict) or config.get('task_id') != 297:
        raise RuntimeError('Unsupported CT fast model')
    model=model_status(weights)
    devices=[]
    if torch.cuda.is_available(): devices.append('gpu')
    if torch.backends.mps.is_available(): devices.append('mps')
    devices.append('cpu')
    return dict(protocol=1, version=importlib.metadata.version('TotalSegmentator'),
        devices=devices, organs=list(class_map['total'].values()), model_ready=model['ready'], model_issues=model['issues'])


def to_nifti(root):
    import SimpleITK as sitk
    source = sitk.ReadImage(str(root / 'source.nrrd'))
    sitk.WriteImage(source, str(root / 'source.nii.gz'))
    return source


def main():
    mode, root_text = sys.argv[1:3]
    root=Path(root_text)
    if mode == 'roundtrip':
        import SimpleITK as sitk
        to_nifti(root)
        sitk.WriteImage(sitk.ReadImage(str(root/'source.nii.gz')), str(root/'roundtrip.nrrd'))
        return
    request=json.loads((root / 'request.json').read_text(encoding='utf-8'))
    weights=Path(request['weights'])
    configure(root,weights)
    info=capabilities(weights)
    if mode == 'probe':
        if info['model_issues']:event('model', issues=info['model_issues'])
        (root / 'result.json').write_text(json.dumps(info), encoding='utf-8')
        return
    if not info['model_ready']:
        raise RuntimeError('CT fast model is missing or incomplete')
    organs=request['organs']
    if not organs or len(organs)!=len(set(organs)) or not set(organs) <= set(info['organs']):
        raise RuntimeError('Invalid organ selection')
    device=info['devices'][0] if request['device']=='auto' else request['device']
    if device not in info['devices']:
        raise RuntimeError('Requested compute device is unavailable')
    # These tasks need only preflight-checked weights. Forbid accidental downloads
    # and telemetry from this worker, without modifying the user's environment.
    import requests
    def offline(*args, **kwargs):
        raise RuntimeError('Network access is disabled for local segmentation')
    requests.sessions.Session.request=offline
    from totalsegmentator.python_api import totalsegmentator
    import SimpleITK as sitk
    source=to_nifti(root)
    event('stage', stage='running')
    totalsegmentator(root/'source.nii.gz',root/'masks',task='total',fast=True,
        robust_crop=True,roi_subset=organs,device=device,nr_thr_resamp=2,nr_thr_saving=1)
    event('stage',stage='validating')
    outputs={}
    for organ in organs:
        image=sitk.ReadImage(str(root/'masks'/f'{organ}.nii.gz'))
        # Preserve returned geometry: never copy the source header to hide errors.
        filename=organ+'.nrrd'
        sitk.WriteImage(image,str(root/filename),True)
        outputs[organ]=filename
    result=dict(protocol=1,version=info['version'],device=device,model='total-fast-297',
        completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),outputs=outputs)
    (root/'result.json').write_text(json.dumps(result),encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        event('error', reason=str(error))
        sys.exit(1)
