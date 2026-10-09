"""Subprocess probe of saved source frame and physical measurement identity."""
import json
import sys
import time
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.model import MeasurementKind
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_measurement_controller import _position, _drag


def wait(condition):
    deadline=time.monotonic()+30
    while not condition():
        QApplication.processEvents();time.sleep(.005)
        if time.monotonic()>deadline:raise TimeoutError('Workspace/frame restore did not settle')


def main():
    mode,folder=sys.argv[1:];root=Path(folder);qt=QApplication([])
    app=AppController(DicomImageProvider(),settings_path=root/'restart-settings.json')
    ws=app.workspaceController;document=app.workspaceDocumentController;path=root/'session.voxworkspace'
    try:
        if mode=='write':
            series=list(DicomFolderScanner().scan_files(list(root.glob('*.dcm')),folder=root))[-1]
            app.panelController.update_series_session(series);app.panelController._update_series_record(series)
            record=series.series[-1];ws.createTab(record.series_instance_uid,'Audit','2d')
            wait(lambda:ws.activeViewport is not None and ws.activeViewport.loadState=='ready')
            view=ws.activeViewport;view.setSliceIndex(4)
            wait(lambda:view._frame_meta.slice_index==4)
            controller=view._measure_controller
            context=view._measurement_context(.1,.1,kind=MeasurementKind.LENGTH)
            a,b=_position(.5,1.5),_position(10.5,9.5)
            controller.begin(a,context);controller.update(_drag(a,b));controller.end(b)
            expected=float(np.hypot(10*.5,8*.7))
            measurement=next(iter(controller._measurements.values()))
            np.testing.assert_allclose(measurement.length_mm,expected,rtol=1e-6,atol=1e-4)
            frame=view._frame_meta.instance_meta
            evidence=dict(length=expected,sop=frame.sop_instance_uid,frame=frame.frame_index,slice=4)
            (root/'restart-expected.json').write_text(json.dumps(evidence))
            np.save(root/'restart-pixels.npy',view._modality_pixel)
            assert document.save_to(path);wait(lambda:not document.busy)
            assert not document.isError,document.message
        else:
            assert document.restore_from(path);wait(lambda:not document.busy)
            assert not document.isError,document.message
            wait(lambda:ws.activeViewport is not None and ws.activeViewport.loadState=='ready')
            view=ws.activeViewport;expected=json.loads((root/'restart-expected.json').read_text())
            frame=view._frame_meta.instance_meta
            assert view.sliceIndex==expected['slice']
            assert frame.sop_instance_uid==expected['sop'] and frame.frame_index==expected['frame']
            measurement=next(iter(view._measure_controller._measurements.values()))
            np.testing.assert_allclose(measurement.length_mm,expected['length'],atol=1e-4,rtol=1e-6)
            np.testing.assert_array_equal(view._modality_pixel,np.load(root/'restart-pixels.npy'))
            (root/'restart-result.json').write_text(json.dumps(dict(status='pass',source_frame=True,pixels=True,length=True)))
    finally:app.shutdown()

if __name__=='__main__':main()
