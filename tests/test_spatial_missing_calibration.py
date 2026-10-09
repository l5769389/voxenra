"""Display-only fallback grids must never become fabricated millimetres."""
import pytest
from PySide6.QtTest import QTest
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.model import MeasurementKind
from spatial_audit.cases import CASES, generate
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find


@pytest.mark.parametrize('name',['invalid-missing-spacing','invalid-zero-spacing','invalid-nan-spacing'])
def test_uncalibrated_grayscale_cannot_create_physical_measurement(scene,tmp_path,name):
    window,app,warnings=scene
    generate(tmp_path,next(c for c in CASES if c.name==name))
    snapshot=list(DicomFolderScanner().scan_files(list(tmp_path.glob('*.dcm')),folder=tmp_path))[-1]
    panel=app.panelController;panel.update_series_session(snapshot);panel._update_series_record(snapshot)
    ws=app.workspaceController;ws.createTab(snapshot.series[0].series_instance_uid,'Uncalibrated','2d')
    wait_until(lambda:ws.activeViewport and ws.activeViewport.loadState=='ready')
    view=ws.activeViewport
    assert not view.hasPhysicalSpacing
    # The 1x1 grid is only for displaying source pixels, never a calibration.
    for kind in [MeasurementKind.LENGTH,MeasurementKind.ANGLE,MeasurementKind.RECT,MeasurementKind.ELLIPSE,MeasurementKind.FREEHAND,MeasurementKind.CURVE]:
        assert view._measurement_context(2,2,kind=kind) is None
    ws.activeTab.toolController.activateTool('measure');QTest.qWait(100)
    for kind in ['length','angle','rect','ellipse','freehand','curve']:
        assert not find(window,'measureEntry-'+kind).isEnabled()
    assert find(window,'measurementCalibrationWarning').isVisible()
    assert not warnings,warnings

    if name=='invalid-missing-spacing':
        view.applyWindowPreset(-980,400)
        import os
        from pathlib import Path
        for language,theme in [('en-US','light'),('zh-CN','graphite')]:
            app.languageController.selectLanguage(language)
            app.settingsController.setValue('appearance','theme',theme)
            window.resize(1100,720);QTest.qWait(80)
            note=find(window,'measurementCalibrationWarning')
            assert note.isVisible() and note.width()>120
            assert ('pixel spacing' if language=='en-US' else '像素间距') in note.property('text')
            output=os.environ.get('VOXENRA_SPATIAL_QML_OUTPUT')
            if output:
                dest=Path(output);dest.mkdir(parents=True,exist_ok=True)
                assert window.grabWindow().save(str(dest/f'calibration-{language}-{theme}.png'))
        assert not warnings,warnings


def test_measurement_calibration_tracks_current_source_frame(scene,tmp_path):
    import pydicom
    window,app,warnings=scene
    generate(tmp_path,next(c for c in CASES if c.name=='ct-axial'))
    path=tmp_path/'005.dcm';ds=pydicom.dcmread(path);del ds.PixelSpacing
    ds.save_as(path,enforce_file_format=True)
    snapshot=list(DicomFolderScanner().scan_files(list(tmp_path.glob('*.dcm')),folder=tmp_path))[-1]
    panel=app.panelController;panel.update_series_session(snapshot);panel._update_series_record(snapshot)
    ws=app.workspaceController;ws.createTab(snapshot.series[0].series_instance_uid,'Mixed calibration','2d')
    wait_until(lambda:ws.activeViewport and ws.activeViewport.loadState=='ready')
    view=ws.activeViewport;ws.activeTab.toolController.activateTool('measure')
    for index,calibrated in [(0,True),(4,False),(1,True)]:
        view.setSliceIndex(index);wait_until(lambda:view._frame_meta.slice_index==index);QTest.qWait(50)
        assert view.hasPhysicalSpacing==calibrated
        assert (view._measurement_context(2,2,kind=MeasurementKind.LENGTH) is not None)==calibrated
        assert find(window,'measureEntry-length').isEnabled()==calibrated
    assert not warnings,warnings
