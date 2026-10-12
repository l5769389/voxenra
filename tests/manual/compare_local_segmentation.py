"""Compare a verified Voxenra run with independent TotalSegmentator or Slicer.

Run using the external TotalSegmentator Python (SimpleITK + NumPy required):
  python tests/manual/compare_local_segmentation.py RUN_DIRECTORY --standalone STANDALONE_DIRECTORY
RUN_DIRECTORY contains source.nrrd and expected.npz written by verify_local_segmentation.
Only axis permutation/flips are used to normalize grids; there is no interpolation.
For the Slicer return, run with the Voxenra Python and --slicer-return after
verify_nrrd_slicer.py. This checks its intentional [1,2,3] edit as well.
"""
import argparse
import json
from pathlib import Path
import numpy as np


def standalone(root, previous):
    import SimpleITK as sitk
    expected=np.load(root/'expected.npz')
    image=sitk.DICOMOrient(sitk.ReadImage(str(previous/'source.nii.gz')),'LPS')
    source=sitk.ReadImage(str(root/'source.nrrd'))
    np.testing.assert_array_equal(sitk.GetArrayFromImage(image),expected['pixels'])
    np.testing.assert_allclose(image.GetOrigin(),source.GetOrigin(),atol=.001,rtol=0)
    np.testing.assert_allclose(image.GetDirection(),source.GetDirection(),atol=1e-6,rtol=0)
    np.testing.assert_allclose(image.GetSpacing(),source.GetSpacing(),atol=1e-6,rtol=0)
    organs={}
    for i,key in enumerate(expected['organs']):
        image=sitk.DICOMOrient(sitk.ReadImage(str(previous/'masks'/f'{key}.nii.gz')),'LPS')
        np.testing.assert_array_equal(sitk.GetArrayFromImage(image).astype(bool),expected[f'mask{i}'])
        np.testing.assert_allclose(image.GetOrigin(),source.GetOrigin(),atol=.001,rtol=0)
        np.testing.assert_allclose(image.GetDirection(),source.GetDirection(),atol=1e-6,rtol=0)
        np.testing.assert_allclose(image.GetSpacing(),source.GetSpacing(),atol=1e-6,rtol=0)
        organs[str(key)]={'voxels':int(expected[f'mask{i}'].sum()),'different_voxels':0}
    return dict(source_pixels_equal=True,axis_reorientation_only=True,organs=organs)


def slicer_return(root):
    from qt_dicom_viewer.core.nrrd_exchange import read_nrrd,read_segmentation
    from qt_dicom_viewer.model import DicomVolume,VolumeGeometry,PixelValueMeta
    expected=np.load(root/'expected.npz')
    pixels,affine,_=read_nrrd(root/'source.nrrd')
    spacing=np.linalg.norm(affine[:3,:3],axis=0);directions=affine[:3,:3]/spacing
    geometry=VolumeGeometry(*pixels.shape,row_spacing=spacing[1],column_spacing=spacing[2],
        slice_spacing=spacing[0],origin_patient=tuple(affine[:3,3]),
        slice_index_direction_patient=tuple(directions[:,0]),row_index_direction_patient=tuple(directions[:,1]),
        column_index_direction_patient=tuple(directions[:,2]))
    volume=DicomVolume(pixels,geometry,'validation',None,None,PixelValueMeta(unit='HU'))
    records,_=read_segmentation(root/'slicer-return.seg.nrrd',volume)
    assert len(records)==len(expected['organs'])
    for i,record in enumerate(records):
        mask=np.zeros(pixels.shape,bool)
        mask[tuple(slice(o,o+n) for o,n in zip(record['mask_offset'],record['mask'].shape))]=record['mask']
        wanted=expected[f'mask{i}'].copy()
        if i==0:
            wanted[1,2,3]=True
            assert record['name']=='Slicer edited'
        np.testing.assert_array_equal(mask,wanted)
    return dict(all_masks_equal=True,edited_voxel_equal=True,segments=len(records))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--standalone',type=Path)
    group.add_argument('--slicer-return',action='store_true')
    args=parser.parse_args()
    result=standalone(args.root,args.standalone) if args.standalone else slicer_return(args.root)
    name='standalone-comparison.json' if args.standalone else 'slicer-return-comparison.json'
    (args.root/name).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
