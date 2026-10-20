from pathlib import Path
import numpy as np
import pytest
from PySide6.QtCore import QUrl, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete
from pydicom.uid import CTImageStorage, generate_uid
from test_measurement_qml import qt_app, _visual_children, _scene
from test_mpr_voi_qml import _owner
from test_pet_2d import _pet_dataset, _write_dataset
from qt_dicom_viewer.core.dicom_scanner import _read_instance, _build_series_record
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from qt_dicom_viewer.core.volume_manager import VolumeManager
from PySide6.QtCore import QObject
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(params=[(.5, .5), (1., 1.), (2., 2.), (.5, 2.)])
def mpr_scene(qt_app,tmp_path,request):
    row_spacing, column_spacing=request.param
    study,series,reference=generate_uid(),generate_uid(),generate_uid()
    instances=[]
    for z in range(5):
        pixels=(np.add.outer(np.arange(64),np.arange(64))*10+z*100).astype(np.uint16)
        ds=_pet_dataset(pixels)
        ds.Modality='CT'; ds.SOPClassUID=CTImageStorage
        ds.file_meta.MediaStorageSOPClassUID=CTImageStorage
        ds.StudyInstanceUID=study; ds.SeriesInstanceUID=series; ds.FrameOfReferenceUID=reference
        ds.PixelSpacing=[row_spacing,column_spacing]; ds.ImagePositionPatient=[0,0,z*column_spacing]; ds.InstanceNumber=z+1
        instances.append(_read_instance(_write_dataset(ds,tmp_path/f'{z}.dcm')))
    record=_build_series_record(instances)
    catalog=SeriesCatalog(); catalog.update(DicomFolderScanSnapshot(tmp_path,5,5,0,[record]))
    host=QObject(); host._settings_controller=SettingsController(host,path=False)
    provider=DicomImageProvider(); workspace=WorkspaceController(catalog,provider,host)
    worker=DicomRenderWorker(catalog,VolumeManager()); failures=[]
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(failures.append)
    workspace.renderRequested.connect(worker.handleRenderRequest)
    workspace.createTab(series,'Synthetic audit','mpr')
    tab=workspace.activeTab
    view=QQuickView(); view.engine().addImageProvider('dicom',provider)
    view.engine().addImageProvider('navigation',SvgIconProvider())
    warnings=[]; view.engine().warnings.connect(lambda es:warnings.extend(e.toString() for e in es))
    view.setResizeMode(QQuickView.SizeRootObjectToView); view.resize(1280,800)
    view.setInitialProperties(dict(workspace=workspace,tabController=tab))
    view.setSource(QUrl.fromLocalFile(str(ROOT/'tests/qml/MprVoiWorkspace.qml')))
    assert view.status()==QQuickView.Ready
    view.show(); view.requestActivate(); QTest.qWait(150)
    try:
        vp=next(v for v in tab.viewports_by_id.values() if v.viewportType=='axial')
        layer=next(x for x in _visual_children(view.rootObject()) if x.objectName()=='dicomPixelLayer' and _owner(x) is vp)
        yield view, vp, layer, host._settings_controller
        assert not failures, failures
        assert not warnings, warnings
    finally:
        view.hide(); delete(view); workspace.shutdown()


def test_crosshair_hit_radius_is_stable_in_screen_pixels(mpr_scene, tmp_path):
    view, vp, layer, _ = mpr_scene
    center = vp._crosshair_image_position
    origin = _scene(layer, center.column, center.row)
    # Independent screen-space contract: center radius 8 px, line radius 6 px.
    for dx, dy, expected in [(4, 4, 'center'), (10, 10, ''),
                             (30, 4, 'horizontalLine'), (30, 8, ''),
                             (4, 30, 'verticalLine')]:
        QTest.mouseMove(view, origin + QPoint(dx, dy))
        QTest.qWait(30)
        assert vp.crosshairHoverTarget == expected
    vp.apply_zoom(1.5)
    vp.applyTransformAction('rotate:cw90')
    QTest.qWait(30)
    origin = _scene(layer, center.column, center.row)
    for dx, dy, expected in [(4, 4, 'center'), (10, 10, '')]:
        QTest.mouseMove(view, origin + QPoint(dx, dy))
        QTest.qWait(30)
        assert vp.crosshairHoverTarget == expected
    assert view.grabWindow().save(str(tmp_path / 'crosshair.png'))


def test_pixel_only_wheel_changes_actual_mpr_slice(mpr_scene, tmp_path):
    view, vp, layer, settings = mpr_scene
    p = _scene(layer, 30, 30)
    def wheel(angle, pixel):
        event = QWheelEvent(QPointF(p), QPointF(view.mapToGlobal(p)),
                           QPoint(0, pixel), QPoint(0, angle), Qt.NoButton,
                           Qt.NoModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(view, event)
        QTest.qWait(30)
    vp.apply_slice_index(2)
    wheel(0, -30)
    assert vp._state.slice_index == 2  # accumulate small touchpad movements
    wheel(0, -30)
    assert vp._state.slice_index == 3
    settings.setValue('input', 'reverseWheel', True)
    wheel(0, -60)
    assert vp._state.slice_index == 2
    wheel(-120, -60)  # an event with both units counts once
    assert vp._state.slice_index == 1
    assert view.grabWindow().save(str(tmp_path / 'pixel-wheel.png'))
