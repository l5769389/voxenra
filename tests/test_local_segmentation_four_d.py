"""Automatic results return to the captured phase of a real, scanned 4D tab."""
import numpy as np
from test_four_d_tools import temporal
from test_dicom_tags import qt_app
from qt_dicom_viewer.ui.controller.local_segmentation_controller import LocalSegmentationController
from qt_dicom_viewer.core.segmentation_masks import mask_record


def test_automatic_masks_wait_for_original_four_d_phase(temporal,tmp_path):
    tab,requests,(_,workspace)=temporal
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    settings=SettingsController(path=False)
    c=LocalSegmentationController(settings,workspace._series_catalog,cache=tmp_path/'jobs')
    try:
        assert c.prepare(tab),c.message
        volume=c._target[2]
        mask=np.zeros(volume.modality_pixels.shape,bool);mask[0,0,0]=True
        r,e=mask_record(volume,mask,(0,0,0),name='liver',phase=0)
        c._pending=([r],{r['id']:e},[]);c._state='pending'
        tab.setPhaseIndex(1)
        c._poll_target()
        assert c.state=='pending' and not tab.voiController.records
        tab.setPhaseIndex(0)
        before=[view.sliceIndex for view in tab.viewports_by_id.values()]
        c._poll_target()
        assert c.state=='done' and tab.voiController.records[0]['phase']==0
        assert [view.sliceIndex for view in tab.viewports_by_id.values()]==before
        tab.setPhaseIndex(1)
        assert not tab.voiController.items and not tab.activeViewport.voiMasks
        tab.setPhaseIndex(0)
        assert tab.voiController.records[0]['id']==r['id']
    finally:
        c.shutdown()
