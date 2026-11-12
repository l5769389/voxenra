"""Run with PYTHONPATH=<git archive v2.5.0>/src; no current product imports."""
from dataclasses import replace
from pathlib import Path
import time
import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian
from PySide6.QtWidgets import QApplication
import qt_dicom_viewer
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.model import MeasurementKind, PointerPosition, Point, ImagePoint, DragUpdateEvent, Offset

assert qt_dicom_viewer.__version__ == '2.5.0'
root = Path(__file__).resolve().parent
qapp = QApplication([])
def wait(condition):
    deadline = time.monotonic() + 30
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert condition(), 'Timed out'

pixels = np.full((128, 128), -1000, np.int16)
y, x = np.indices(pixels.shape)
pixels[(x-64)**2+(y-64)**2 <= 45**2] = 7
image_dir = root/'images'
image_dir.mkdir(exist_ok=True)
for z in range(3):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = f'1.2.826.0.1.3680043.10.999.250.{z+1}'
    ds = FileDataset(None, {}, file_meta=meta, preamble=bytes(128))
    ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = '1.2.826.0.1.3680043.10.999.250.100'
    ds.SeriesInstanceUID = '1.2.826.0.1.3680043.10.999.250.200'
    ds.FrameOfReferenceUID = '1.2.826.0.1.3680043.10.999.250.300'
    ds.PatientName, ds.PatientID = 'SYNTHETIC^UPGRADE', 'SYNTHETIC-UPGRADE-250'
    ds.Modality, ds.SeriesDescription = 'CT', 'Synthetic upgrade phantom'
    ds.SeriesNumber, ds.InstanceNumber = 1, z+1
    ds.Rows = ds.Columns = 128
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16,16,15,1
    ds.PixelSpacing, ds.SliceThickness = [1,1], 2
    ds.ImagePositionPatient, ds.ImageOrientationPatient = [0,0,z*2], [1,0,0,0,1,0]
    ds.RescaleSlope, ds.RescaleIntercept = 1,0
    ds.WindowCenter, ds.WindowWidth = 40,400
    ds.PixelData = pixels.tobytes()
    ds.save_as(image_dir/f'{z+1}.dcm', enforce_file_format=True)

app = AppController(DicomImageProvider(), settings_path=False)
try:
    snapshot = list(DicomFolderScanner().scan(image_dir))[-1]
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    ws = app.workspaceController
    ws.createTab(snapshot.series[0].series_instance_uid, 'Synthetic CT', '2d')
    wait(lambda: ws.activeViewport.loadState == 'ready')
    view = ws.activeViewport
    view._state = replace(view._state, zoom=1.5, pan_x=4.25, rotation_degrees=90.)
    measure = view.measurementController
    start = PointerPosition(viewport=Point(40,64), image=ImagePoint(40,64))
    end = PointerPosition(viewport=Point(50,64), image=ImagePoint(50,64))
    measure.begin(start, view._measurement_context(3,2,kind=MeasurementKind.LENGTH))
    measure.update(DragUpdateEvent(start,end,Offset(10,0),Offset(10,0)))
    measure.end(end)
    assert len(measure.measurementItems) == 1
    view.qaController.setRoiDiameterMm(10.)
    view.qaController.setEdgeClearanceMm(5.)
    ws.activeTab.toolController.selectService('service:qa')
    wait(lambda: view.qaController.status != 'calculating')
    assert view.qaController.status == 'ready', view.qaController.error
    assert view.qaController.currentResult['water_ct_hu'] == 7
    ws.createTab(snapshot.series[0].series_instance_uid, 'Synthetic CPR', 'cpr')
    tab = ws.activeTab
    wait(lambda: tab.referencesReady)
    ref = tab.viewForRole('reference-a')
    tab.startPath()
    for x,y in ((40,64),(50,64),(60,64)):
        assert ref.cprTap(x,y,.4)
    assert tab.finishPath()
    wait(lambda: tab.ready)
    tab.setParameter('step', 2.)
    wait(lambda: tab.ready)
    manager = app.workspaceDocumentController
    assert manager.save_to(root/'workspace.voxworkspace')
    wait(lambda: not manager.busy)
    assert not manager.isError, manager.message
    print('Saved using', qt_dicom_viewer.__file__)
    print('QA', view.qaController.currentResult)
    print('CPR', tab.session_state())
finally:
    app.shutdown()
