"""Build a metadata-free summary; raw DICOM and detailed artifacts remain local."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from qt_dicom_viewer import __version__
import subprocess


def report(root):
    cases=[]
    for category in ('synthetic','real','codecs'):
        folder=root/category
        comparison=folder/'comparison.json'
        comparisons={r['case']:r for r in json.loads(comparison.read_text())} if comparison.exists() else {}
        for p in sorted(folder.glob('*/voxenra-result.json')):
            r=json.loads(p.read_text());c=comparisons.get(p.parent.name,{})
            groups=r.get('volumes',r.get('groups',[]))
            groups=groups if isinstance(groups,list) else []
            item=dict(category=category,case=p.parent.name,product_status=r['status'],
                      product_groups=r['groups'] if isinstance(r.get('groups'),int) else len(groups),
                      slicer_status=c.get('status','blocked'),
                      geometry_max_error_mm=max((g.get('geometry_max_error_mm',0.) for g in groups),default=0.),
                      intensity_max_error=max((g.get('intensity_max_error',0.) for g in groups),default=0.),
                      slicer_roundtrip_groups=len(c.get('exchange',[])))
            if 'reason' in r:item['reason']=r['reason']
            item['volume_limits']=[dict(group=g['index'],reason=g['reason']) for g in groups if g.get('volume')=='unsupported']
            if category=='synthetic':
                item['planes_checked']=sum(len(g['planes']) for g in groups)
                item['mpr_max_error']=max((plane['max_error'] for g in groups for plane in g['planes']),default=0.)
                item['source_frames_checked']=r['source_frames_checked']
            else:
                item['source_frames_checked']=sum(g['frames'] for g in groups)
                item['stored_voxels_checked']=sum(g['stored_voxels_checked'] for g in groups)
            item['slicer_details']=[{k:v for k,v in d.items() if k in ('status','reason','geometry_scope','geometry_max_error_mm','intensity_max_error','stored_frame_values_equal','suv_slicer')} for d in c.get('comparisons',[])]
            # Never copy Slicer traceback paths or source metadata into repository reports.
            for detail in item['slicer_details']:
                if detail['status']=='blocked' and ('Traceback' in detail.get('reason','') or len(detail.get('reason',''))>300):
                    detail['reason']='Slicer DICOM plugin could not load this object; details retained locally'
            cases.append(item)
    tests=json.loads((root/'acceptance/results.json').read_text())
    full_path=root/'full-regression/results.json'
    full=json.loads(full_path.read_text()) if full_path.exists() else None
    if full is not None:
        initial_totals=full['totals']
        initial_failed=[r['file'] for r in full['files'] if r['exit_code']!=0]
        rows={r['file']:r for r in full['files']}
        affected_path=root/'final-affected/results.json'
        affected=json.loads(affected_path.read_text()) if affected_path.exists() else {'files':[]}
        rows.update({r['file']:r for r in affected['files']})
        totals={k:sum(r['counts'].get(k,0) for r in rows.values()) for k in initial_totals}
        full=dict(totals=totals,files_run=len(rows),
                  files_expected=len(list(Path('tests').rglob('test_*.py'))),
                  initial_totals=initial_totals,initial_unsuccessful=initial_failed,
                  final_affected_files=[r['file'] for r in affected['files']],
                  unsuccessful=[r['file'] for r in rows.values() if r['exit_code']!=0],
                  skipped_files=[r['file'] for r in rows.values() if r['counts'].get('skipped')])
        full['complete']=full['files_run']==full['files_expected']
    native_path=root/'native/acceptance-summary.json'
    native=json.loads(native_path.read_text()) if native_path.exists() else dict(
        status='blocked',reason='No native UI acceptance record available')
    changed=subprocess.check_output(['git','ls-files','-m','-o','--exclude-standard'],text=True).splitlines()
    hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in sorted(changed) if p.startswith(('src/','tests/')) and Path(p).is_file()}
    return dict(schema=1,created=datetime.now(timezone.utc).isoformat(),
        baseline=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        working_tree_sha256=hashes,
        software=dict(Voxenra=__version__,**{p:version(p) for p in ['numpy','pydicom','PySide6','vtk']}),slicer='5.12.4',
        tolerances=dict(geometry_mm=.001,intensity_atol=1e-4,intensity_rtol=1e-6,
                        interpolation_atol=1e-4,interpolation_rtol=5e-6,statistics_rtol=1e-5),
        cases=cases,counts=dict(product=dict(Counter(r['product_status'] for r in cases)),
                               slicer=dict(Counter(r['slicer_status'] for r in cases))),
        regression=tests['totals'],
        full_regression=full,
        fixed_findings=[dict(id='uncalibrated-measurement',status='fixed',
            reason='Missing or invalid grayscale PixelSpacing allowed the display fallback grid to become physical measurement calibration',
            tests='tests/test_spatial_missing_calibration.py',before='3 failed',after='4 passed')],
        native_ui=native,
        exclusions=['No claim of clinical validation','No Slicer SUV calculation comparison',
                    'No direct Slicer arbitrary-plane/slab pixel comparison',
                    'Native paired GUI coverage incomplete; coordinate interactions blocked by computer-use window lookup',
                    'Same-series classic CT interleaved phases are not split; 3D is rejected',
                    'No new format support, resampling, MTF/FWHM formula change, workspace schema change, or release'])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report(args.root),indent=2,ensure_ascii=False)+'\n')
