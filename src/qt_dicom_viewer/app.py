from __future__ import annotations

import logging
import sys
from importlib.resources import as_file, files

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from qt_dicom_viewer.infrastructure.exception_handler import install_exception_hooks
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.infrastructure.logging_config import (
    configure_logging,
)

logger = logging.getLogger(__name__)
install_exception_hooks()

def configure_process_identity() -> None:
    """Match installed shortcuts before Windows creates any application windows."""
    if sys.platform == "win32":
        import ctypes

        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.c_long
        result = set_id("com.junliu.voxenra")
        if result != 0:
            logger.warning("Could not set Windows application identity: %s", result)


def configure_application_identity(app: QApplication) -> None:
    from qt_dicom_viewer import __version__
    app.setApplicationDisplayName("Voxenra")
    app.setApplicationVersion(__version__)
    # Native decorations and dialogs should match the application surfaces.
    pixmap = QPixmap()
    brand = files("qt_dicom_viewer").joinpath("qml/assets/brand/voxenra-mark.png")
    if pixmap.loadFromData(brand.read_bytes()):
        app.setWindowIcon(QIcon(pixmap))
    else:
        logger.warning("Could not load application icon")


def main() -> None:
    configure_process_identity()
    app = QApplication(sys.argv)
    configure_application_identity(app)
    from qt_dicom_viewer.infrastructure.brand_settings import configure_storage_identity
    configure_storage_identity()

    log_path = configure_logging(debug=True)

    logger.info("Application starting")
    logger.info("Log file: %s", log_path)
    engine = bind_controller()
    app.aboutToQuit.connect(engine.app_controller.shutdown)

    qml_path = files("qt_dicom_viewer").joinpath("qml/Main.qml")
    try:
        engine.load(qml_path)

        if not engine.rootObjects():
            logger.critical("Failed to load QML root component")
            return 1

        from qt_dicom_viewer.infrastructure.update_health import arm_startup_confirmation
        arm_startup_confirmation(engine.rootObjects()[0])
        engine.app_controller.updateController.start()
        result = app.exec()
    finally:
        engine.app_controller.shutdown()
    # Installation starts only after the regular workspace exit decision and
    # worker shutdown; a cancelled close never reaches this handoff.
    if result == 0:
        try:
            engine.app_controller.updateController.install_after_exit()
        except OSError:
            logger.exception("Could not launch update installer")
            # No application files were touched. Reopen the current version
            # quietly if the operating system could not start the helper.
            from qt_dicom_viewer.infrastructure.update_installer import restart_current_application
            restart_current_application()
    return result


def bind_controller() -> QQmlApplicationEngine:
    engine = QQmlApplicationEngine()
    image_provider = DicomImageProvider()
    app_controller = AppController(image_provider)
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    engine.addImageProvider("navigation", SvgIconProvider())
    engine.addImageProvider("dicom", image_provider)
    engine.rootContext().setContextProperty("appController", app_controller)
    engine.image_provider = image_provider
    engine.app_controller = app_controller

    return engine

if __name__ == "__main__":
    main()
