"""Native CPR acceptance fixture; interactions are performed in the real UI.

VOXENRA_CPR_UI selects an isolated output folder. state.json is observation only.
The generated DICOM series contains synthetic anatomy, no patient data.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from qt_dicom_viewer.app import configure_application_identity
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider

base = Path(os.environ['VOXENRA_CPR_UI']).resolve()
source = base/'synthetic-ct'
source.mkdir(parents=True, exist_ok=True)
uid = '1.2.826.0.1.3680043.10.999.20261029.88'
if not list(source.glob('*.dcm')):
    yy, xx = np.mgrid[:160, :160]
    for z in range(96):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = f'{uid}.{z+1}'
        ds = FileDataset(str(source/f'{z+1:03}.dcm'), {}, file_meta=meta, preamble=b'\0'*128)
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = uid+'.200', uid, uid+'.300'
        ds.Modality, ds.SeriesDescription, ds.StudyDescription = 'CT', 'CPR synthetic curved tubes', 'Native CPR validation'
        ds.PatientName, ds.PatientID, ds.StudyDate = 'CPR^PHANTOM', 'SYNTHETIC-CPR', '20261029'
        ds.ImageType, ds.InstanceNumber = ['ORIGINAL', 'PRIMARY', 'AXIAL'], z+1
        ds.Rows = ds.Columns = 160
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, 1
        ds.PixelSpacing, ds.SliceThickness = [.8, .8], 1.
        ds.ImagePositionPatient, ds.ImageOrientationPatient = [0, 0, z], [1, 0, 0, 0, 1, 0]
        ds.WindowCenter, ds.WindowWidth = 300, 1800
        ds.RescaleIntercept, ds.RescaleSlope, ds.BurnedInAnnotation = 0, 1, 'NO'
        body = ((xx-80)/65)**2 + ((yy-80)/58)**2 < 1
        pixels = np.where(body, 40+15*np.sin(xx/12), -900)
        for center in (80+23*np.sin((z-45)/24), 45+10*np.cos(z/22)):
            radius = np.hypot(xx-center, yy-80)
            pixels += np.where(body, 1350*np.exp(-.5*(radius/3)**2), 0)
        ds.PixelData = pixels.astype('<i2').tobytes()
        ds.save_as(source/f'{z+1:03}.dcm', enforce_file_format=True)

app = QApplication(sys.argv)
QAccessible.setActive(True)
configure_application_identity(app)
provider = DicomImageProvider()
controller = AppController(provider, settings_path=base/'settings.json',
    pacs_config_path=base/'pacs.json', pacs_import_root=base/'imports')
engine = QQmlApplicationEngine()
engine.addImageProvider('dicom', provider)
engine.addImageProvider('navigation', SvgIconProvider())
engine.rootContext().setContextProperty('appController', controller)
engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[2]/'src/qt_dicom_viewer/qml/Main.qml')))
window = engine.rootObjects()[0]
window.setTitle('Voxenra — CPR native validation')
window.resize(*(int(value) for value in os.environ.get('VOXENRA_CPR_WINDOW', '1280x720').split('x')))
window.show()
window.raise_()
window.requestActivate()

def observe():
    workspace = controller.workspaceController
    tab = workspace.activeTab
    document = controller.workspaceDocumentController
    info = dict(platform=app.platformName(), visible=window.isVisible(), active=window.isActive(),
                accessible=QAccessible.isActive(),
                dpr=window.devicePixelRatio(), title=window.title(),
                windowSize=[window.width(), window.height()],
                tab=workspace.activeTabType, tabIds=list(workspace._tab_dict),
                scanning=controller.panelController.scanning,
                document=dict(busy=document.busy, dirty=document.dirty, error=document.isError, message=str(document.message),
                              closedTabs=document.closedTabCount),
                export=dict(busy=controller.exportController.busy, message=str(controller.exportController.message)))
    if tab is not None and hasattr(tab, 'session_state'):
        info.update(session=tab.session_state(), ready=tab.ready, busy=tab.busy,
                    generation=tab._generation, message=str(tab.message), drawing=tab.drawing,
                    history=dict(undo=len(tab._edit_history._undo), redo=len(tab._edit_history._redo)),
                    activeRole=tab.activeViewport.viewportRole, focused=tab.focusedViewportId,
                    activePanel=tab.toolController.activePanel, interaction=tab.toolController.activeInteraction,
                    exportScope=tab.exportScope, views={})
        for view in tab.viewports_by_id.values():
            pixels = view._modality_pixel
            info['views'][view.viewportRole] = dict(
                state=repr(view.viewport_state), geometry=repr(view.plane_geometry),
                physicalOrigin=None if view.plane_geometry is None else view.plane_geometry.image_origin_patient,
                physicalOrientation=None if view.plane_geometry is None else view.plane_geometry.image_orientation_patient,
                pending=view.render_pending, historical=view.historicalPlane,
                hasPhysicalSpacing=view.hasPhysicalSpacing,
                pixels=None if pixels is None else hashlib.sha256(pixels.tobytes()).hexdigest(),
                measurements=view.measurementController.measurementItems,
                annotations=view.textAnnotationController.annotationItems,
                selectedAnnotation=view.textAnnotationController.selectedAnnotationId,
                sources={k:repr(v) for k,v in view.measurementController._sources.items()})
    temporary = base/'state.tmp'
    temporary.write_text(json.dumps(info, default=str, indent=2))
    temporary.replace(base/'state.json')

timer = QTimer()
timer.timeout.connect(observe)
timer.start(400)
app.aboutToQuit.connect(controller.shutdown)
app.exec()
