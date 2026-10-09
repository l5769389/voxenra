"""Isolated native UI fixture; drive interactions manually or through CUA.
VOXENRA_SPATIAL_UI is an output folder containing imports.json (path list).
The periodic state file is read-only evidence, not a control endpoint.
"""
import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtQml import QQmlApplicationEngine
from qt_dicom_viewer.app import configure_application_identity
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider

base=Path(os.environ['VOXENRA_SPATIAL_UI']).resolve();base.mkdir(parents=True,exist_ok=True)
started_at = datetime.now(timezone.utc).isoformat()
app=QApplication(sys.argv);configure_application_identity(app)
provider=DicomImageProvider()
ctrl=AppController(provider,settings_path=base/'settings.json',pacs_config_path=base/'pacs.json',pacs_import_root=base/'imports')
engine=QQmlApplicationEngine();engine.addImageProvider('dicom',provider)
engine.addImageProvider('navigation',SvgIconProvider());engine.rootContext().setContextProperty('appController',ctrl)
engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[2]/'src/qt_dicom_viewer/qml/Main.qml')))
engine.rootObjects()[0].setTitle('Voxenra — Spatial validation')

def state():
    ws=ctrl.workspaceController;v=ws.activeViewport
    info=dict(tab=ws.activeTabType,scanning=ctrl.panelController.scanning, startedAt=started_at)
    if v:
        info.update(viewport=v.viewportId,load=getattr(v,'loadState',None),slice=getattr(v,'sliceIndex',None))
        frame=getattr(v,'_frame_meta',None)
        if frame:
            info['frame']=repr(frame)
        source=getattr(v,'imageSource','');info['imageSource']=source
        data=getattr(v,'_modality_pixel',None)
        if data is not None:
            info['shape']=list(data.shape)
            info['pixels_sha256']=hashlib.sha256(data.tobytes()).hexdigest()
        for prop in ('zoom','rotationDegrees','horizontalFlip','verticalFlip','hasPhysicalSpacing'):
            info[prop]=getattr(v,prop,None)
        measurement=getattr(v,'measurementController',None)
        if measurement is not None:info['measurements']=measurement.measurementItems
        cursor=getattr(v,'cursorController',None)
        if cursor is not None:info['cursor']=cursor.cursorInfo
        tool=getattr(ws.activeTab,'toolController',None)
        if tool is not None:
            info['interaction']=tool.activeInteraction
    info['playing']=getattr(ws.activeTab,'playing',False)
    voi = getattr(ws.activeTab, '_voi_controller', None)
    if voi is not None:
        info['segmentation'] = dict(displayMode=voi.displayMode, fillOpacity=voi.fillOpacity,
            records=[dict(id=r['id'], name=str(r['name']), color=r['color'], visible=r['visible'],
                          mask_sha256=hashlib.sha256(r['mask'].tobytes()).hexdigest() if 'mask' in r else None,
                          metrics=voi.evaluations[r['id']].metrics if r['id'] in voi.evaluations else None)
                     for r in voi.records])
        history = getattr(ws.activeTab, '_edit_history', None)
        if history is not None:
            info['history'] = dict(undo=len(history._undo), redo=len(history._redo))
    (base/'state.json').write_text(json.dumps(info,default=str,indent=2))

QTimer.singleShot(500,lambda:ctrl.panelController.importUrls([QUrl.fromLocalFile(p) for p in json.loads((base/'imports.json').read_text())]))
timer=QTimer();timer.timeout.connect(state);timer.start(750)
app.aboutToQuit.connect(ctrl.shutdown)
app.exec()
