"""Opt-in native checks of display mapping on the user's existing sample library."""
import os
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtTest import QTest
from voxplane.model import WindowLevel
from test_dicom_tags import qt_app,wait_until
from test_pacs_qml import scene
from test_tag_qml import find,click
from manual.test_mr_samples import import_local,ready
from test_live_windowing import image_pixels

pytestmark=pytest.mark.skipif(os.getenv('QT_QPA_PLATFORM')=='offscreen',reason='Native views and captures')

@pytest.fixture
def library():
    root=os.getenv('VOXPLANE_TEST_DICOM_DIR')
    if not root:pytest.skip('Set VOXPLANE_TEST_DICOM_DIR to the existing sample library')
    assert Path(root).is_dir()
    return Path(root)


def test_real_perfusion_custom_mapping_restore_and_montage(scene,library,tmp_path):
    window,app,warnings=scene
    import_local(app,[library/'VoxPlane-EnhancedCT-TestData/pydicom/eCT_Supplemental.dcm'])
    series=next(iter(app.panelController._scan_series_record.values()))
    ws=app.workspaceController;window.resize(1400,900)
    ws.createTab(series.series_instance_uid,'RCBF display mapping','2d');ready(ws)
    v=ws.activeViewport;original=image_pixels(app._image_provider,v.viewportId)
    pixels=v._modality_pixel.copy()
    assert v.displayMapping['lower']==0 and v.displayMapping['upper']==99
    click(window,find(window,'mappingCustom'))
    v.setDisplayRange(10,70)
    wait_until(lambda:not app.render_service._active and not app.render_service._pending)
    custom=image_pixels(app._image_provider,v.viewportId)
    assert np.any(custom!=original)
    np.testing.assert_array_equal(v._modality_pixel,pixels)
    mask=v._frame_meta.supplemental_overlay[...,3]!=0
    np.testing.assert_array_equal(custom[~mask],original[~mask])
    for i in (1,0):
        v.setSliceIndex(i);wait_until(lambda:v._frame_meta.slice_index==i)
        assert v.displayMapping['mode']=='custom' and v.displayMapping['upper']==70
    QTest.qWait(120)
    assert window.grabWindow().save(str(tmp_path/'display-mapping-perfusion-custom.png'))
    click(window,find(window,'mappingSource'))
    wait_until(lambda:not app.render_service._active and not app.render_service._pending)
    np.testing.assert_array_equal(image_pixels(app._image_provider,v.viewportId),original)
    QTest.qWait(120)
    assert window.grabWindow().save(str(tmp_path/'display-mapping-perfusion-source.png'))
    ws.createTab(series.series_instance_uid,'RCBF montage','montage')
    wait_until(lambda:len(ws.activeViewport._display_values)==2)
    m=ws.activeViewport;m.setDisplayMappingMode('custom');m.setDisplayRange(10,70)
    wait_until(lambda:not app.render_service._active and not app.render_service._pending)
    assert all(f.source_palette.unit=='ml/100ml/s' for f in m._display_frames.values())
    np.testing.assert_array_equal(image_pixels(app._image_provider,m.image_key(0)),custom)
    QTest.qWait(120)
    assert window.grabWindow().save(str(tmp_path/'display-mapping-perfusion-montage.png'))
    assert not warnings,warnings


def test_real_pet_ct_stack_mpr_fusion_and_volume(scene,library,tmp_path):
    window,app,warnings=scene
    import_local(app,[library/'PET-CT--L']);ws=app.workspaceController
    records=list(app.panelController._scan_series_record.values())
    ct=next(s for s in records if s.modality=='CT')
    pet=next(s for s in records if s.modality=='PT')
    window.resize(1400,900)
    ws.createTab(ct.series_instance_uid,'CT','2d');ready(ws)
    v=ws.activeViewport;source=v._modality_pixel.copy()
    assert v.displayMapping['kind']=='window' and v.displayMapping['unit']=='HU'
    v.applyWindowPreset(50,200);v.toggleInverted();QTest.qWait(100)
    np.testing.assert_array_equal(v._modality_pixel,source)
    ws.createTab(ct.series_instance_uid,'CT MPR','mpr');ready(ws)
    assert all(v.displayMapping['kind']=='window' for v in ws.activeTab.viewports_by_id.values())
    ws.createTab(pet.series_instance_uid,'PET','2d');ready(ws)
    v=ws.activeViewport
    for i in (0,len(pet.instances)//2,len(pet.instances)-1):
        v.setSliceIndex(i);wait_until(lambda:v._frame_meta.slice_index==i)
    old=v._modality_pixel.copy();old_meta=v._frame_meta.pixel_value_meta
    assert v.displayMapping['kind']=='range' and v.displayMapping['fixedLower']
    v.setPetDisplayUpper(v.petDisplayUpper*.7)
    wait_until(lambda:not app.render_service._active and not app.render_service._pending)
    np.testing.assert_array_equal(v._modality_pixel,old)
    options=[o for o in old_meta.unit_options if o.available and o.unit_id!=old_meta.unit_id]
    assert options,'Sample should offer Bq/ml and kBq/ml'
    upper=v.petDisplayUpper;option=options[0]
    v.setPetUnit(option.unit_id)
    wait_until(lambda:v._frame_meta.pixel_value_meta.unit_id==option.unit_id)
    ratio=option.scale_from_source/old_meta.scale_from_source
    assert v.petDisplayUpper==pytest.approx(upper*ratio)
    np.testing.assert_allclose(v._modality_pixel,old*ratio,rtol=2e-6,atol=.001)
    for fusion in (False,True):
        if fusion:ws.createFusionTab(ct.series_instance_uid,pet.series_instance_uid)
        else:ws.createTab(pet.series_instance_uid,'PET MPR','mpr')
        tab=ws.activeTab;wait_until(lambda:tab.ready,timeout=30000)
        state=tab.pet_display.visible
        tab.pet_display.set_upper(state.upper*.8)
        wait_until(lambda:tab.ready and not app.render_service._active and not app.render_service._pending,timeout=30000)
        assert tab.pet_display.visible.upper==pytest.approx(state.upper*.8)
        assert all(v._modality_pixel is not None for v in tab.viewports_by_id.values())
    fusion_tab=ws.activeTab
    ws.createTab(pet.series_instance_uid,'PET 3D','3d');ready(ws)
    v=ws.activeViewport;wait_until(lambda:v._host is not None,timeout=15000)
    source=v.volume.modality_pixels.copy();v.setPetUpper(v.petUpper*.8);QTest.qWait(180)
    np.testing.assert_array_equal(v.volume.modality_pixels,source)
    assert not v.snapshot_image().isNull()
    ws.createFusionVolumeTab(fusion_tab);ready(ws)
    v=ws.activeViewport;wait_until(lambda:v._host is not None,timeout=15000)
    QTest.qWait(180);assert not v.snapshot_image().isNull()
    assert not warnings,warnings


def test_real_ct_four_d_display_and_phase_switch(scene,library):
    window,app,warnings=scene
    import_local(app,[library/'P113_dicom/MP1']);ws=app.workspaceController
    series=next(s for s in app.panelController._scan_series_record.values() if s.supports_four_d)
    ws.createTab(series.series_instance_uid,'CT 4D','4d');ready(ws)
    tab=ws.activeTab;v=ws.activeViewport
    assert v.displayMapping['kind']=='window'
    v.applyWindowPreset(45,350)
    tab.setPhaseIndex(1)
    wait_until(lambda:tab._current_phase_index==1 and ws.activeLoadState.status=='ready',timeout=30000)
    assert all(v.current_window==WindowLevel(45,350) for v in tab.viewports_by_id.values())
    assert not warnings,warnings
