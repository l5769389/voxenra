"""Slicer --python-script verification, including Segment Statistics and edits.

VOXENRA_NRRD_QA points to a case directory, or a parent with case directories.
Each case contains source.nrrd, segmentation.seg.nrrd and expected.npz.
Optional dicom-reference.json enables independent GDCM decoding of source DICOM.
No data leaves this computer. Results and a Slicer-edited .seg.nrrd stay local.
"""
import json
import os
import traceback
from pathlib import Path

import numpy as np
import slicer
import vtk


def verify(root):
    slicer.mrmlScene.Clear(0)
    expected = np.load(root / 'expected.npz')
    volume = slicer.util.loadVolume(str(root / 'source.nrrd'))
    node = slicer.util.loadSegmentation(str(root / 'segmentation.seg.nrrd'))
    assert volume and node
    np.testing.assert_array_equal(slicer.util.arrayFromVolume(volume), expected['pixels'])
    matrix = vtk.vtkMatrix4x4()
    volume.GetIJKToRASMatrix(matrix)
    actual = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
    affine = np.diag([-1, -1, 1, 1]) @ actual @ np.eye(4)[[2, 1, 0, 3]]
    np.testing.assert_allclose(affine, expected['affine'], atol=1e-6)
    independent_dicom = False
    reference = root / 'dicom-reference.json'
    if reference.exists():
        import SimpleITK as sitk
        config = json.loads(reference.read_text())
        reader = sitk.ImageSeriesReader()
        paths = reader.GetGDCMSeriesFileNames(config['directory'], config['uid'])
        if not paths:
            # Some local series omit File Meta Information needed by directory
            # discovery. Explicit files still use ITK/GDCM for pixel decoding.
            import pydicom
            headers = [(p, pydicom.dcmread(p, stop_before_pixels=True, force=True))
                       for p in config['paths']]
            direction = np.array(headers[0][1].ImageOrientationPatient, float)
            normal = np.cross(direction[:3], direction[3:])
            paths = [p for p, d in sorted(headers, key=lambda item:
                     np.dot(np.array(item[1].ImagePositionPatient, float), normal))]
        reader.SetFileNames(paths)
        original = reader.Execute()
        np.testing.assert_array_equal(sitk.GetArrayFromImage(original), expected['pixels'])
        original_affine = np.eye(4)
        original_affine[:3, :3] = (np.array(original.GetDirection()).reshape(3, 3)
                                    @ np.diag(original.GetSpacing()))[:, ::-1]
        original_affine[:3, 3] = original.GetOrigin()
        np.testing.assert_allclose(original_affine, affine, atol=1e-5, rtol=0)
        independent_dicom = True
    segmentation = node.GetSegmentation()
    assert segmentation.GetNumberOfSegments() == sum(k.startswith('mask') for k in expected.files)
    counts, ids = [], []
    for i in range(segmentation.GetNumberOfSegments()):
        sid = segmentation.GetNthSegmentID(i)
        ids.append(sid)
        if expected[f'mask{i}'].any():
            mask = slicer.util.arrayFromSegmentBinaryLabelmap(node, sid, volume).astype(bool)
            np.testing.assert_array_equal(mask, expected[f'mask{i}'])
        else:
            # Slicer represents empty segments with an empty image extent; its
            # reference-grid array helper cannot resample that representation.
            representation = segmentation.GetSegment(sid).GetRepresentation('Binary labelmap')
            scalars = representation.GetPointData().GetScalars() if representation else None
            assert scalars is None or not np.any(vtk.util.numpy_support.vtk_to_numpy(scalars))
            mask = np.zeros_like(expected[f'mask{i}'])
        assert segmentation.GetSegment(sid).GetName() == str(expected[f'name{i}'])
        np.testing.assert_allclose(segmentation.GetSegment(sid).GetColor(), expected[f'color{i}'], atol=1e-6)
        counts.append(int(mask.sum()))
    statistics_checked = False
    if (root / 'voxenra-metrics.json').exists():
        from SegmentStatistics import SegmentStatisticsLogic
        metrics = json.loads((root / 'voxenra-metrics.json').read_text())
        logic = SegmentStatisticsLogic()
        logic.getParameterNode().SetParameter('Segmentation', node.GetID())
        logic.getParameterNode().SetParameter('ScalarVolume', volume.GetID())
        logic.getParameterNode().SetParameter('ClosedSurfaceSegmentStatisticsPlugin.enabled', 'False')
        logic.computeStatistics()
        stats = logic.getStatistics()
        statistics = []
        for sid, values in zip(ids, metrics):
            result = {}
            for key, field in [('voxel_count', 'count'), ('volume_cm3', 'volume'),
                               ('mean', 'mean'), ('min', 'minimum'), ('max', 'maximum')]:
                value = stats.get((sid, 'ScalarVolumeSegmentStatisticsPlugin.' + key))
                if values['count']:
                    np.testing.assert_allclose(value, values[field], rtol=1e-5, atol=1e-7)
                result[field] = value
            # VTK reports sample SD. Voxenra explicitly reports population SD.
            sample_sd = stats.get((sid, 'ScalarVolumeSegmentStatisticsPlugin.stdev'))
            if values['count'] > 1:
                population_sd = sample_sd * np.sqrt((values['count'] - 1) / values['count'])
                np.testing.assert_allclose(population_sd, values['sd'], rtol=1e-5, atol=1e-7)
                result['population_sd'] = population_sd
            statistics.append(result)
        (root / 'slicer-statistics.json').write_text(json.dumps(statistics, indent=2))
        statistics_checked = True
    mask = slicer.util.arrayFromSegmentBinaryLabelmap(node, ids[0], volume).copy()
    mask[1, 2, 3] = 1
    slicer.util.updateSegmentBinaryLabelmapFromArray(mask, node, ids[0], volume)
    segmentation.GetSegment(ids[0]).SetName('Slicer edited')
    assert slicer.util.saveNode(node, str(root / 'slicer-return.seg.nrrd'))
    result = dict(slicer=slicer.app.applicationVersion, counts=counts, pixels_equal=True,
                  geometry_equal=True, overlapping_masks_equal=True, names_and_colors_equal=True,
                  independent_dicom=independent_dicom, segment_statistics_equal=statistics_checked)
    (root / 'slicer-result.json').write_text(json.dumps(result, indent=2))
    print('NRRD_SLICER_OK', root.name, result, flush=True)
    return result


root = Path(os.environ['VOXENRA_NRRD_QA'])
try:
    cases = [root] if (root / 'expected.npz').exists() else sorted(p.parent for p in root.glob('*/expected.npz'))
    assert cases, 'No prepared cases'
    results = {case.name: verify(case) for case in cases}
    (root / 'slicer-summary.json').write_text(json.dumps(results, indent=2))
except Exception:
    (root / 'slicer-error.txt').write_text(traceback.format_exc())
    traceback.print_exc()
    slicer.app.exit(1)
else:
    slicer.app.exit(0)
