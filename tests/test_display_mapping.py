"""Mapping changes display pixels only, including live/cache/restore paths."""
from dataclasses import replace
import numpy as np
import pytest
from qt_dicom_viewer.core.display_mapping import map_display
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.workspace_state import encode, decode
from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent, capabilities
from qt_dicom_viewer.model import PixelValueMeta, ToolType
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_ct_perfusion import perfusion, save_and_scan
from test_dicom_tags import qt_app, wait_until
from test_live_windowing import image_pixels, pause_worker, drain, begin_drag, move_drag
from test_pacs_qml import scene
from test_tag_qml import find, click, type_text
from manual.test_mr_samples import ready


@pytest.mark.parametrize('modality,meta,palette,hu,kind',[
    ('CT',PixelValueMeta(unit='HU'),False,True,'window'),
    ('MR',PixelValueMeta(unit='a.u.'),False,True,'window'),
    ('PT',PixelValueMeta(unit='SUVbw'),False,True,'range'),
    ('CT',PixelValueMeta(unit='ml/100ml/s'),True,False,'palette'),
    ('CT',PixelValueMeta(unit='mg/ml'),False,False,'range')])
def test_mapping_capabilities_follow_values_and_palette(modality,meta,palette,hu,kind):
    caps=capabilities(modality=modality,value_meta=meta,supplemental=palette,hu_analysis=hu)
    assert caps.kind==kind and caps.unit==meta.unit
    assert caps.presets == (modality=='CT' and hu)


@pytest.mark.parametrize('lower,upper',[(1,1),(2,1),(float('nan'),1),(0,float('inf')),(-1e308,1e308)])
def test_invalid_mapping_intents_rejected(lower,upper):
    with pytest.raises(ValueError): DisplayMappingIntent('custom',lower,upper,'HU')


def test_color_domain_custom_range_and_unit_mismatch(tmp_path):
    path,_=save_and_scan(tmp_path,perfusion())
    meta,raw=DicomLoader().read_frame(path,0)
    r=DicomLoader().load_dataset(meta,None,False,modality_pixels=raw)
    original=r.image.copy(); values=r.modality_pixel.copy()
    intent=DisplayMappingIntent('custom',3,20,r.pixel_value_meta.unit)
    actual=map_display(r.image,r.modality_pixel,r.pixel_value_meta,r.supplemental_overlay,r.source_palette,intent)
    mask=r.supplemental_overlay[...,3]!=0
    palette=np.array([[0,255,0],[255,0,0],[0,0,255]],np.uint8)
    indices=np.rint(np.clip((values-3)/17,0,1)*2).astype(int)
    np.testing.assert_array_equal(actual[mask],palette[indices[mask]])
    np.testing.assert_array_equal(actual[~mask],original[~mask])
    np.testing.assert_array_equal(r.modality_pixel,values)
    np.testing.assert_array_equal(r.image,original)
    fallback=map_display(r.image,values,r.pixel_value_meta,r.supplemental_overlay,r.source_palette,replace(intent,unit='HU'))
    np.testing.assert_array_equal(fallback,original)


def test_custom_range_grayscale_values_and_padding():
    values=np.array([[-1,0,1,np.nan]],np.float32)
    gray=np.array([[15,16,17,18]],np.uint8)
    mapped=map_display(gray,values,PixelValueMeta(unit='mg/ml'),intent=DisplayMappingIntent('custom',-1,1,'mg/ml'))
    np.testing.assert_array_equal(mapped,[[0,128,255,18]])
    assert np.isnan(values[0,-1])


@pytest.fixture
def app_with_perfusion(qt_app,tmp_path):
    path,snapshot=save_and_scan(tmp_path,perfusion())
    app=AppController(DicomImageProvider(),settings_path=tmp_path/'settings.json')
    app.panelController.update_series_session(snapshot);app.panelController._update_series_record(snapshot)
    try: yield app,snapshot
    finally:app.shutdown()


@pytest.mark.parametrize('mode',['2d','montage'])
def test_custom_mapping_live_worker_and_restore(app_with_perfusion,mode):
    app,snapshot=app_with_perfusion
    ws=app.workspaceController;ws.createTab(snapshot.series[0].series_instance_uid,'Mapping',mode)
    view=ws.activeViewport
    if mode=='2d':wait_until(lambda:view._frame_meta is not None)
    else:
        view.setVisibleRange(0,2)
        wait_until(lambda:len(view._display_frames)==3)
    pending=pause_worker(app)
    captured=[];view.imageUpdateRequested.connect(lambda key,image:captured.append(image.copy()))
    values=(view._modality_pixel if mode=='2d' else view._display_values[0]).copy()
    baseline=image_pixels(app._image_provider,view.viewportId if mode=='2d' else view.image_key(0))
    view.setDisplayMappingMode('custom');view.setDisplayRange(0,150)
    assert captured and pending
    if mode=='2d':
        assert view.overlayInfo['mappingMode']=='custom' and float(view.overlayInfo['mappingUpper'])==150
    state=decode(encode(view._state))
    assert state.display_mapping==DisplayMappingIntent('custom',0,150,'ml/100ml/s')
    before=(view._modality_pixel if mode=='2d' else view._display_values[0])
    np.testing.assert_array_equal(before,values)
    live=image_pixels(app._image_provider,view.viewportId if mode=='2d' else view.image_key(0))
    drain(app,pending)
    np.testing.assert_array_equal(image_pixels(app._image_provider,view.viewportId if mode=='2d' else view.image_key(0)),live)
    view.setDisplayMappingMode('source');drain(app,pending)
    np.testing.assert_array_equal(image_pixels(app._image_provider,view.viewportId if mode=='2d' else view.image_key(0)),baseline)
    view._state=state;view.request_render();drain(app,pending)
    np.testing.assert_array_equal(image_pixels(app._image_provider,view.viewportId if mode=='2d' else view.image_key(0)),live)
    view.reset_all_view_state();drain(app,pending)
    assert view.displayMapping['mode']=='source'
    np.testing.assert_array_equal(image_pixels(app._image_provider,view.viewportId if mode=='2d' else view.image_key(0)),baseline)


def test_source_palette_mouse_drag_is_explicit(app_with_perfusion):
    app,snapshot=app_with_perfusion;ws=app.workspaceController
    ws.createTab(snapshot.series[0].series_instance_uid,'Mapping','2d')
    view=ws.activeViewport;wait_until(lambda:view._frame_meta is not None)
    view.setViewportSize(512,512)
    view.beginInteraction(20,20,1,True,.37,.63,.001,.001)
    assert view._active_drag_operation is None
    view.setDisplayMappingMode('custom')
    begin_drag(view);move_drag(view,1);view.endInteraction(44,32,True,0,0)
    assert view._state.display_mapping.mode=='custom'


def test_mapping_ui_modes_and_gray_controls(scene,tmp_path):
    window,app,warnings=scene
    _,snapshot=save_and_scan(tmp_path,perfusion())
    app.panelController.update_series_session(snapshot);app.panelController._update_series_record(snapshot)
    app.workspaceController.createTab(snapshot.series[0].series_instance_uid,'Mapping','2d');ready(app.workspaceController)
    view=app.workspaceController.activeViewport
    panel=find(window,'displayMappingPanel')
    assert panel.isVisible()
    assert view.displayMapping['kind']=='palette'
    assert find(window,'mappingUnit').property('text').endswith('ml/100ml/s')
    click(window,find(window,'mappingCustom'))
    assert view.displayMapping['mode']=='custom'
    wait_until(lambda: view.loadState == 'ready')
    assert find(window, 'mappingLower').isEnabled()
    assert find(window, 'mappingUpper').isEnabled()
    before = (view.displayMapping['lower'], view.displayMapping['upper'])
    type_text(window, find(window, 'mappingLower'), '30')
    # An equivalent mapping notification from a completed render is not a new context.
    view.displayMappingChanged.emit()
    assert find(window, 'mappingLower').property('text') == '30'
    type_text(window, find(window, 'mappingUpper'), '100')
    assert (view.displayMapping['lower'], view.displayMapping['upper']) == before
    click(window, find(window, 'applyMappingRange'))
    assert (view.displayMapping['lower'], view.displayMapping['upper']) == (30, 100)
    wait_until(lambda: view.loadState == 'ready')
    assert find(window, 'mappingLower').isEnabled()
    type_text(window, find(window, 'mappingLower'), '70')
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(window, Qt.Key_Escape)
    assert find(window, 'mappingLower').property('text') == '30'
    assert find(window, 'mappingUpper').property('text') == '100'
    click(window,find(window,'mappingSource'))
    assert view.displayMapping['mode']=='source'
    click(window,find(window,'mappingBackground'))
    assert panel.property('backgroundExpanded')
    assert not warnings,warnings


def test_volume_transfer_capability_does_not_route_to_pet_slice_panel():
    for modality,unit in [('CT','HU'),('MR','a.u.'),('PT','SUVbw')]:
        caps=capabilities(modality=modality,value_meta=PixelValueMeta(unit=unit),volume=True)
        assert caps.kind=='transfer' and caps.unit==unit
        assert caps.fixed_lower is None and not caps.custom_range
