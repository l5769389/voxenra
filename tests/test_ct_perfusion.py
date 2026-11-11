"""Color-domain boundaries, physical measurements and live derived-CT browsing."""
import numpy as np
import pytest
from voxplane.core.ct_display import palette_lut
from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.enhanced_frames import frame_metadata
from voxplane.core.ct import ct_view_error
from voxplane.core.export_images import frame_image
from voxplane.core.series_sidebar import build_sidebar_rows
from voxplane.model import WindowLevel, TabType
from voxplane.ui.controller.tab.tool_controller import ToolController
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from test_enhanced_ct import enhanced_ct_dataset, save_and_scan, item
from test_dicom_tags import qt_app, wait_until


def perfusion():
    d = enhanced_ct_dataset()
    d.SharedFunctionalGroupsSequence[0].CTImageFrameTypeSequence[0].PixelPresentation = 'COLOR'
    for f in d.PerFrameFunctionalGroupsSequence:
        f.PixelValueTransformationSequence[0].RescaleType = 'US'
        f.RealWorldValueMappingSequence = [item(RealWorldValueSlope=.25, RealWorldValueIntercept=3,
            RealWorldValueFirstValueMapped=0, RealWorldValueLastValueMapped=2000,
            MeasurementUnitsCodeSequence=[item(CodeValue='ml/100ml/s', CodingSchemeDesignator='UCUM', CodeMeaning='flow')])]
    for c, values in zip(('Red','Green','Blue'), ([0,65535,0],[65535,0,0],[0,0,65535])):
        setattr(d, c+'PaletteColorLookupTableDescriptor', [3,30,16])
        setattr(d, c+'PaletteColorLookupTableData', np.array(values,dtype='<u2').tobytes())
    return d


def test_palette_uses_stored_domain_and_keeps_gray_voi(tmp_path):
    d = perfusion()
    path, snapshot = save_and_scan(tmp_path,d)
    meta, pixels = DicomLoader().read_frame(path,0)
    stored = d.pixel_array[0]
    window = WindowLevel(-1010,30)
    for inverted in (False,True):
        result = DicomLoader().load_dataset(meta,window,inverted,modality_pixels=pixels)
        assert result.pixel_value_meta.unit == 'ml/100ml/s'
        np.testing.assert_allclose(result.modality_pixel, stored*.25+3)
        mask = stored >= 30
        palette = np.array([[0,255,0],[255,0,0],[0,0,255]],np.uint8)
        np.testing.assert_array_equal(result.image[mask],palette[np.clip(stored[mask]-30,0,2)])
        gray = DicomLoader.apply_window(pixels,window,inverted)
        np.testing.assert_array_equal(result.image[~mask],np.repeat(gray[~mask,None],3,axis=1))
    image = frame_image(stored,d,0)
    assert image.pixelColor(6,3).getRgb()[:3] == (0,255,0) # stored=30
    for series in snapshot.series:
        assert not ct_view_error(series,'2d') and ct_view_error(series,'mpr')
    rows = [r for r in build_sidebar_rows(snapshot.series,'',set(),{} ) if r['kind']=='series']
    assert all('3' in str(r['countLabel']) and '1' in str(r['countLabel']) for r in rows)


def test_palette_validation_and_mapping_fallback():
    d = perfusion(); meta = frame_metadata(d,0)
    meta.GreenPaletteColorLookupTableDescriptor = [3,31,16]
    with pytest.raises(ValueError): palette_lut(meta)
    meta = frame_metadata(d,0)
    meta.RealWorldValueMappingSequence.append(item())
    values, units, _ = DicomLoader.to_display_values(meta,np.zeros((2,2),np.float32))
    assert units.unit=='a.u.' and units.warning
    np.testing.assert_array_equal(values,0)


def test_live_window_keeps_source_colors_and_disables_hu_tools(qt_app,tmp_path):
    path,snapshot = save_and_scan(tmp_path,perfusion())
    app = AppController(DicomImageProvider(),settings_path=tmp_path/'settings.json')
    try:
        app.panelController.update_series_session(snapshot); app.panelController._update_series_record(snapshot)
        uid = snapshot.series[0].series_instance_uid
        app.workspaceController.createTab(uid,'Perfusion','2d')
        view=app.workspaceController.activeViewport
        wait_until(lambda:view._frame_meta is not None)
        assert view._frame_meta.pixel_value_meta.unit=='ml/100ml/s'
        assert not view.supportsCtWindow and view.supportsGrayscaleWindow
        tools=app.workspaceController.activeTab.toolController
        assert not tools.windowPresets
        assert 'service' not in [t['toolType'] for t in tools.tools]
        images=[]; view.imageUpdateRequested.connect(lambda _,pixels:images.append(pixels.copy()))
        view.refresh_window_image()
        before=images[-1]; palette=view._frame_meta.supplemental_overlay
        view.toggleInverted()
        assert images
        np.testing.assert_array_equal(images[-1][palette[...,3]!=0],before[palette[...,3]!=0])
        for index in (2,0,1):
            view.setSliceIndex(index)
            wait_until(lambda:view._frame_meta.slice_index==index)
            assert view._frame_meta.supplemental_overlay is not None
    finally: app.shutdown()
