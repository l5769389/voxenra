"""Opt-in acceptance against unchanged public Enhanced MR + NIfTI references."""
from pathlib import Path
import gzip, hashlib, json, os, struct
import numpy as np
import pydicom
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.volume_manager import VolumeManager
from voxplane.core.mr import mr_series_error
from voxplane.core.series_thumbnail import read_series_thumbnail
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click, descendants
from manual.test_mr_samples import sample_root, import_local, ready


def scan(path):
    return list(DicomFolderScanner().scan_files(sorted(Path(path).rglob('*.dcm')),folder=path,can_publish=lambda:False))[-1]


def nifti_reference(path):
    """Minimal reader for these fixed NIfTI-1 fixtures, not an application importer.

    Keep stored values unscaled: Philips reference files use a documented private
    precise-value scale, while the viewer intentionally uses standard rescale.
    """
    data=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    assert struct.unpack_from('<i',data)[0]==348 and data[344:347]==b'n+1'
    dims=struct.unpack_from('<8h',data,40)
    dtype={2:'u1',4:'<i2',16:'<f4',512:'<u2'}[struct.unpack_from('<h',data,70)[0]]
    offset=int(struct.unpack_from('<f',data,108)[0])
    array=np.frombuffer(data,dtype=dtype,offset=offset).reshape(dims[1:dims[0]+1],order='F')
    assert struct.unpack_from('<h',data,254)[0]>0
    affine=np.eye(4);affine[:3]=np.array(struct.unpack_from('<12f',data,280)).reshape(3,4)
    return array,affine


def reference_for(series,root):
    p=series.instances[0].mr_parameters
    name=series.instances[0].path.name
    time=int(p.temporal_position or 1)-1
    if name=='DTI_PA.dcm':return root/'Ref/Canon_DTI_PA-ortho_9000.nii',time
    if name=='IM_0006_T1.dcm':return root/('Ref/Philips_WIP_AnatBrain_T1W3D_301'+('_ph' if p.component=='PHASE' else '')+'.nii'),0
    if name=='IM_0027_fMAP.dcm':return root/('Ref/Philips_WIP_B0_NS_801_'+('e1' if p.component=='MAGNITUDE' else 'e2_fieldmaphz')+'.nii'),0
    if name=='IM_0035_fMRI.dcm':return root/f'Ref/Philips_WIP_resting_state_1001_e{1 if p.echo_time<15 else 2}.nii',time
    return root/'Ref/Siemens_REST1_w_SMS_PF7-8_6.nii',time


def test_public_enhanced_frames_values_and_patient_space_against_references(sample_root,tmp_path):
    root=sample_root/'Enhanced-MR';s=scan(root/'In')
    assert s.dicom_file_count==8 and len(s.series)==29
    sources={p:pydicom.dcmread(p) for p in {i.path for r in s.series for i in r.instances}}
    decoded={p:d.pixel_array for p,d in sources.items()}
    references={}
    report=[]
    for r in s.series:
        assert not mr_series_error(r,volume=True)
        volume=VolumeManager().get_or_build(r)
        path,t=reference_for(r,root)
        if path not in references:references[path]=nifti_reference(path)
        ref,affine=references[path];inverse=np.linalg.inv(affine)
        if ref.ndim==4:ref=ref[:,:,:,t]
        for z,instance in enumerate(r.instances):
            ds=sources[instance.path];f=instance.frame_index;raw=decoded[instance.path][f]
            # Independent direct functional-group lookup, not the app flattener.
            groups=[*getattr(ds,'SharedFunctionalGroupsSequence',()),ds.PerFrameFunctionalGroupsSequence[f]]
            def fg(keyword):return next(getattr(g,keyword)[0] for g in reversed(groups) if keyword in g)
            pvt=fg('PixelValueTransformationSequence') if any('PixelValueTransformationSequence' in g for g in groups) else ds
            expected=raw.astype(float)*float(getattr(pvt,'RescaleSlope',1))+float(getattr(pvt,'RescaleIntercept',0))
            if 'PixelPaddingValue' in ds:
                low=float(ds.PixelPaddingValue);high=float(getattr(ds,'PixelPaddingRangeLimit',low))
                expected[(raw>=min(low,high)) & (raw<=max(low,high))]=np.nan
            np.testing.assert_allclose(volume.modality_pixels[z],expected,atol=.002,rtol=1e-6)
            ipp=np.asarray(fg('PlanePositionSequence').ImagePositionPatient,float)
            u,v=np.asarray(fg('PlaneOrientationSequence').ImageOrientationPatient,float).reshape(2,3)
            spacing=np.asarray(fg('PixelMeasuresSequence').PixelSpacing,float)
            for y,x in ((0,0),(raw.shape[0]//3,raw.shape[1]//3),(raw.shape[0]//2,raw.shape[1]//2),(raw.shape[0]-1,raw.shape[1]-1)):
                lps=ipp+u*x*spacing[1]+v*y*spacing[0]
                np.testing.assert_allclose((volume.geometry.voxel_to_patient@[z,y,x,1])[:3],lps,atol=.002)
                ras=lps*np.array([-1,-1,1]);coord=(inverse@[*ras,1])[:3]
                np.testing.assert_allclose(coord,np.rint(coord),atol=.002)
                q=np.rint(coord).astype(int)
                assert np.all(q>=0) and np.all(q<ref.shape)
                assert ref[tuple(q)]==pytest.approx(raw[y,x],abs=.01)
        first=r.instances[0]
        assert not read_series_thumbnail(first.path,first.frame_index).isNull()
        report.append(dict(description=r.series_description,frames=len(r.instances),shape=list(volume.modality_pixels.shape),reference=path.name))
    assert sum(r['frames'] for r in report)==928
    (tmp_path/'enhanced-reference-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


def test_thin_t1_matches_upstream_volume_and_one_mm_geometry(sample_root):
    root=sample_root/'Thin-3D-T1'
    s=scan(root/'DICOM');assert len(s.series)==1
    r=s.series[0];assert len(r.instances)==192
    v=VolumeManager().get_or_build(r)
    assert (v.geometry.row_spacing,v.geometry.column_spacing,v.geometry.slice_spacing)==pytest.approx((1,1,1),abs=.001)
    ref,affine=nifti_reference(next((root/'Ref').glob('*.nii.gz')))
    inverse=np.linalg.inv(affine)
    for z in (0,48,96,144,191):
        for y,x in ((64,64),(128,128),(192,192)):
            lps=(v.geometry.voxel_to_patient@[z,y,x,1])[:3]
            q=(inverse@[*(lps*np.array([-1,-1,1])),1])[:3]
            np.testing.assert_allclose(q,np.rint(q),atol=.002)
            assert ref[tuple(np.rint(q).astype(int))]==v.modality_pixels[z,y,x]


def test_new_downloads_match_fixed_upstream_hashes(sample_root):
    for folder in ('Enhanced-MR','Thin-3D-T1'):
        root=sample_root/folder;m=json.loads((root/'manifest.json').read_text())
        for record in [*m['files'],*m.get('extracted',[])]:
            data=(root/record['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest()==record['sha256']


def test_real_four_series_ui_and_selected_frame_export(scene,sample_root,tmp_path):
    window,app,warnings=scene
    path=sample_root/'Enhanced-MR/In/Philips/IM_0035_fMRI.dcm'
    import_local(app,[path]);ws=app.workspaceController
    records=list(app.panelController._scan_series_record.values())
    assert len(records)==8
    picker=app.panelController.compareController
    picker.request(records[0].series_instance_uid)
    QTest.qWait(80)
    candidates=find(window,'compareCandidates')
    for index,r in enumerate(picker.candidates[:3]):
        candidates.setProperty('contentY',78*index)
        QTest.qWait(30)
        click(window,find(window,'compareCandidate-'+r['seriesUid']))
    assert len(picker.partnerUids)==3
    click(window,find(window,'confirmCompare'));ready(ws)
    tab=ws.activeTab;views=list(tab.viewports_by_id.values())
    assert len(views)==4 and tab.scrollMode=='spatial'
    views[0].setSliceIndex(16)
    wait_until(lambda:all(v._frame_meta.slice_index==16 for v in views))
    for width,height in ((1000,650),(1400,900)):
        window.resize(width,height);QTest.qWait(100)
        rects=[]
        for v in views:
            cell=find(window,'imageViewport-'+v.viewportId)
            assert cell.width()>100 and cell.height()>100
            rects.append(cell.mapRectToScene(cell.boundingRect()))
        for i,r in enumerate(rects):assert not any(r.intersects(other) for other in rects[i+1:])
    QTest.qWait(150)
    assert window.grabWindow().save(str(tmp_path/'enhanced-four-series.png'))
    assert not warnings,warnings


@pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM')=='offscreen',reason='Native VTK requires a desktop surface')
def test_native_thin_mr_3d_and_mpr_reference(scene,sample_root,tmp_path):
    window,app,warnings=scene
    import_local(app,[sample_root/'Thin-3D-T1/DICOM']);ws=app.workspaceController
    r=next(iter(app.panelController._scan_series_record.values()))
    ws.createTab(r.series_instance_uid,'Thin MR 3D','3d');ready(ws)
    view=ws.activeViewport
    wait_until(lambda:view._host is not None,timeout=15000);QTest.qWait(200)
    before=view.volume.modality_pixels.copy()
    for preset in ('mr-general','mr-bright','mr-mip'):
        view.applyVolumePreset(preset);QTest.qWait(100)
        if preset=='mr-mip':
            assert view.windowWidth==float(np.nanmax(before)-np.nanmin(before))
        shot=view.snapshot_image();assert not shot.isNull()
        assert shot.save(str(tmp_path/(preset+'.png')))
    view.setViewFace('L');view.setZoom(1.2);view.autoWindow();QTest.qWait(100)
    np.testing.assert_array_equal(view.volume.modality_pixels,before)
    ws.createTab(r.series_instance_uid,'Thin MR MPR','mpr');ready(ws)
    tab=ws.activeTab;tab.mprLayout.setLayout('quad')
    reference=tab.mprLayout.volumeViewport
    wait_until(lambda:reference._host is not None,timeout=15000);QTest.qWait(250)
    assert reference.currentPresetId=='mr-general'
    assert reference.volume is tab.mprLayout._pending_volume
    assert reference.snapshot_image().save(str(tmp_path/'mr-mpr-reference.png'))
    assert window.grabWindow().save(str(tmp_path/'mr-mpr-four-views.png'))
    assert not warnings,warnings



@pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM')=='offscreen',reason='Native VTK requires a desktop surface')
@pytest.mark.parametrize('polarity', ['MONOCHROME1','MONOCHROME2'])
def test_native_mr_padding_stays_excluded_on_mip_and_reset(scene,tmp_path,polarity):
    from test_mr import write_mr_series
    from voxplane.model import DicomFolderScanSnapshot
    from vtkmodules.util.numpy_support import vtk_to_numpy
    window,app,warnings=scene
    def padding(ds,index):
        raw=ds.pixel_array.copy()
        raw[:8,:]=-30000;raw[-8:,:]=-30000
        raw[:,:8]=-30000;raw[:,-8:]=-30000
        ds.PixelData=raw.tobytes();ds.PixelPaddingValue=-30000
        ds.PhotometricInterpretation=polarity
    r=write_mr_series(tmp_path/'padded',12,change=padding)
    s=DicomFolderScanSnapshot(tmp_path,12,12,0,[r])
    app.panelController.update_series_session(s);app.panelController._update_series_record(s)
    ws=app.workspaceController
    ws.createTab(r.series_instance_uid,'Synthetic padded MR','3d');ready(ws)
    view=ws.activeViewport
    wait_until(lambda:view._host is not None,timeout=15000)
    QTest.qWait(150)
    before=view.volume.modality_pixels.copy()
    view.applyVolumePreset('mr-mip');view.autoWindow();QTest.qWait(150)
    backend=view._host.backend
    valid=vtk_to_numpy(backend.mapper.GetMaskInput().GetPointData().GetScalars()).reshape(before.shape)>0
    np.testing.assert_array_equal(valid,np.isfinite(before))
    assert not backend._error
    shot=view.snapshot_image();assert not shot.isNull()
    assert shot.save(str(tmp_path/('mr-padding-'+polarity.lower()+'.png')))
    view.reset_all_view_state();QTest.qWait(100)
    assert backend.mapper.GetMaskInput() is not None and not backend._error
    np.testing.assert_array_equal(view.volume.modality_pixels,before)
    assert not warnings,warnings


@pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM')=='offscreen', reason='Native VTK requires a desktop surface')
def test_native_thin_mr_crop_mouse_gesture_and_reset(scene, sample_root, tmp_path):
    window, app, warnings = scene
    import_local(app, [sample_root/'Thin-3D-T1/DICOM'])
    ws = app.workspaceController
    record = next(iter(app.panelController._scan_series_record.values()))
    ws.createTab(record.series_instance_uid, 'MR crop', '3d')
    ready(ws)
    view = ws.activeViewport
    wait_until(lambda: view._host is not None, timeout=15000)
    QTest.qWait(200)
    original = view.volume.modality_pixels.copy()
    click(window, find(window, 'primaryTool-volume-crop'))
    click(window, find(window, 'volumeCrop-outside'))
    widget = view._host.vtk_widget
    points = [QPoint(round(widget.width()*x), round(widget.height()*y))
              for x, y in ((.42,.40), (.58,.40), (.58,.65), (.42,.65), (.42,.40))]
    QTest.mousePress(widget, Qt.LeftButton, pos=points[0])
    for point in points[1:]:
        QTest.mouseMove(widget, point, 20)
    QTest.mouseRelease(widget, Qt.LeftButton, pos=points[-1])
    wait_until(lambda: not view.editBusy and view.crop_mask is not None, timeout=15000)
    assert not view.editMessage, view.editMessage
    assert 0 < np.count_nonzero(view.crop_mask) < view.crop_mask.size
    np.testing.assert_array_equal(view.volume.modality_pixels, original)
    QTest.qWait(150)
    assert view.snapshot_image().save(str(tmp_path/'mr-crop-outside.png'))
    click(window, find(window, 'activeToolReset'))
    wait_until(lambda: view.crop_mask is None)
    QTest.qWait(150)
    assert view.snapshot_image().save(str(tmp_path/'mr-crop-reset.png'))
    np.testing.assert_array_equal(view.volume.modality_pixels, original)
    assert not view._host.backend._error
    assert not warnings, warnings
