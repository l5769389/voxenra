"""Real-window 3D smoke test. Run separately from headless pytest.

    uv run python tests/manual/smoke_3d.py

Creates temporary synthetic DICOM files and exercises the actual QML/worker/VTK
path. Requires a desktop session and OpenGL. No patient data is used.
"""
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolbar_navigation import reveal_primary_tool

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_dicom_viewer.app import bind_controller
from qt_dicom_viewer.core.dicom_scanner import _read_instance, _build_series_record
from qt_dicom_viewer.core.volume_view import VolumeViewState
from qt_dicom_viewer.model.volume_models import VolumeDisplayState
from qt_dicom_viewer.volume_presets import VOLUME_PRESETS, VOLUME_PRESET_BY_ID
from qt_dicom_viewer.model import DicomFolderScanSnapshot, TabType


def make_series(folder):
    series_uid, study_uid = generate_uid(), generate_uid()
    z, y, x = np.mgrid[-1:1:48j, -1:1:64j, -1:1:64j]
    pixels = np.full(x.shape, -1000, dtype=np.int16)
    pixels[(x/0.65)**2+(y/0.8)**2+(z/0.85)**2 < 1] = 100
    pixels[((x+0.25)/0.18)**2+(y/0.42)**2+(z/0.6)**2 < 1] = -650
    pixels[((x-0.2)/0.15)**2+((y+0.2)/0.2)**2+(z/0.65)**2 < 1] = 400
    pixels[((x-0.23)/0.2)**2+(y/0.23)**2+(z/0.65)**2 < 1] = 800
    pixels[((x+0.22)/0.10)**2+((y-0.18)/0.12)**2+(z/0.48)**2 < 1] = 2400
    pixels[(y > 0.86) & (y < 0.97) & (np.abs(x) < 0.92)] = 450
    instances = []
    for index, plane in enumerate(pixels):
        path = folder / f"{index:03}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0"*128)
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
        ds.PatientName, ds.PatientID = "Synthetic^Phantom", "SMOKE-3D"
        ds.SeriesDescription, ds.Modality = "Synthetic 3D phantom", "CT"
        ds.InstanceNumber = index+1
        ds.Rows, ds.Columns = plane.shape
        ds.PixelSpacing, ds.SliceThickness = [1, 1], 1.5
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [-32, -32, -36+1.5*index]
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
        ds.SamplesPerPixel, ds.PixelRepresentation = 1, 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleIntercept, ds.RescaleSlope = 0, 1
        ds.WindowCenter, ds.WindowWidth = 400, 1000
        ds.PixelData = plane.tobytes()
        ds.save_as(path, enforce_file_format=True)
        instances.append(_read_instance(path))
    return _build_series_record(instances)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    temp = TemporaryDirectory(prefix="qt-dicom-3d-")
    series = make_series(Path(temp.name))
    second = replace(series, series_instance_uid=generate_uid(), series_description="Second phantom")
    engine = bind_controller()
    controller = engine.app_controller
    controller._series_catalog.update(DicomFolderScanSnapshot(
        Path(temp.name), 48, 48, 0, [series, second]))
    warnings = []
    engine.warnings.connect(lambda messages: warnings.extend(m.toString() for m in messages))
    engine.load(files("qt_dicom_viewer").joinpath("qml/Main.qml"))
    assert engine.rootObjects(), "QML root failed to load"
    root = engine.rootObjects()[0]
    workspace = controller.workspaceController
    workspace.createTab(series.series_instance_uid, "Synthetic phantom", TabType.THREE_D)
    first = workspace.activeViewport
    first_id = workspace.activeTabId
    errors = []

    def pump(milliseconds=300):
        # Let the Python render worker run too; QTest.qWait can retain the GIL.
        deadline = time.monotonic()+milliseconds/1000
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    def ready(viewport):
        deadline = time.monotonic()+10
        while viewport.loadState in ("idle", "loading") and time.monotonic() < deadline:
            pump(50)
        assert viewport.loadState == "ready", (viewport.loadState, viewport.errorMessage)
        pump(500)
        assert viewport.loadState == "ready", viewport.errorMessage
        assert viewport._host.backend._initialized
        assert viewport.nativeWindow.parent() == root
        assert viewport._host.isVisible()

    def capture(viewport, filename, allow_empty=False):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.util.numpy_support import vtk_to_numpy
        grab = vtkWindowToImageFilter()
        grab.SetInput(viewport._host.backend.window)
        grab.ReadFrontBufferOff()
        grab.Update()
        array = vtk_to_numpy(grab.GetOutput().GetPointData().GetScalars())
        if not allow_empty:
            assert np.count_nonzero(array.max(axis=1) > 80) > 1000, "Empty framebuffer"
        if filename:
            writer = vtkPNGWriter()
            writer.SetFileName(str(filename))
            writer.SetInputConnection(grab.GetOutputPort())
            writer.Write()
        return array.copy()

    def visual_children(item):
        yield item
        for child in item.childItems():
            yield from visual_children(child)

    def find_item(name):
        reveal_primary_tool(root.contentItem(), name)
        return next(item for item in visual_children(root.contentItem())
                    if item.objectName() == name and item.isVisible())

    def click_item(name):
        button = find_item(name)
        assert button.isEnabled(), name
        if name.startswith("volumePreset-"):
            flickable = find_item("toolDetailFlickable")
            local = button.mapToItem(flickable, QPointF(button.width()/2, button.height()/2))
            if local.y() < 0 or local.y() > flickable.height():
                target = flickable.property("contentY") + local.y() - flickable.height()/2
                maximum = max(0, flickable.property("contentHeight")-flickable.height())
                flickable.setProperty("contentY", min(max(0, target), maximum))
                pump(20)
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
        QTest.mouseClick(root, Qt.LeftButton, pos=point)
        pump(50)

    def select_tool(name):
        click_item("primaryTool-"+name)

    def sample_anatomy(array, widget):
        w, h = widget.GetRenderWindow().GetSize()
        return array.reshape(h, w, 3)[h//5:4*h//5, w//5:4*w//5]

    def edit_ready(viewport):
        deadline = time.monotonic()+15
        while viewport.editBusy and time.monotonic() < deadline:
            pump(30)
        assert not viewport.editBusy
        assert not viewport.editMessage, viewport.editMessage
        pump()

    def draw_crop(widget, fractions):
        points = [QPoint(round(x*widget.width()), round(y*widget.height())) for x, y in fractions]
        QTest.mousePress(widget, Qt.LeftButton, pos=points[0])
        for point in points[1:]:
            QTest.mouseMove(widget, point, 20)
        pump(80)
        assert first._drawing and first._host.backend.selection_actor.GetVisibility()
        if len(sys.argv) > 1:
            capture(first, Path(sys.argv[1]).with_stem("volume-crop-"+first.cropMode+"-selection"))
        QTest.mouseRelease(widget, Qt.LeftButton, pos=points[-1])
        assert not first.selection_points
        edit_ready(first)
        assert first.hasCrop

    def exercise():
        try:
            ready(first)
            print("3D loaded and embedded", first._host.size(), flush=True)
            backend = first._host.backend
            started = time.perf_counter()
            backend.render(first.state, True, first.display_state)
            interactive_elapsed = time.perf_counter()-started
            interactive_frame = capture(first, None)
            started = time.perf_counter()
            backend.render(first.state, False, first.display_state)
            settled_elapsed = time.perf_counter()-started
            settled_frame = capture(first, None)
            quality_delta = np.abs(interactive_frame.astype(np.int16)-settled_frame.astype(np.int16))
            assert quality_delta.max() <= 1
            assert np.mean(quality_delta) < 0.01
            print(f"PASS: fixed interaction quality (pixel delta {np.mean(quality_delta):.4f}, "
                  f"interactive {interactive_elapsed*1000:.1f} ms, settled {settled_elapsed*1000:.1f} ms)",
                  flush=True)
            before = capture(first, None)
            marker_initial = first._host.backend.marker.GetRenderer().GetActiveCamera().GetDirectionOfProjection()
            widget = first._host.vtk_widget
            center = QPoint(widget.width()//2, widget.height()//2)
            QTest.mousePress(widget, Qt.LeftButton, pos=center)
            QTest.mouseMove(widget, center+QPoint(95, 50))
            QTest.mouseRelease(widget, Qt.LeftButton, pos=center+QPoint(95, 50))
            pump()
            assert first.state.rotation != VolumeViewState().rotation
            after = capture(first, sys.argv[1] if len(sys.argv) > 1 else None)
            assert np.mean(np.abs(after.astype(float)-before.astype(float))) > 0.1
            marker_rotated = first._host.backend.marker.GetRenderer().GetActiveCamera().GetDirectionOfProjection()
            assert not np.allclose(marker_initial, marker_rotated)
            np.testing.assert_allclose(marker_rotated,
                first._host.backend.renderer.GetActiveCamera().GetDirectionOfProjection())
            select_tool("volume-direction")
            for face in ("P", "L", "R", "S", "I", "A"):
                click_item("volumeFace-"+face)
                assert first.currentFace == face
                assert find_item("currentVolumeFace").property("text") == face
                assert find_item("volumeFace-"+face).property("checked")
            QTest.mousePress(widget, Qt.LeftButton, pos=center)
            QTest.mouseRelease(widget, Qt.LeftButton, pos=center+QPoint(300, 40))
            pump()
            assert find_item("currentVolumeFace").property("text") == first.currentFace
            assert first.currentFace != "A"
            assert sum(find_item("volumeFace-"+f).property("checked") for f in "AP LRSI".replace(" ", "")) == 1
            click_item("volumeFace-A")
            select_tool("volume-preset")
            frames = {}
            image_data = first._host.backend.mapper.GetInput()
            for preset_id in (p.preset_id for p in VOLUME_PRESETS if p.group != "MR"):
                click_item("volumePreset-"+preset_id)
                pump()
                assert first.currentPresetId == preset_id, (preset_id, first.currentPresetId)
                assert find_item("volumePreset-"+preset_id).property("checked")
                filename = (Path(sys.argv[1]).with_stem(Path(sys.argv[1]).stem+"-"+preset_id)
                            if len(sys.argv) > 1 else None)
                frames[preset_id] = sample_anatomy(capture(first, filename), widget)
                assert np.count_nonzero(frames[preset_id].max(axis=2) > 20) > 500, preset_id
                assert first._host.backend.mapper.GetInput() is image_data
            for name in frames.keys()-{"general"}:
                assert np.mean(np.abs(frames[name].astype(float)-frames["general"].astype(float))) > 0.1, name
            assert np.mean(frames["xray"] > 250) < 0.1, "XRay saturated"
            # Increasing ray density must not apply opacity compensation twice.
            click_item("volumePreset-xray")
            backend = first._host.backend
            step = backend._sample_distance
            backend.mapper.SetSampleDistance(step * 4)
            coarse = sample_anatomy(capture(first, None), widget)
            backend.mapper.SetSampleDistance(step)
            dense = sample_anatomy(capture(first, None), widget)
            assert abs(coarse.mean()-dense.mean()) / max(1, dense.mean()) < 0.1, "XRay exposure depends on sampling"
            click_item("volumePreset-bone")
            select_tool("window")
            assert workspace.activeTab.toolController.activePanel == "window"
            original_display = first.display_state
            pose = first.state
            QTest.mousePress(widget, Qt.LeftButton, pos=center)
            QTest.mouseRelease(widget, Qt.LeftButton, pos=center+QPoint(100, -100))
            pump()
            assert first.windowCenter > original_display.window.center
            assert first.windowWidth > original_display.window.width
            assert first.state == pose
            changed = sample_anatomy(capture(first, None), widget)
            assert np.mean(np.abs(changed.astype(float)-frames["bone"].astype(float))) > 0.1
            click_item("activeToolReset")
            assert first.display_state == original_display
            print(f"PASS: six faces, QML direction tracking, all {len(frames)} CT presets, drag window/reset", flush=True)
            select_tool("pan")
            QTest.mousePress(widget, Qt.LeftButton, pos=center)
            QTest.mouseRelease(widget, Qt.LeftButton, pos=center+QPoint(30, 15))
            assert first.state.pan != (0, 0)
            select_tool("zoom")
            QTest.mousePress(widget, Qt.LeftButton, pos=center)
            QTest.mouseRelease(widget, Qt.LeftButton, pos=center+QPoint(0, -80))
            assert first.state.zoom > 1
            saved = first.state
            saved_display = first.display_state
            marker_before = first._host.backend.marker.GetRenderer().GetActiveCamera().GetDirectionOfProjection()
            pump()
            marker_after = first._host.backend.marker.GetRenderer().GetActiveCamera().GetDirectionOfProjection()
            np.testing.assert_allclose(marker_before, marker_after)
            root.resize(1200, 700)
            pump()
            assert widget.width() < 800 and widget.height() > 400
            workspace.createTab(series.series_instance_uid, "2D phantom", TabType.TWO_D)
            pump()
            assert not first._host.isVisible()
            assert first.nativeWindow.parent() is None
            workspace.activateTabId(first_id)
            pump()
            ready(first)
            assert first.state == saved
            assert first.display_state == saved_display
            workspace.createTab(second.series_instance_uid, "Second phantom", TabType.THREE_D)
            other = workspace.activeViewport
            ready(other)
            assert other.state == VolumeViewState()
            assert other.currentPresetId == "aaa"
            assert not first._host.isVisible()
            workspace.closeTab(workspace.activeTabId)
            pump()
            assert other.nativeWindow is None
            workspace.activateTabId(first_id)
            pump()
            ready(first)
            select_tool("reset")
            assert first.state == VolumeViewState()
            assert first.display_state == VolumeDisplayState("aaa", VOLUME_PRESET_BY_ID["aaa"].default_window)
            original_pixels = first.volume.modality_pixels.copy()
            with_bed = capture(first, None)
            select_tool("volume-bed")
            edit_ready(first)
            assert first.bedRemovalEnabled
            assert workspace.activeTab.toolController.activeTool != "volume-bed"
            assert find_item("primaryTool-volume-bed").property("checked")
            bed_mask = first.visible_mask.copy()
            assert not bed_mask[:, 60, 10:54].any()
            without_bed = capture(first, None)
            assert np.mean(np.abs(with_bed.astype(float)-without_bed.astype(float))) > 0.1
            select_tool("volume-crop")
            assert find_item("volumeCrop-inside").isEnabled()
            assert find_item("volumeCrop-inside").property("checked")
            assert "voi" not in {t["toolType"] for t in workspace.activeTab.toolController.tools}
            draw_crop(widget, [(0.34, 0.30), (0.62, 0.29), (0.55, 0.48), (0.63, 0.65), (0.36, 0.68)])
            assert first.hasCrop and not first.selection_points
            assert np.count_nonzero(first.visible_mask) < np.count_nonzero(bed_mask)
            inside_mask = first.crop_mask.copy()
            cropped = capture(first, None, allow_empty=True)
            assert np.mean(np.abs(cropped.astype(float)-without_bed.astype(float))) > 0.1
            select_tool("pan")
            assert first.bedRemovalEnabled and first.hasCrop
            select_tool("volume-bed")
            assert not first.bedRemovalEnabled
            np.testing.assert_array_equal(first.visible_mask, inside_mask)
            select_tool("volume-bed")
            assert first.bedRemovalEnabled
            select_tool("volume-crop")
            assert first.cropMode == "inside"
            click_item("volumeCrop-outside")
            assert first.cropMode == "outside"
            draw_crop(widget, [(0.03, 0.03), (0.12, 0.03), (0.10, 0.12), (0.03, 0.10)])
            assert not first.visible_mask.any()
            # A completely excluded volume must remain invisible in every blend
            # mode and after transfer-function edits, not just look like air.
            select_tool("volume-preset")
            for preset in ("general", "bone", "lung", "vessel", "mip", "xray"):
                click_item("volumePreset-"+preset)
                pump()
                anatomy = sample_anatomy(capture(first, None, allow_empty=True), widget)
                assert anatomy.max() < 20, (preset, anatomy.max())
            select_tool("volume-crop")
            click_item("activeToolReset")
            assert first.bedRemovalEnabled and not first.hasCrop
            np.testing.assert_array_equal(first.visible_mask, bed_mask)
            capture(first, None)
            select_tool("reset")
            assert not first.bedRemovalEnabled and first.visible_mask is None
            np.testing.assert_array_equal(first.volume.modality_pixels, original_pixels)
            print("PASS: bed toggle coexists, native freehand preview, inside/outside crops, "
                  "all six masked presets, scoped/global resets, original pixels unchanged", flush=True)
            workspace.closeTab(first_id)
            pump()
            assert first.nativeWindow is None
            workspace.createTab(series.series_instance_uid, "Reopened phantom", TabType.THREE_D)
            ready(workspace.activeViewport)
            assert not warnings, "\n".join(warnings)
            print("PASS: render, drag tools, cube, resize, 2D/3D switching, independent tabs, close/reopen", flush=True)
        except BaseException:
            errors.append(traceback.format_exc())
            print(errors[-1], flush=True)
        finally:
            controller.shutdown()
            root.close()
            app.quit()

    QTimer.singleShot(100, exercise)
    app.exec()
    temp.cleanup()
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
