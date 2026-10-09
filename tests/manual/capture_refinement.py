"""Render anonymous refinement examples with the real QML UI, offscreen.

Pass a local manifest containing source_paths; source files remain read-only.
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software PYTHONPATH=src:tests \
  python tests/manual/capture_refinement.py MANIFEST OUTPUT
"""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from i18n_support import install_default_language
from test_dicom_tags import wait_until
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider

ROOT = Path(__file__).resolve().parents[2]
qt = QApplication(["capture", "-platform", "offscreen:configfile=tests/qt-offscreen-desktop.json"])
install_default_language(qt)
output = Path(sys.argv[2]); output.mkdir(parents=True, exist_ok=True)
paths = list(map(Path, json.loads(Path(sys.argv[1]).read_text())['source_paths']))
snapshot = list(DicomFolderScanner().scan_files(paths, folder=paths[0].parent))[-1]
fields = dict(patient_name='MR Demo', patient_id='Anonymous', study_description='',
              study_date='', study_time='', series_description='3D T1')
records = [replace(r, **fields, instances=tuple(replace(i, **fields) for i in r.instances))
           for r in snapshot.series]
snapshot = replace(snapshot, series=records)
with TemporaryDirectory(prefix='voxenra-refinement-capture-') as temp:
    provider = DicomImageProvider()
    app = AppController(provider, settings_path=Path(temp)/'settings.json',
                        pacs_config_path=Path(temp)/'pacs.json', pacs_import_root=Path(temp)/'imports')
    app.workspaceDocumentController.setAutomaticRecovery(False)
    english = '--english' in sys.argv
    app.languageController.selectLanguage('en-US' if english else 'zh-CN')
    for group,key,value in [('appearance','theme','graphite'),('layout','rightPanelWidth',310),
                           ('layout','rightPanelCollapsed',False),
                           ('corners','topLeft',['viewPosition','seriesDescription','slice']),
                           ('corners','topRight',[]),('corners','bottomRight',['transform'])]:
        app.settingsController.setValue(group,key,value)
    engine = QQmlApplicationEngine()
    engine.addImageProvider('dicom',provider); engine.addImageProvider('navigation',SvgIconProvider())
    engine.rootContext().setContextProperty('appController',app)
    warnings=[]
    engine.warnings.connect(lambda items: warnings.extend(i.toString() for i in items))
    engine.load(QUrl.fromLocalFile(str(ROOT/'src/qt_dicom_viewer/qml/Main.qml')))
    window=engine.rootObjects()[0]; window.resize(1440,900); window.show()
    frames=[]
    def shot(name=None):
        QTest.qWait(220)
        picture=window.grabWindow(); assert not picture.isNull()
        if name: assert picture.save(str(output/(name+'.png')))
        buffer=QBuffer(); buffer.open(QIODevice.WriteOnly); picture.save(buffer,'PNG')
        image=Image.open(BytesIO(bytes(buffer.data()))).convert('RGB')
        image.thumbnail((1100,688),Image.Resampling.LANCZOS); frames.append(image)
    try:
        app.panelController.update_series_session(snapshot); app.panelController._update_series_record(snapshot)
        record=max(records,key=lambda r:len(r.instances))
        app.panelController.selectSeries(record.series_instance_uid)
        app.workspaceController.createTab(record.series_instance_uid,
                                         'MR · Refinement' if english else 'MR · 分割精修','mpr')
        tab=app.workspaceController.activeTab
        wait_until(lambda: bool(tab.voiController.sources) and all(v._plane_geometry for v in tab.viewports_by_id.values()),timeout=30000)
        tab.mprLayout.setLayout('left')
        view=next(v for v in tab.viewports_by_id.values() if v.viewportType=='axial')
        tab.activateViewport(view.viewportId); tab.toolController.activateTool('segmentation')
        c=tab.voiController; g=view._plane_geometry
        cx,cy=g.columns*.5,g.rows*.48
        c.newSegment(); c.rename('Region 1' if english else '区域 1')
        c.setBrushDiameter(18); c.setBrushSphere(True)
        shot()
        c.begin(view,cx-12,cy,.1)
        for dx,dy in [(-8,-2),(-4,-4),(0,-4),(4,-2),(8,0)]:
            c.update(view,cx+dx,cy+dy); shot()
        c.finish(view,cx+8,cy); c.rename('Region 1' if english else '区域 1'); tab.historyController.capture(); shot()
        c.setEditMode('erase'); c.setBrushDiameter(8)
        c.begin(view,cx,cy,.1); c.update(view,cx+3,cy+3); shot()
        c.finish(view,cx+3,cy+3); tab.historyController.capture(); shot()
        tab.historyController.undo(); shot(); tab.historyController.redo(); shot()
        c.newSegment(); c.setBrushDiameter(12)
        c.begin(view,cx+18,cy+8,.1); c.finish(view,cx+18,cy+14); c.rename('Region 2' if english else '区域 2')
        wait_until(lambda:not c.busy)
        assert len(c.records)==2 and len({r['color'] for r in c.records})==2
        shot('38-segmentation-refinement'); shot('34-segment-management')
        # Retain the rendered steps; all frames come from actual application state.
        swatches=Image.new('RGB',(160*len(frames),100))
        for i,im in enumerate(frames): swatches.paste(im.resize((160,100)),(160*i,0))
        palette=swatches.quantize(colors=224)
        indexed=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in frames]
        indexed[0].save(output/'38-segmentation-refinement.gif',save_all=True,
                        append_images=indexed[1:],duration=[1000]+[250]*5+[900]*6+[1800]*2,loop=0,disposal=2)
        tab.toolController.activateTool('import'); shot('33-associated-import')
        tab.toolController.activateTool('export'); shot('32-structured-report')
        assert not warnings,warnings
        print('Captured refinement, import and export; no QML warnings',flush=True)
    finally:
        window.hide(); app.shutdown(); delete(engine)
