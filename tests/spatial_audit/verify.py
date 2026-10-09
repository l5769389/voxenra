"""Product adapter. Expected values come only from serialized independent truth."""
import json
import math
from pathlib import Path
import warnings

import numpy as np
import pydicom
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.pixel_codecs import decode_pixels
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.core.measurement_geometry import angle_degrees, roi_metrics
from qt_dicom_viewer.core.geometry_2d import image_point_distance_mm
from qt_dicom_viewer.core.segmentation_masks import mask_record
from qt_dicom_viewer.core.nrrd_exchange import write_nrrd, read_nrrd, write_segmentation, read_segmentation
from qt_dicom_viewer.core import workspace_state
from qt_dicom_viewer.model import ImagePoint, MeasurementKind, MprPlane, MprProjectionMode, WindowLevel
from .cases import sample_reference, directions
from qt_dicom_viewer.model.dicom_core import MprFrame


def close(actual, expected, *, rtol=1e-6, atol=1e-4):
    np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True)
    a,b=np.asarray(actual),np.asarray(expected)
    valid=np.isfinite(a)&np.isfinite(b)
    return float(np.max(np.abs(a[valid]-b[valid]))) if valid.any() else 0.


def check_measurements(pixels, spacing):
    sr,sc=spacing
    points=[ImagePoint(.5,1.5),ImagePoint(10.5,9.5)]
    expected_length=math.hypot(10*sc,8*sr)
    length=image_point_distance_mm(*points,row_spacing=sr,column_spacing=sc)
    close(length,expected_length)
    angle=angle_degrees([ImagePoint(1,0),ImagePoint(0,0),ImagePoint(1,1)],row_spacing=sr,column_spacing=sc)
    close(angle,math.degrees(math.atan2(sr,sc)))
    output={'length_mm':length,'angle_deg':angle}
    # Include a clipped ROI, continuous ellipse and straight-edged free shape.
    for kind in (MeasurementKind.RECT,MeasurementKind.ELLIPSE,MeasurementKind.FREEHAND):
        x0,y0,x1,y1=-2.5,1.5,10.5,9.5
        poly=[ImagePoint(x0,y0),ImagePoint(x1,y0),ImagePoint(x1,y1),ImagePoint(x0,y1)]
        roi=poly if kind==MeasurementKind.FREEHAND else [poly[0],poly[2]]
        m=roi_metrics(roi,kind,pixels,row_spacing=sr,column_spacing=sc)
        selected=[]
        for y in range(pixels.shape[0]):
            for x in range(pixels.shape[1]):
                inside=x0<=x<=x1 and y0<=y<=y1
                if kind==MeasurementKind.ELLIPSE:
                    inside=((x-4)/6.5)**2+((y-5.5)/4)**2<=1
                if inside and np.isfinite(pixels[y,x]): selected.append(float(pixels[y,x]))
        close(m.area_mm2,13*8*sr*sc*(math.pi/4 if kind==MeasurementKind.ELLIPSE else 1))
        assert m.pixel_count==len(selected)
        close([m.mean,m.std,m.minimum,m.maximum],
              [np.mean(selected),np.std(selected),min(selected),max(selected)])
        output[kind.value]={'count':m.pixel_count,'area_mm2':m.area_mm2,'mean':m.mean}
    return output


def check_planes(volume, pixels, affine, dest):
    rng=np.random.default_rng(2819); out=[]; samples={}
    rotation=directions('oblique')
    frame=MprFrame(tuple(np.asarray(volume.geometry.center_patient)+[.13,.21,-.4]),
        *[tuple(rotation[:,i]) for i in range(3)])
    for plane in MprPlane:
        for roll,chosen_frame in ((0.,None),(.31,None),(.17,frame)):
            sliced=MprReslicer().reslice(volume,plane,frame=chosen_frame,view_roll_radians=roll)
            g=sliced.geometry
            # Explicit radiological display axes in LPS, independent of the resolver.
            bases={MprPlane.AXIAL:([0,0,1],[0,1,0],[1,0,0]),
                   MprPlane.CORONAL:([0,1,0],[0,0,-1],[1,0,0]),
                   MprPlane.SAGITTAL:([1,0,0],[0,0,-1],[0,1,0])}
            normal,row,col=map(lambda v:np.array(v,float),bases[plane])
            row=row*np.cos(roll)+np.cross(normal,row)*np.sin(roll)
            col=col*np.cos(roll)+np.cross(normal,col)*np.sin(roll)
            expected=np.column_stack([normal,row,col])
            if chosen_frame is not None:expected=rotation@expected
            actual=g.image_index_to_patient[:3,:3]
            close(actual/np.linalg.norm(actual,axis=0),expected,atol=1e-8,rtol=0)
            ij=np.column_stack([rng.integers(0,g.rows,65),rng.integers(0,g.columns,65)])
            ij=np.vstack([ij,[[0,0],[g.rows-1,g.columns-1],[g.rows//2,g.columns//2]]])
            patient=(g.image_index_to_patient@np.column_stack([np.zeros(len(ij)),ij,np.ones(len(ij))]).T).T[:,:3]
            indices=(np.linalg.inv(affine)@np.column_stack([patient,np.ones(len(patient))]).T).T[:,:3]
            expected=sample_reference(pixels,indices)
            actual=sliced.modality_pixels[ij[:,0],ij[:,1]]
            error=close(actual,expected,rtol=5e-6)
            key=f'{plane.value}_{roll}'
            samples[key+'_points']=patient; samples[key+'_values']=actual
            out.append(dict(plane=plane.value,roll=roll,oblique_frame=chosen_frame is not None,max_error=error,
                valid=int(np.isfinite(actual).sum()),invalid=int((~np.isfinite(actual)).sum()),
                boundary=int(np.any((np.abs(indices)<1e-6)|(np.abs(indices-(np.array(pixels.shape)-1))<1e-6),axis=1).sum())))
            # Slab follows declared discrete sampling, not continuous integration.
            thickness=4.2; half_count=max(1,math.ceil(thickness/2/g.navigation_spacing))
            offsets=np.linspace(-thickness/2,thickness/2,2*half_count+1)
            normal=g.image_index_to_patient[:3,0]/g.navigation_spacing
            stack=[]
            for offset in offsets:
                xyz=patient+normal*offset
                coords=(np.linalg.inv(affine)@np.column_stack([xyz,np.ones(len(xyz))]).T).T[:,:3]
                stack.append(sample_reference(pixels,coords))
            stack=np.array(stack); valid=np.isfinite(stack).any(axis=0)
            for mode,reduce in [(MprProjectionMode.MIP,np.nanmax),(MprProjectionMode.MIN_IP,np.nanmin),
                                (MprProjectionMode.MEAN,np.nanmean),(MprProjectionMode.SUM,np.nansum)]:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',RuntimeWarning); reference=reduce(stack,axis=0)
                reference[~valid]=np.nan
                proj=MprReslicer().reslice(volume,plane,frame=chosen_frame,view_roll_radians=roll,
                    projection_mode=mode,slab_thickness_mm=thickness)
                close(proj.modality_pixels[ij[:,0],ij[:,1]],reference,rtol=5e-6)
    np.savez_compressed(dest/'plane-samples.npz',**samples)
    return out


def check_exchange(volume, dest):
    shape=volume.modality_pixels.shape
    masks=[];records=[];evaluations={}; counts=[]
    for n in range(3):
        m=np.zeros(shape,bool)
        if n<2: m[1+n:6+n,2:11,3:13]=True
        record,evaluation=mask_record(volume,m,(0,0,0),name=['Region A','Overlap','Empty'][n],
            color=['#ed55ed','#43c6dc','#ffbb55'][n],allow_empty=True)
        count=int(m.sum()); counts.append(count)
        expected_volume=count*abs(np.linalg.det(volume.geometry.voxel_to_patient[:3,:3]))/1000
        close(evaluation.metrics['volume'],expected_volume,rtol=1e-5)
        values=volume.modality_pixels[m & np.isfinite(volume.modality_pixels)].astype(float)
        if count:
            close([evaluation.metrics[k] for k in ('mean','sd','minimum','maximum')],
                  [values.mean(),values.std(),values.min(),values.max()],rtol=1e-5)
        masks.append(m);records.append(record);evaluations[record['id']]=evaluation
    write_nrrd(dest/'source.nrrd',volume.modality_pixels,volume.geometry.voxel_to_patient)
    p,a,_=read_nrrd(dest/'source.nrrd'); close(p,volume.modality_pixels,rtol=0,atol=0); close(a,volume.geometry.voxel_to_patient)
    write_segmentation(dest/'segmentation.seg.nrrd',volume,records,evaluations)
    restored,ev=read_segmentation(dest/'segmentation.seg.nrrd',volume)
    # Actual workspace codec, checked separately from NRRD representation.
    workspace_state.atomic_write(dest/'records.json',workspace_state.dumps(records))
    saved=workspace_state.loads((dest/'records.json').read_bytes())
    for group in (restored,saved):
        assert len(group)==len(records)
        for record,expected in zip(group,masks):
            dense=np.zeros(shape,bool); origin=record['mask_offset']; mask=record['mask']
            dense[tuple(slice(int(x),int(x)+n) for x,n in zip(origin,mask.shape))]=mask
            np.testing.assert_array_equal(dense,expected)
    assert [r['name'] for r in restored]==[r['name'] for r in records]
    assert [r['color'] for r in restored]==[r['color'] for r in records]
    np.savez_compressed(dest/'masks.npz',**{f'mask{i}':m for i,m in enumerate(masks)})
    return counts


def verify_case(root):
    root=Path(root); manifest=json.loads((root/'case.json').read_text()); spec=manifest['case']
    truth=np.load(root/'truth.npz'); loader=DicomLoader()
    paths=[root/f['path'] for f in manifest['files']]
    if spec['defect']=='duplicate-file': paths=paths+paths
    snapshot=list(DicomFolderScanner().scan_files(paths,folder=root))[-1]
    expected_groups=spec['phases'] if spec['enhanced'] else 1
    assert len(snapshot.series)==expected_groups, f'Unexpected groups: {len(snapshot.series)}'
    output=dict(case=spec['name'],groups=len(snapshot.series),volumes=[],source_frames_checked=0)
    lookup={(s['path'],s['frame']):s for s in manifest['sources']}
    seen=set()
    work=[(series,phase.phase_identifier) for series in snapshot.series for phase in series.phases] if not spec['enhanced'] and spec['phases']>1 and snapshot.series[0].phases else [(series,None) for series in snapshot.series]
    assert len(work)==(spec['phases'] if manifest['expected_volume'] else expected_groups)
    for series,phase_identifier in work:
        instances=series.phase_by_identifier(phase_identifier).instances if phase_identifier is not None else series.instances
        ordered=sorted(instances,key=lambda i: lookup[(i.path.name,i.frame_index)]['z'])
        for instance in ordered:
            source=lookup[(instance.path.name,instance.frame_index)]
            identity=(instance.path.name,instance.frame_index)
            assert identity not in seen;seen.add(identity)
            original=pydicom.dcmread(instance.path)
            assert instance.sop_instance_uid==str(original.SOPInstanceUID)
            stored=decode_pixels(original,index=instance.frame_index)
            np.testing.assert_array_equal(stored,truth['stored'][source['z']]+source['phase']*100)
            ds,values=loader.read_frame(instance.path,instance.frame_index)
            reference=truth[f'pixels{source["phase"]}'][source['z']]
            close(values,reference)
            for invert,window in [(False,WindowLevel(20,300)),(True,WindowLevel(700,25))]:
                rendered=loader.load_dataset(ds,window,invert,modality_pixels=values)
                assert rendered.pixel_value_meta.unit==manifest['unit']
                quantitative=truth[f'display{source["phase"]}'][source['z']] if spec['modality']=='PT' else reference
                close(rendered.modality_pixel,quantitative)
                close(values,reference)
            output['source_frames_checked']+=1
        try: volume=VolumeManager().get_or_build(series,phase_identifier)
        except (ValueError,RuntimeError) as error:
            if manifest['expected_volume']: raise
            output.update(status='expected_unsupported',reason=str(error)); continue
        assert manifest['expected_volume'], 'Invalid geometry silently accepted as a regular volume'
        phase=lookup[(ordered[0].path.name,ordered[0].frame_index)]['phase']
        pixels=truth[f'display{phase}'] if spec['modality']=='PT' else truth[f'pixels{phase}']
        dest=root/f'group-{phase}'; dest.mkdir(exist_ok=True)
        close(volume.modality_pixels,pixels)
        close(volume.geometry.voxel_to_patient,truth['affine'],atol=.001,rtol=0)
        affine=truth['affine']
        landmarks=np.array([[0,0,0,1],[8,16,22,1],[1,3,5,1],[4,8,11,1]],float).T
        geometry_error=close(volume.geometry.voxel_to_patient@landmarks,affine@landmarks,atol=.001,rtol=0)
        planes=check_planes(volume,pixels,affine,dest)
        measurements=check_measurements(pixels[len(pixels)//2],spec['spacing'][1:])
        counts=check_exchange(volume,dest)
        np.savez_compressed(dest/'voxenra.npz',pixels=volume.modality_pixels,
            source_pixels=truth[f'pixels{phase}'],affine=volume.geometry.voxel_to_patient)
        (dest/'sources.json').write_text(json.dumps([lookup[(i.path.name,i.frame_index)] for i in ordered]))
        output['volumes'].append(dict(phase=phase,geometry_max_error_mm=geometry_error,planes=planes,
            measurements=measurements,segment_counts=counts,unit=volume.pixel_value_meta.unit))
    assert len(seen)==len(manifest['sources'])
    output.setdefault('status','pass')
    (root/'voxenra-result.json').write_text(json.dumps(output,indent=2))
    return output
