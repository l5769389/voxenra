"""Opt-in original-file audit: python -m spatial_audit.real manifest.json output.
Manifest is a local JSON list of {name, paths, provenance?, expected_groups?}.
No sample discovery, download, or patient metadata is committed by this adapter.
"""
import hashlib
import json
from pathlib import Path
import sys
import traceback
import numpy as np
import pydicom
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.pixel_codecs import decode_pixels
from .verify import close
from .pet_reference import suvbw_factor


def element(ds,frame,sequence,keyword,default=None):
    if frame is not None:
        for group in [ds.PerFrameFunctionalGroupsSequence[frame],*getattr(ds,'SharedFunctionalGroupsSequence',[])]:
            if sequence in group and keyword in getattr(group,sequence)[0]:
                return getattr(getattr(group,sequence)[0],keyword)
    return getattr(ds,keyword,default)


def reference(ds,frame,raw):
    slope=float(element(ds,frame,'PixelValueTransformationSequence','RescaleSlope',1))
    intercept=float(element(ds,frame,'PixelValueTransformationSequence','RescaleIntercept',0))
    values=raw.astype(float)*slope+intercept
    if 'PixelPaddingValue' in ds:
        a=float(ds.PixelPaddingValue);b=float(getattr(ds,'PixelPaddingRangeLimit',a))
        values[(raw>=min(a,b))&(raw<=max(a,b))]=np.nan
    pos=element(ds,frame,'PlanePositionSequence','ImagePositionPatient')
    ori=element(ds,frame,'PlaneOrientationSequence','ImageOrientationPatient')
    spacing=element(ds,frame,'PixelMeasuresSequence','PixelSpacing')
    return values,pos,ori,spacing


def verify(config,root):
    root.mkdir(parents=True,exist_ok=True)
    paths=[Path(p) for p in config['paths']]
    manifest=dict(schema=1,real=True,case={'name':config['name']},
        provenance=config.get('provenance','User-local original; not redistributed'),
        files=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])
    (root/'case.json').write_text(json.dumps(manifest,indent=2))
    scanned=list(DicomFolderScanner().scan_files(paths,folder=paths[0].parent))[-1]
    if 'expected_groups' in config: assert len(scanned.series)==config['expected_groups']
    result=dict(case=config['name'],groups=[],status='pass',files=len(paths))
    loader=DicomLoader();cache={};seen=set()
    for n,series in enumerate(scanned.series):
        data=[];positions=[];maximum=0.;gerror=0.;stored_checked=0;unit=None
        for instance in series.instances:
            key=(str(instance.path),instance.frame_index)
            assert key not in seen;seen.add(key)
            if instance.path not in cache:
                ds=pydicom.dcmread(instance.path,force=True);cache[instance.path]=(ds,ds.pixel_array)
            ds,raws=cache[instance.path];f=instance.frame_index;raw=raws if f is None else raws[f]
            np.testing.assert_array_equal(decode_pixels(ds,index=f),raw)
            stored_checked+=raw.size
            expected,pos,ori,spacing=reference(ds,f,raw)
            meta,pixels=loader.read_frame(instance.path,f)
            maximum=max(maximum,close(pixels,expected))
            display=loader.load_dataset(meta,None,False,modality_pixels=pixels)
            unit=display.pixel_value_meta.unit
            data.append(expected);positions.append((pos,ori,spacing))
        entry=dict(index=n,frames=len(data),stored_voxels_checked=stored_checked,
            intensity_max_error=maximum,unit=unit)
        try:volume=VolumeManager().get_or_build(series)
        except (ValueError,RuntimeError) as error:
            entry.update(volume='unsupported',reason=str(error))
            # Keep decoded frames for Slicer comparison even without a regular volume.
            dest=root/f'group-{n}';dest.mkdir(exist_ok=True)
            extra={}
            if len(data)==1 and all(x is not None for x in positions[0]):
                pos,ori,spacing=positions[0];u,v=np.array(ori,float).reshape(2,3)
                matrix=np.eye(4);matrix[:3,:3]=np.column_stack([np.cross(u,v),v*float(spacing[0]),u*float(spacing[1])]);matrix[:3,3]=pos
                extra=dict(plane_affine=matrix)
            np.savez_compressed(dest/'voxenra.npz',pixels=np.stack(data),source_pixels=np.stack(data),**extra)
        else:
            expected=np.stack(data)
            # PET display may be SUVbw; compare original BQML through source_pixels.
            source=volume.source_pixels if volume.source_pixels is not None else volume.modality_pixels
            close(source,expected)
            if series.modality=='PT' and volume.pixel_value_meta.unit=='SUVbw':
                factor=suvbw_factor(cache[series.instances[0].path][0])
                entry['suvbw_factor']=factor
                entry['suvbw_max_error']=close(volume.modality_pixels,expected*factor)
                entry['suvbw_slicer']='not_verified: scalar DICOM importer retains source activity'
            for z,(pos,ori,spacing) in enumerate(positions):
                u,v=np.asarray(ori,float).reshape(2,3);p=np.asarray(pos,float)
                for y,x in [(0,0),(expected.shape[1]-1,expected.shape[2]-1),(expected.shape[1]//3,expected.shape[2]//3)]:
                    actual=(volume.geometry.voxel_to_patient@[z,y,x,1])[:3]
                    truth=p+u*x*float(spacing[1])+v*y*float(spacing[0])
                    gerror=max(gerror,close(actual,truth,atol=.001,rtol=0))
            entry.update(volume='pass',geometry_max_error_mm=gerror)
            dest=root/f'group-{n}';dest.mkdir(exist_ok=True)
            np.savez_compressed(dest/'voxenra.npz',pixels=volume.modality_pixels,source_pixels=expected,
                affine=volume.geometry.voxel_to_patient)
        (dest/'sources.json').write_text(json.dumps([dict(path=str(i.path),frame=i.frame_index) for i in series.instances]))
        result['groups'].append(entry)
    (root/'voxenra-result.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    configs=json.loads(Path(sys.argv[1]).read_text());root=Path(sys.argv[2]);root.mkdir(parents=True,exist_ok=True)
    results=[]
    for config in configs:
        try: result=verify(config,root/config['name'])
        except Exception:
            result=dict(case=config['name'],status='failure',reason=traceback.format_exc())
            dest=root/config['name'];dest.mkdir(parents=True,exist_ok=True)
            # A failed rerun must replace an older successful per-case report.
            (dest/'voxenra-result.json').write_text(json.dumps(result,indent=2))
        results.append(result);print(config['name'],result['status'],flush=True)
        (root/'voxenra-summary.json').write_text(json.dumps(results,indent=2))
    return int(any(r['status']=='failure' for r in results))

if __name__=='__main__':raise SystemExit(main())
