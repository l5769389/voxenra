from dataclasses import replace
import gzip
import numpy as np
import pytest
from qt_dicom_viewer.core.nrrd_exchange import read_nrrd, write_nrrd, read_segmentation, write_segmentation
from qt_dicom_viewer.core.segmentation_masks import mask_record
from test_mpr_reslicer import _volume


def dense(record, shape):
    data=np.zeros(shape,bool)
    data[tuple(slice(a,a+b) for a,b in zip(record['mask_offset'],record['mask'].shape))]=record['mask']
    return data


def sample():
    volume=_volume(np.arange(13*17*19).reshape(13,17,19),origin=(12,-21,33),
        slice_spacing=2.4,row_spacing=.7,column_spacing=.5)
    masks=[];records=[];results={}
    for n in range(2):
        mask=np.zeros(volume.modality_pixels.shape,bool)
        mask[2+n:8+n,3:9,4:11]=True
        record,result=mask_record(volume,mask,(0,0,0),name=['肝脏','Overlap'][n],color=['#ff8833','#33cc55'][n])
        masks.append(mask);records.append(record);results[record['id']]=result
    return volume,masks,records,results


def test_volume_and_overlapping_segmentation_roundtrip(tmp_path):
    v,masks,records,results=sample()
    write_nrrd(tmp_path/'source.nrrd',v.modality_pixels,v.geometry.voxel_to_patient)
    data,affine,h=read_nrrd(tmp_path/'source.nrrd')
    np.testing.assert_array_equal(data,v.modality_pixels)
    np.testing.assert_allclose(affine,v.geometry.voxel_to_patient)
    path=tmp_path/'segments.seg.nrrd'
    write_segmentation(path,v,records,results)
    read,ev=read_segmentation(path,v)
    assert [r['name'] for r in read]==[r['name'] for r in records]
    assert [r['color'] for r in read]==[r['color'] for r in records]
    for r,m in zip(read,masks):np.testing.assert_array_equal(dense(r,m.shape),m)
    assert np.logical_and(*(dense(r,masks[0].shape) for r in read)).sum()>0
    assert [ev[r['id']].metrics['volume'] for r in read]==[results[r['id']].metrics['volume'] for r in records]


def test_ras_flip_cropped_labels_and_reject_subvoxel_mismatch(tmp_path):
    v,masks,_,_=sample()
    mask=masks[0][2:8,3:9,4:11][:,:,::-1].astype('uint16')*7
    affine=v.geometry.voxel_to_patient.copy()
    affine[:3,3]=(affine@[2,3,10,1])[:3]
    affine[:3,2]*=-1
    path=tmp_path/'label.nrrd'
    write_nrrd(path,mask,affine)
    # Transform header LPS to RAS independently, preserving the payload.
    raw=path.read_bytes();header,payload=raw.split(b'\n\n',1)
    h=header.decode(); ras=np.diag([-1,-1,1,1])@affine
    lines=[]
    for line in h.splitlines():
        if line.startswith('space:'): line='space: right-anterior-superior'
        if line.startswith('space origin:'):line='space origin: ('+','.join(map(str,ras[:3,3]))+')'
        if line.startswith('space directions:'):line='space directions: '+' '.join('('+','.join(map(str,ras[:3,i]))+')' for i in (2,1,0))
        lines.append(line)
    path.write_bytes(('\n'.join(lines)+'\n\n').encode()+payload)
    records,_=read_segmentation(path,v)
    np.testing.assert_array_equal(dense(records[0],masks[0].shape),masks[0])
    affine[:3,3]+=.1
    write_nrrd(path,mask,affine)
    with pytest.raises(ValueError):read_segmentation(path,v)


def test_detached_raw_big_endian_and_payload_limits(tmp_path):
    payload=np.arange(24,dtype='>i2').reshape(2,3,4)
    (tmp_path/'source.raw').write_bytes(payload.tobytes())
    text='NRRD0005\ntype: short\ndimension: 3\nsizes: 4 3 2\nspace: LPS\nspace directions: (1,0,0) (0,1,0) (0,0,2)\nspace origin: (0,0,0)\nencoding: raw\nendian: big\ndata file: source.raw\n\n'
    path=tmp_path/'source.nhdr';path.write_text(text)
    actual,_,_=read_nrrd(path)
    np.testing.assert_array_equal(actual,payload)
    path.write_text(text.replace('4 3 2','99999999 99999999 99999999'))
    with pytest.raises(ValueError):read_nrrd(path)
    path.write_text(text.replace('source.raw','../source.raw'))
    with pytest.raises(ValueError):read_nrrd(path)


def test_cancel_keeps_existing_file_and_empty_segment_roundtrip(tmp_path):
    v,masks,records,results=sample();path=tmp_path/'seg.nrrd'
    path.write_bytes(b'original')
    with pytest.raises(InterruptedError):
        write_segmentation(path,v,records,results,cancelled=lambda:True)
    assert path.read_bytes()==b'original' and not list(tmp_path.glob('.nrrd-*'))
    r,e=mask_record(v,np.zeros((1,1,1),bool),(0,0,0),name='Empty',allow_empty=True)
    records.append(r);results[r['id']]=e
    write_segmentation(path,v,records,results)
    restored,ev=read_segmentation(path,v)
    assert len(restored)==3 and ev[restored[-1]['id']].metrics['count']==0
