"""Desktop integration: synthetic rescaled DICOM -> loader -> QA worker -> QML.

    PYTHONPATH=src uv run python tests/manual/smoke_water_qa.py /tmp/water-qa.png

No patient data is used. The optional screenshot shows the five measured ROIs.
"""
from importlib.resources import files
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from functools import partial
from unittest.mock import patch
import time
import traceback

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_dicom_viewer.app import bind_controller
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.core.dicom_scanner import _read_instance, _build_series_record
from qt_dicom_viewer.model import DicomFolderScanSnapshot, TabType


def make_water_series(folder):
    series_uid, study_uid = generate_uid(), generate_uid()
    y, x = np.indices((384, 512))
    radius = np.hypot((x-259)*.6, (y-185)*.8)
    body = radius < 95
    instances, expected = [], []
    for index, mean in enumerate((-3, 2, 7)):
        pixels = np.full(radius.shape, -1000.0)
        pixels[body] = np.random.default_rng(100+index).normal(mean, 6, np.count_nonzero(body))
        pixels[(radius >= 95) & (radius < 99)] = 800
        pixels[350:358, 30:480] = 180
        stored = np.rint((pixels+1024)/2).astype(np.int16)
        expected.append(stored.astype(float)*2-1024)
        path = folder/f"water-{index}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0"*128)
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
        ds.SeriesInstanceUID, ds.StudyInstanceUID = series_uid, study_uid
        ds.PatientName, ds.PatientID = "Synthetic^WaterQA", "WATER-QA-SMOKE"
        ds.SeriesDescription, ds.Modality = "Synthetic water phantom", "CT"
        ds.InstanceNumber, ds.Rows, ds.Columns = index+1, *stored.shape
        ds.PixelSpacing, ds.SliceThickness = [.8, .6], 2
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [-155.4, -148, index*2]
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
        ds.SamplesPerPixel, ds.PixelRepresentation = 1, 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleIntercept, ds.RescaleSlope = -1024, 2
        ds.WindowCenter, ds.WindowWidth = 0, 100
        ds.PixelData = stored.tobytes()
        ds.save_as(path, enforce_file_format=True)
        instances.append(_read_instance(path))
    return _build_series_record(instances), expected


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    temp = TemporaryDirectory(prefix="water-qa-")
    series, expected = make_water_series(Path(temp.name))
    isolated = partial(AppController, settings_path=Path(temp.name) / "settings.json",
                       pacs_config_path=Path(temp.name) / "pacs.json", pacs_import_root=Path(temp.name) / "imports")
    with patch("qt_dicom_viewer.app.AppController", isolated):
        engine = bind_controller()
    app_controller = engine.app_controller
    app_controller._series_catalog.update(DicomFolderScanSnapshot(Path(temp.name), 3, 3, 0, [series]))
    warnings, errors = [], []
    engine.warnings.connect(lambda entries: warnings.extend(e.toString() for e in entries))
    engine.load(files("qt_dicom_viewer").joinpath("qml/Main.qml"))
    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    workspace = app_controller.workspaceController
    workspace.createTab(series.series_instance_uid, "Water QA", TabType.TWO_D)
    view = workspace.activeViewport

    def pump(ms=80):
        deadline = time.monotonic()+ms/1000
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.003)

    def wait_for(condition):
        deadline = time.monotonic()+10
        while not condition() and time.monotonic() < deadline:
            pump(20)
        assert condition(), (view.qaController.status, view.qaController.error)
        pump()

    def children(item):
        yield item
        for child in item.childItems():
            yield from children(child)

    def find(name):
        return next(item for item in children(root.contentItem()) if item.objectName() == name and item.isVisible())

    def click(name):
        item = find(name)
        assert item.isEnabled(), name
        center = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
        QTest.mouseClick(root, Qt.LeftButton, pos=center)
        pump()

    def exercise():
        try:
            wait_for(lambda: bool(view.imageSource))
            np.testing.assert_array_equal(view._modality_pixel, expected[0])
            if not any(i.objectName() == "primaryTool-service" and i.isVisible() for i in children(root.contentItem())):
                click("primaryToolsMore")
            click("primaryTool-service")
            click("serviceEntry-qa")
            qa = view.qaController
            wait_for(lambda: qa.status == "ready")
            assert len(qa.roiItems) == 5
            assert abs(qa.currentResult["water_ct_hu"]+3) < 1
            assert 5 < qa.currentResult["noise_hu"] < 7
            for key in ("center", "left", "right", "top", "bottom"):
                assert find("waterQaVoi-"+key).isVisible()
            pixels = find("dicomPixelLayer")
            for index in range(5):
                before = qa.currentResult["rois"]
                roi = before[index]
                start = pixels.mapToScene(QPointF(roi["column"]+.5, roi["row"]+.5)).toPoint()
                end = pixels.mapToScene(QPointF(roi["column"]+8.5, roi["row"]+5.5)).toPoint()
                QTest.mousePress(root, Qt.LeftButton, pos=start)
                QTest.mouseMove(root, (start+end)/2, 20)
                assert qa.dragging
                QTest.mouseMove(root, end, 20)
                QTest.mouseRelease(root, Qt.LeftButton, pos=end)
                pump()
                adjusted = qa.currentResult["rois"][index]
                assert not qa.error and not qa.dragging
                assert abs(adjusted["column"]-roi["column"]-8) < 1
                assert abs(adjusted["row"]-roi["row"]-5) < 1
                for region in qa.currentResult["rois"]:
                    item = find("waterQaVoi-"+region["key"])
                    expected_point = pixels.mapToItem(item, QPointF(region["column"]+.5, region["row"]+.5))
                    actual_point = item.property("center")
                    assert abs(actual_point.x()-expected_point.x()) < .01
                    assert abs(actual_point.y()-expected_point.y()) < .01
                y, x = np.indices(expected[0].shape)
                mask = ((x-adjusted["column"])*.6)**2+((y-adjusted["row"])*.8)**2 <= adjusted["radius_mm"]**2
                assert abs(adjusted["mean_hu"]-expected[0][mask].mean()) < 1e-6
            QTest.mouseMove(root, QPointF(30, 30).toPoint())
            pump()
            if len(sys.argv) > 1:
                assert root.grabWindow().save(sys.argv[1])
            tab_id = workspace.activeTabId
            click("waterQaManualButton")
            wait_for(lambda: workspace.activeTabType == "manual" and workspace.manualController.chapterId == "water-qa")
            if len(sys.argv) > 1:
                path = Path(sys.argv[1])
                assert root.grabWindow().save(str(path.with_stem(path.stem+"-info")))
            workspace.activateTabId(tab_id)
            wait_for(lambda: workspace.activeViewport is view and find("waterQaManualButton").isVisible())
            saved, token = qa.currentResult, qa._token
            view.applyWindowPreset(200, 800)
            wait_for(lambda: view.current_window.center == 200)
            pump(200)
            assert qa.currentResult == saved and qa._token == token
            for index in (1, 2, 0):
                view.setSliceIndex(index)
                wait_for(lambda: qa.status == "ready" and view._frame_meta.slice_index == index)
                np.testing.assert_array_equal(view._modality_pixel, expected[index])
                assert abs(qa.currentResult["water_ct_hu"]-(-3+5*index)) < 1
            view.applyTransformAction("rotate:cw90")
            view.applyTransformAction("rotate:mirror-h")
            view.apply_zoom(1.2)
            pump()
            assert qa.currentResult == saved
            find("activeToolReset").forceActiveFocus(Qt.TabFocusReason)
            pump()
            click("activeToolReset")
            assert not qa.enabled and qa.roiItems == []
            find("waterQa-analyze").forceActiveFocus(Qt.TabFocusReason)
            pump()
            click("waterQa-analyze")
            wait_for(lambda: qa.status == "ready")
            assert len(qa.roiItems) == 5
            assert not warnings, "\n".join(warnings)
            print("PASS: rescaled HU DICOM loading, automatic five-ROI QA, five mouse drags and HU resampling, "
                  "clickable help, per-slice edited-position cache, display transforms, scoped reset, no QML warnings", flush=True)
        except BaseException:
            errors.append(traceback.format_exc())
            print(errors[-1], flush=True)
        finally:
            app_controller.shutdown()
            root.close()
            app.quit()

    QTimer.singleShot(100, exercise)
    app.exec()
    temp.cleanup()
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
