"""Measure a fresh empty workspace through its first frame, without user settings.

QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python tests/manual/benchmark_startup.py
Use QML_DISABLE_DISK_CACHE=1 to compare compilation rather than a warm QML cache.
This measures source startup, not a frozen bootloader, disk cold start or antivirus.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def worker(qml_import_root=None):
    started = time.perf_counter()
    from importlib.resources import files
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete
    from voxplane.ui.app_controller import AppController
    from voxplane.ui.dicom_image_provider import DicomImageProvider
    from voxplane.ui.svg_icon_provider import SvgIconProvider

    app = QApplication([])
    imported = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="voxplane-startup-") as directory:
        root = Path(directory)
        provider = DicomImageProvider()
        controller = AppController(provider, pacs_config_path=root / "pacs.json",
                                   pacs_import_root=root / "imports")
        constructed = time.perf_counter()
        engine = QQmlApplicationEngine()
        if qml_import_root:
            # No fallback to the original Qt QML installation: validate the
            # packaging filter against the actual runtime, not just import text.
            engine.setImportPathList([str(Path(qml_import_root).resolve()),
                                      "qrc:/qt-project.org/imports"])
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.addImageProvider("navigation", SvgIconProvider())
        engine.addImageProvider("dicom", provider)
        engine.rootContext().setContextProperty("appController", controller)
        sample = {}
        try:
            engine.load(QUrl.fromLocalFile(str(files("voxplane").joinpath("qml/Main.qml"))))
            loaded = time.perf_counter()
            if not engine.rootObjects():
                raise RuntimeError(warnings)
            window = engine.rootObjects()[0]
            def first_frame():
                if sample:
                    return
                sample.update(imports_s=imported-started, controller_s=constructed-imported,
                              qml_s=loaded-constructed, first_frame_s=time.perf_counter()-started,
                              vtk_loaded=any(m.startswith("vtkmodules.vtk") for m in sys.modules),
                              highdicom_loaded="highdicom" in sys.modules)
                app.quit()
            window.frameSwapped.connect(first_frame)
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(app.quit)
            timeout.start(15000)
            app.exec()
            timeout.stop()
            if not sample or warnings:
                raise RuntimeError({"sample": sample, "warnings": warnings})
            window.hide()
        finally:
            controller.shutdown()
            delete(engine)
        print(json.dumps(sample))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--qml-import-root")
    args = parser.parse_args()
    if args.worker:
        worker(args.qml_import_root)
        return
    if args.runs < 1:
        parser.error("--runs must be positive")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    if args.qml_import_root:
        command += ["--qml-import-root", args.qml_import_root]
    samples = []
    for _ in range(args.runs):
        started = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        sample = json.loads(result.stdout)
        sample["process_wall_s"] = time.perf_counter()-started
        samples.append(sample)
    medians = {key: statistics.median(s[key] for s in samples)
               for key in samples[0] if key.endswith("_s")}
    print(json.dumps({"platform": sys.platform, "python": sys.version.split()[0],
                      "qt_platform": os.getenv("QT_QPA_PLATFORM", "native"),
                      "qml_disk_cache_disabled": os.getenv("QML_DISABLE_DISK_CACHE") == "1",
                      "median": medians, "samples": samples}, indent=2))


if __name__ == "__main__":
    main()
