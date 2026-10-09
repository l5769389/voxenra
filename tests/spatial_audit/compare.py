"""Compare Slicer artifacts without equating different grids or frame groups.
Usage: PYTHONPATH=src:tests python -m spatial_audit.compare CASE_ROOT
"""
import json
from pathlib import Path
import sys
import numpy as np
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.nrrd_exchange import read_segmentation
from .verify import close


def geometry(v):
    return v['affine'] if 'affine' in v else v['plane_affine']

def same_grid(v,s):
    if v['source_pixels'].shape!=s['pixels'].shape:return False
    if 'affine' in v:return np.allclose(v['affine'],s['affine'],atol=.001,rtol=0)
    return 'plane_affine' in v and np.allclose(v['plane_affine'][:,1:],s['affine'][:,1:],atol=.001,rtol=0)

def compare(root):
    root=Path(root);results=[]
    for manifest_path in sorted(root.glob('*/case.json')):
        case=manifest_path.parent;manifest=json.loads(manifest_path.read_text())
        result=dict(case=case.name,comparisons=[],exchange=[])
        source=case/'slicer-result.json'
        if not source.exists():
            result.update(status='blocked',reason='Slicer result missing');results.append(result);continue
        slicer=json.loads(source.read_text());result['slicer_version']=slicer['slicer']
        if not manifest.get('expected_volume',True):
            result.update(status='explicitly_unsupported',reason='Voxenra rejects irregular or incomplete geometry',
                slicer_corrections=[dict(warning=x.get('warning'),transform=x.get('transform'),shape=x.get('shape')) for x in slicer['dicom']])
            results.append(result);continue
        vox_files=sorted(case.glob('group-*/voxenra.npz'))
        candidates=[(p,np.load(p)) for p in vox_files]
        for n,loaded in enumerate(slicer['dicom']):
            item=dict(slicer_volume=n)
            if loaded['status']!='loaded':
                item.update(status='blocked',reason=loaded.get('reason','Slicer load failed'))
            elif loaded['transform']:
                item.update(status='definition_difference',reason='Slicer added geometry transform; no direct grid comparison')
            else:
                s=np.load(case/f'slicer-dicom-{n}.npz')
                matched=[(p,v) for p,v in candidates if same_grid(v,s)]
                if len(matched)!=1:
                    item.update(status='definition_difference',reason='Different frame grouping or physical grid',
                                slicer_shape=list(s['pixels'].shape),voxenra_shapes=[list(v['pixels'].shape) for p,v in candidates])
                    if len(candidates)==1 and 'affine' not in candidates[0][1] and 'plane_affine' not in candidates[0][1]:
                        v=candidates[0][1]
                        item.update(status='blocked',reason='Original DICOM has no patient plane geometry',
                            stored_frame_values_equal=bool(np.array_equal(v['pixels'],s['pixels'])))
                else:
                    p,v=matched[0];expected=v['source_pixels'];actual=s['pixels'];valid=np.isfinite(expected)
                    same=np.allclose(expected[valid],actual[valid],atol=1e-4,rtol=1e-6)
                    item.update(status='pass' if same else 'definition_difference',group=p.parent.name,
                        geometry_max_error_mm=float(np.max(abs((geometry(v)-s['affine'])[:,1:] if 'plane_affine' in v else geometry(v)-s['affine']))),
                        geometry_scope='single_plane' if 'plane_affine' in v else 'volume',
                        intensity_max_error=float(np.max(abs(expected[valid]-actual[valid]))),
                        valid_voxels=int(valid.sum()),padding_voxels=int((~valid).sum()),
                        padding_policy='Excluded explicitly: Voxenra NaN; Slicer retains numeric padding')
                    if not same:
                        item['reason']='Slicer intensity differs from independently checked DICOM rescale values'
                        if case.name=='mr-mono1':item['reason']='GDCM complements MONOCHROME1 stored pixels before rescale; Voxenra only inverts display'
                        if case.name=='enhanced-ct-rle':item['reason']='Slicer GDCM uses first-frame slope for all frames; Voxenra applies per-frame slope'
                    if case.name.startswith('pet-') or case.name=='petct-2':
                        item['suv_slicer']='not_verified: scalar DICOM plugin provides source values only'
            result['comparisons'].append(item)
        # Slicer rewrites the segmentation. Reload through the product importer.
        for group in sorted(case.glob('group-*')):
            path=group/'slicer-return.seg.nrrd'
            if not path.exists():continue
            paths=[case/f['path'] for f in manifest['files']]
            scan=list(DicomFolderScanner().scan_files(paths,folder=case))[-1]
            sources=json.loads((group/'sources.json').read_text())
            identities={(Path(s['path']).name,s['frame']) for s in sources}
            matches=[(s,None) for s in scan.series if {(i.path.name,i.frame_index) for i in s.instances}==identities]
            if not matches:
                matches=[(s,p.phase_identifier) for s in scan.series for p in s.phases if {(i.path.name,i.frame_index) for i in p.instances}==identities]
            series,phase=matches[0]
            volume=VolumeManager().get_or_build(series,phase);records,evaluations=read_segmentation(path,volume)
            masks=np.load(group/'masks.npz')
            assert len(records)==len(masks.files)
            for i,record in enumerate(records):
                dense=np.zeros(volume.modality_pixels.shape,bool)
                dense[tuple(slice(int(a),int(a)+n) for a,n in zip(record['mask_offset'],record['mask'].shape))]=record['mask']
                np.testing.assert_array_equal(dense,masks[f'mask{i}'])
            result['exchange'].append(dict(group=group.name,status='pass',masks=len(records)))
        if slicer.get('exchange_error'):result['exchange_error']=slicer['exchange_error']
        states={x['status'] for x in result['comparisons']}
        result['status']='pass' if states=={'pass'} else 'definition_difference' if 'definition_difference' in states else 'blocked'
        results.append(result)
    (root/'comparison.json').write_text(json.dumps(results,indent=2))
    for result in results:print(result['case'],result['status'],len(result['exchange']))
    return results

if __name__=='__main__':compare(sys.argv[1])
