"""Native PET/CT multivolume smoke test; requires a desktop OpenGL session.

PYTHONPATH=src python tests/manual/smoke_pet_3d.py /tmp/pet-3d
Uses only generated phantom data. Also saves four-pane and 3D screenshots.
"""
from importlib.resources import files
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

import numpy as np
import pydicom
from pydicom.uid import PositronEmissionTomographyImageStorage, generate_uid
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.util.numpy_support import vtk_to_numpy

if __package__:
    from .smoke_3d import make_series
else:
    from smoke_3d import make_series
from voxplane.app import bind_controller
from voxplane.core.dicom_scanner import _read_instance, _build_series_record
from voxplane.core.volume_view import VolumeViewState
from voxplane.model import DicomFolderScanSnapshot


def make_pair(folder):
    ct = make_series(folder)
    reference, pet_uid = generate_uid(), generate_uid()
    ct_instances, pet_instances = [], []
    z, y, x = np.mgrid[-1:1:48j, -1:1:64j, -1:1:64j]
    pet_pixels = (9000*np.exp(-((x-.25)**2+(y+.1)**2+(z-.2)**2)/.045)
                  + 5000*np.exp(-((x+.2)**2+(y-.1)**2+(z+.4)**2)/.03)).astype(np.uint16)
    for index, instance in enumerate(ct.instances):
        ds = pydicom.dcmread(instance.path)
        ds.FrameOfReferenceUID = reference
        ds.save_as(instance.path, enforce_file_format=True)
        ct_instances.append(_read_instance(instance.path))
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID = PositronEmissionTomographyImageStorage
        ds.SeriesInstanceUID, ds.SeriesDescription, ds.Modality = pet_uid, "Synthetic PET hotspots", "PT"
        ds.Units, ds.SUVType = "GML", "BW"
        ds.SeriesType = ["STATIC", "IMAGE"]
        ds.RescaleSlope, ds.RescaleIntercept = .001, 0
        ds.PixelRepresentation = 0
        ds.WindowCenter, ds.WindowWidth = 5, 10
        ds.PixelData = pet_pixels[index].tobytes()
        path = folder / f"pet-{index:03}.dcm"
        ds.save_as(path, enforce_file_format=True)
        pet_instances.append(_read_instance(path))
    return _build_series_record(ct_instances), _build_series_record(pet_instances)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/pet-3d")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="pet-3d-phantom-") as folder:
        ct, pet = make_pair(Path(folder))
        engine = bind_controller()
        controller = engine.app_controller
        controller._series_catalog.update(DicomFolderScanSnapshot(Path(folder), 96, 96, 0, [ct, pet]))
        warnings = []
        engine.warnings.connect(lambda messages: warnings.extend(m.toString() for m in messages))
        engine.load(files("voxplane").joinpath("qml/Main.qml"))
        assert engine.rootObjects(), "QML failed to load"
        root = engine.rootObjects()[0]
        root.resize(1440, 850)
        workspace = controller.workspaceController

        def pump(ms=300):
            deadline = time.monotonic()+ms/1000
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)

        def until(predicate):
            deadline = time.monotonic()+20
            while not predicate() and time.monotonic() < deadline:
                pump(30)
            assert predicate(), "Timed out"

        def children(item):
            yield item
            for child in item.childItems():
                yield from children(child)

        def click(name):
            button = next(item for item in children(root.contentItem())
                          if item.objectName() == name and item.isVisible())
            assert button.isEnabled(), name
            QTest.mouseClick(root, Qt.LeftButton, pos=button.mapToScene(
                QPointF(button.width()/2, button.height()/2)).toPoint())
            pump()

        def capture(view, name):
            grab = vtkWindowToImageFilter()
            grab.SetInput(view._host.backend.window)
            grab.ReadFrontBufferOff()
            grab.Update()
            data = grab.GetOutput()
            w, h, _ = data.GetDimensions()
            array = vtk_to_numpy(data.GetPointData().GetScalars()).reshape(h, w, 3).copy()
            anatomy = array[h//5:4*h//5, w//5:4*w//5]
            assert np.count_nonzero(anatomy.max(axis=2) > 60) > 500, (name, "Empty anatomy")
            writer = vtkPNGWriter()
            writer.SetFileName(str(output / f"{name}.png"))
            writer.SetInputData(data)
            writer.Write()
            return array

        try:
            workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
            source = workspace.activeTab
            until(lambda: source.ready)
            pump()
            root.grabWindow().save(str(output / "four-pane.png"))
            click("openFusion3D")
            view, volume_id = workspace.activeViewport, workspace.activeTabId
            until(lambda: view._host is not None and view._host.backend._initialized)
            pump()
            assert view.loadState == "ready", view.errorMessage
            assert view.nativeWindow.parent() == root and view._host.isVisible()
            assert any(i.objectName() == "petVolumePanel" and i.isVisible()
                       for i in children(root.contentItem())), "Missing 3D controls"
            frames = {}
            for mode in ("ct", "pet", "fusion"):
                click("volumeMode-"+mode)
                assert view.volumeMode == mode
                frames[mode] = capture(view, mode)
            for a, b in (("ct", "pet"), ("ct", "fusion"), ("pet", "fusion")):
                assert np.mean(np.abs(frames[a].astype(float)-frames[b])) > .1, (a, b)
            root.grabWindow().save(str(output / "3d-controls.png"))
            # grabWindow on QQuickWindow omits its native VTK child. The screen
            # API captures this application's own window with that child.
            root.screen().grabWindow(root.winId()).save(str(output / "3d-window.png"))
            backend = view._host.backend
            ct_input = backend.mapper.GetInputDataObject(0, 0)
            pet_input = backend.mapper.GetInputDataObject(1, 0)
            widget = view._host.vtk_widget
            center = QPoint(widget.width()//2, widget.height()//2)
            QTest.mousePress(widget, Qt.LeftButton, pos=center)
            QTest.mouseMove(widget, center+QPoint(100, 65))
            QTest.mouseRelease(widget, Qt.LeftButton, pos=center+QPoint(100, 65))
            pump()
            assert view.state.rotation != VolumeViewState().rotation
            rotated = capture(view, "rotated")
            assert np.mean(np.abs(rotated.astype(float)-frames["fusion"])) > .1
            assert backend.mapper.GetInputDataObject(0, 0) is ct_input
            assert backend.mapper.GetInputDataObject(1, 0) is pet_input
            state = view.state
            workspace.activateTabId(source._tab_config.tab_id)
            pump()
            assert not view._host.isVisible() and view.nativeWindow.parent() is None
            source.setRegistrationActive(True)
            source.setRegistrationParameter(0, 12)
            until(lambda: source._requested == source._committed_request and not source._requested.preview)
            assert view.scene is source._last_result
            workspace.activateTabId(volume_id)
            pump()
            assert view.state == state
            assert backend.layers[1].GetUserMatrix().GetElement(0, 3) == 12
            shifted = capture(view, "registered")
            assert np.mean(np.abs(shifted.astype(float)-rotated)) > .1
            workspace.closeTab(source._tab_config.tab_id)
            pump()
            assert view.source_workspace is None and "快照" in view.sceneLabel
            capture(view, "snapshot")
            workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
            source = workspace.activeTab
            until(lambda: source.ready)
            source.openVolumeView()
            pump()
            assert workspace.activeTabId == volume_id and workspace.activeViewport is view
            assert view.source_workspace is source
            workspace.closeTab(volume_id)
            pump()
            assert view.nativeWindow is None
            source.openVolumeView()
            reopened = workspace.activeViewport
            until(lambda: reopened._host is not None and reopened._host.backend._initialized)
            assert reopened is not view
            assert not warnings, "\n".join(warnings)
            print("PASS: 3 GPU volume modes, QML controls, rotation, registration sync, cache reuse, tab hide/close/reopen", flush=True)
        finally:
            controller.shutdown()
            root.close()
            pump(50)
            from shiboken6 import delete
            delete(root)


if __name__ == "__main__":
    main()
