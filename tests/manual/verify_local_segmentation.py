"""Isolated native CT fixture for local inference; UI can be driven through CUA.
Usage: python tests/manual/verify_local_segmentation.py SOURCE OUTPUT [--run]
--interactive leaves inference, editing and saving entirely to the visible UI.
No network data transfer; original DICOMs and user settings remain untouched.
"""
import json
import hashlib
from pathlib import Path
import sys
import time
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.core.workspace_state import dumps,loads
from qt_dicom_viewer.core.nrrd_exchange import write_nrrd,write_segmentation,read_segmentation
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
source=Path(sys.argv[1]);output=Path(sys.argv[2]).resolve();output.mkdir(parents=True,exist_ok=True)
qt=QApplication(['Voxenra Local Segmentation QA']);qt.setApplicationName('Voxenra Local Segmentation QA')
provider=DicomImageProvider()
app=AppController(provider,settings_path=output/'settings.json',pacs_config_path=output/'pacs.json',pacs_import_root=output/'imports')
app.workspaceDocumentController.setAutomaticRecovery(False)
app.settingsController.setValue('updates','enabled',False)
app.settingsController.setValue('privacy','hideIdentity',True)
app.settingsController.setValue('appearance','theme','graphite')
app.settingsController.setValue('layout','rightPanelWidth',240 if '--small' in sys.argv else 300)
engine=QQmlApplicationEngine();engine.addImageProvider('dicom',provider);engine.addImageProvider('navigation',SvgIconProvider())
engine.rootContext().setContextProperty('appController',app)
warnings=[]
engine.warnings.connect(lambda items:warnings.extend(i.toString() for i in items))
engine.load(QUrl.fromLocalFile(str(ROOT/'src/qt_dicom_viewer/qml/Main.qml')))
window=engine.rootObjects()[0];window.resize(1280 if '--small' in sys.argv else 1440,720 if '--small' in sys.argv else 900);window.show()
if '--empty' in sys.argv:
    pass
elif '--restore' in sys.argv:
    app.workspaceDocumentController.restore_from(source)
else:
    snapshot=list(DicomFolderScanner().scan_files(list(source.rglob('*.dcm')),folder=source))[-1]
    series=max(snapshot.series,key=lambda s:len(s.instances))
    app.panelController.update_series_session(snapshot);app.panelController._update_series_record(snapshot)
    app.workspaceController.createTab(series.series_instance_uid,'Local CT segmentation','mpr')
c=app.localSegmentationController
begun=False;computed=False;started=time.monotonic()

last_capture=None
capture_number=0

def interactive_snapshot():
    """Read-only evidence collection; no UI commands or product mutations."""
    global last_capture,capture_number
    tabs=[tab for tab in app.workspaceController._tab_dict.values() if hasattr(tab,'voiController')]
    tab=tabs[0] if tabs else None
    voi=tab.voiController if tab else None
    records=voi.records if voi else []
    signature=tuple((r['id'], id(r.get('mask')),r.get('name'),r.get('color'),
                     r.get('visible'),tuple(r.get('mask_offset',()))) for r in records)
    if signature!=last_capture:
        last_capture=signature;capture_number+=1
        data=dumps({'voi':records})
        (output/f'capture-{capture_number:03d}.json').write_bytes(data)
        (output/'current-records.json').write_bytes(data)
        masks=[]
        for r in records:
            mask=r.get('mask')
            masks.append(dict(id=r['id'],name=r.get('name'),color=r.get('color'),
                offset=r.get('mask_offset'),shape=list(mask.shape) if mask is not None else None,
                count=int(np.count_nonzero(mask)) if mask is not None else None,
                sha256=hashlib.sha256(mask.tobytes()).hexdigest() if mask is not None else None,
                metadata=r.get('automatic_segmentation')))
        with (output/'history.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(capture=capture_number,elapsed=time.monotonic()-started,masks=masks),ensure_ascii=False)+'\n')
    doc=app.workspaceDocumentController
    state=dict(state=c.state,message=c.message,environment=c.environment,
        environment_state=c.environmentState,environment_message=c.environmentMessage,
        settings=app.settingsController.values['services'],capture=capture_number,
        workspace=dict(path=doc.path,dirty=doc.dirty,busy=doc.busy,restoring=doc.restoring,
                       missing=doc.hasMissingSources,message=doc.message),
        tool=tab.toolController.activeTool if tab else None,
        edit_mode=voi.editMode if voi else None,diameter=voi.brushDiameter if voi else None,
        selected=voi.selectedId if voi else None,
        draft=bool(voi._draft) if voi else False,
        counts={r['name']:voi.evaluations[r['id']].metrics['count'] for r in records if r['id'] in voi.evaluations},
        warnings=warnings,elapsed=round(time.monotonic()-started,1))
    (output/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))


def poll():
    global begun,computed
    if "--interactive" in sys.argv:
        interactive_snapshot();return
    tab=app.workspaceController.activeTab
    if tab is None or not hasattr(tab,"voiController"):return
    voi=tab.voiController
    if not begun and voi.sources and all(getattr(v,'_plane_geometry',None) for v in tab.viewports_by_id.values()):
        begun=True
        tab.toolController.activateTool('segmentation')
        c.prepare(tab)
        if '--run' in sys.argv:c.checkEnvironment()
    if '--run' in sys.argv and begun and c.state=='ready' and not computed:
        computed=True;c.start()
    state=dict(state=c.state,message=c.message,environment=c.environment,
        counts={r['name']:voi.evaluations[r['id']].metrics['count'] for r in voi.records if r['id'] in voi.evaluations},
        warnings=warnings,elapsed=round(time.monotonic()-started,1))
    (output/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
    if '--restore' in sys.argv and not (output/'restored.json').exists() and voi.records and voi.sources and not app.workspaceDocumentController.busy:
        original=loads((source.parent/'records.json').read_bytes())['voi']
        assert len(original)==len(voi.records)
        assert all(np.array_equal(a['mask'],b['mask']) and a['mask_offset']==b['mask_offset'] and a['automatic_segmentation']==b['automatic_segmentation'] for a,b in zip(original,voi.records))
        (output/'restored.json').write_text(json.dumps(dict(masks_equal=True,metadata_equal=True,segments=len(original),inference_started=computed)))
    if c.state=='done' and not (output/'verification.json').exists():
        volume=next(iter(voi.sources.values()))
        data=dumps({'voi':voi.records});(output/'records.json').write_bytes(data)
        restored=loads(data)['voi']
        assert all(np.array_equal(a['mask'],b['mask']) for a,b in zip(voi.records,restored))
        from PySide6.QtGui import QColor
        expected=dict(pixels=volume.modality_pixels,affine=volume.geometry.voxel_to_patient,
            organs=np.array([r['automatic_segmentation']['organ'] for r in voi.records]))
        for i,record in enumerate(voi.records):
            full=np.zeros(volume.modality_pixels.shape,bool)
            full[tuple(slice(o,o+n) for o,n in zip(record['mask_offset'],record['mask'].shape))]=record['mask']
            expected[f'mask{i}']=full;expected[f'name{i}']=record['name']
            expected[f'color{i}']=QColor(record['color']).getRgbF()[:3]
        np.savez_compressed(output/'expected.npz',**expected)
        write_nrrd(output/'source.nrrd',volume.modality_pixels,volume.geometry.voxel_to_patient)
        write_segmentation(output/'segmentation.seg.nrrd',volume,voi.records,voi.evaluations)
        imported,_=read_segmentation(output/'segmentation.seg.nrrd',volume)
        assert all(np.array_equal(a['mask'],b['mask']) and a['mask_offset']==b['mask_offset'] for a,b in zip(voi.records,imported))
        (output/'verification.json').write_text(json.dumps(dict(workspace_mask_roundtrip=True,nrrd_roundtrip=True,segments=len(restored)),indent=2))
        app.workspaceDocumentController.save_to(output/'automatic.voxworkspace')
        print('LOCAL_SEGMENTATION_VERIFIED',state,flush=True)

clock=QTimer();clock.timeout.connect(poll);clock.start(300)
qt.aboutToQuit.connect(app.shutdown)
qt.exec()
