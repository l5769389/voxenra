"""Run with Slicer --python-script; VOXENRA_SPATIAL_AUDIT is a local case root.

Uses an isolated DICOM database and the installed scalar-volume DICOM plugin.
No Voxenra modules are imported. Failures and loadable warnings remain evidence.
"""
import json
import os
import traceback
from pathlib import Path
import numpy as np
import slicer
import vtk
from DICOMLib import DICOMUtils

ROOT=Path(os.environ['VOXENRA_SPATIAL_AUDIT']).resolve()


def affine(node):
    matrix=vtk.vtkMatrix4x4();node.GetIJKToRASMatrix(matrix)
    ras=np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)])
    return np.diag([-1,-1,1,1])@ras@np.eye(4)[[2,1,0,3]]


def exchange(root):
    from SegmentStatistics import SegmentStatisticsLogic
    results=[]
    for group in sorted(root.glob('group-*')):
        if not (group/'segmentation.seg.nrrd').exists(): continue
        slicer.mrmlScene.Clear(0)
        volume=slicer.util.loadVolume(str(group/'source.nrrd'))
        seg=slicer.util.loadSegmentation(str(group/'segmentation.seg.nrrd'))
        expected=np.load(group/'masks.npz'); v=np.load(group/'voxenra.npz')
        np.testing.assert_allclose(affine(volume),v['affine'],atol=.001,rtol=0)
        np.testing.assert_allclose(slicer.util.arrayFromVolume(volume),v['pixels'],atol=0,rtol=0,equal_nan=True)
        segmentation=seg.GetSegmentation();counts=[]
        assert segmentation.GetNumberOfSegments()==len(expected.files)
        for i in range(segmentation.GetNumberOfSegments()):
            sid=segmentation.GetNthSegmentID(i)
            if expected[f'mask{i}'].any():
                actual=slicer.util.arrayFromSegmentBinaryLabelmap(seg,sid,volume).astype(bool)
                np.testing.assert_array_equal(actual,expected[f'mask{i}'])
            else:
                rep=segmentation.GetSegment(sid).GetRepresentation('Binary labelmap')
                assert rep.GetPointData().GetScalars() is None or rep.GetScalarRange()==(0.,0.)
            counts.append(int(expected[f'mask{i}'].sum()))
        logic=SegmentStatisticsLogic();p=logic.getParameterNode()
        p.SetParameter('Segmentation',seg.GetID());p.SetParameter('ScalarVolume',volume.GetID())
        p.SetParameter('ClosedSurfaceSegmentStatisticsPlugin.enabled','False')
        logic.computeStatistics();stats=logic.getStatistics();numeric=[]
        for i,count in enumerate(counts):
            if not count: continue
            sid=segmentation.GetNthSegmentID(i);values=v['pixels'][expected[f'mask{i}']].astype(float)
            prefix='ScalarVolumeSegmentStatisticsPlugin.'
            for name,expected_value in [('voxel_count',count),('mean',values.mean()),('min',values.min()),('max',values.max()),
                ('volume_cm3',count*abs(np.linalg.det(v['affine'][:3,:3]))/1000),
                ('stdev',values.std(ddof=1))]:
                np.testing.assert_allclose(stats[(sid,prefix+name)],expected_value,rtol=1e-5,atol=1e-5)
            numeric.append(dict(count=count,mean=float(values.mean())))
        assert slicer.util.saveNode(seg,str(group/'slicer-return.seg.nrrd'))
        results.append(dict(group=group.name,status='pass',counts=counts,statistics=numeric))
    return results


def collect(root):
    result=dict(case=root.name,slicer=slicer.app.applicationVersion,dicom=[],exchange=[])
    manifest=json.loads((root/'case.json').read_text())
    # Case directory contains original DICOM only; outputs have non-DICOM suffixes.
    with DICOMUtils.TemporaryDICOMDatabase(str(root/'slicer-db')):
        import ctk
        indexer=ctk.ctkDICOMIndexer()
        for entry in manifest['files']:
            indexer.addFile(slicer.dicomDatabase,str(root/entry['path']))
        indexer.waitForImportFinished()
        plugin=slicer.modules.dicomPlugins['DICOMScalarVolumePlugin']()
        all_uids=[u for p in slicer.dicomDatabase.patients()
                    for s in slicer.dicomDatabase.studiesForPatient(p)
                    for u in slicer.dicomDatabase.seriesForStudy(s)]
        result['series_count']=len(all_uids)
        for uid in all_uids:
            files=list(slicer.dicomDatabase.filesForSeries(uid))
            loadables=plugin.examineForImport([files])
            result['loadables']=[dict(name=l.name,selected=l.selected,warning=l.warning,
                                     confidence=l.confidence,files=len(l.files)) for l in loadables]
            for l in loadables:
                if not l.selected: continue
                slicer.mrmlScene.Clear(0)
                record=dict(name=l.name,warning=l.warning,reader='GDCM with DCMTK fallback')
                try:
                    node=plugin.load(l,readerApproach='GDCM with DCMTK fallback')
                    assert node is not None,'DICOM plugin did not load volume'
                    values=slicer.util.arrayFromVolume(node).copy(); matrix=affine(node)
                    transform=node.GetParentTransformNode()
                    record.update(status='loaded',shape=list(values.shape),
                        transform=transform.GetClassName() if transform else None,
                        affine_lps=matrix.tolist(),range=[float(np.nanmin(values)),float(np.nanmax(values))])
                    number=len(result['dicom'])
                    np.savez_compressed(root/f'slicer-dicom-{number}.npz',pixels=values,affine=matrix)
                    if transform: slicer.util.saveNode(transform,str(root/f'slicer-transform-{number}.h5'))
                    # Independent physical length using Slicer Markups logic.
                    line=slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsLineNode')
                    points=(matrix@np.array([[0,1.5,.5,1],[0,9.5,10.5,1]]).T).T[:,:3]
                    for point in points: line.AddControlPoint(vtk.vtkVector3d(*(-point*np.array([1,1,-1]))))
                    record['line_mm']=line.GetMeasurement('length').GetValue()
                    record['line_expected_mm']=float(np.linalg.norm(points[1]-points[0]))
                    np.testing.assert_allclose(record['line_mm'],record['line_expected_mm'],atol=1e-4,rtol=1e-6)
                except Exception: record.update(status='load_error',reason=traceback.format_exc())
                result['dicom'].append(record)
    try:result['exchange']=exchange(root)
    except Exception:result['exchange_error']=traceback.format_exc()
    (root/'slicer-result.json').write_text(json.dumps(result,indent=2))
    return result


results=json.loads((ROOT/'slicer-summary.json').read_text()) if os.environ.get('VOXENRA_SPATIAL_CASES') and (ROOT/'slicer-summary.json').exists() else []
selected=set(filter(None,os.environ.get('VOXENRA_SPATIAL_CASES','').split(',')))
for path in sorted(ROOT.glob('*/case.json')):
    if selected and path.parent.name not in selected:continue
    try: result=collect(path.parent)
    except Exception: result=dict(case=path.parent.name,error=traceback.format_exc())
    results=[r for r in results if r['case']!=path.parent.name]
    results.append(result)
    (ROOT/'slicer-summary.json').write_text(json.dumps(results,indent=2))
    print('SPATIAL_SLICER',path.parent.name,flush=True)
slicer.app.exit(0)
