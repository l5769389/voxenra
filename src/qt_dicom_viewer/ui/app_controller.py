from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Property, QObject, Signal, Slot, QCoreApplication
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.series_export_controller import SeriesExportController

from qt_dicom_viewer.ui.controller.pacs_controller import PacsController
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.model import DicomSeriesRecord
from qt_dicom_viewer.service.render_serivce import RenderService
from qt_dicom_viewer.ui.controller.panel_controller import  PanelController
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.application.series_catalog import SeriesCatalog


class AppController(QObject):
    statusMessageChanged = Signal()
    scanningChanged = Signal()
    summaryTextChanged = Signal()
    seriesItemsChanged = Signal()

    def __init__(self, image_provider, *, pacs_config_path=None, pacs_import_root=None, settings_path=None) -> None:
        super().__init__()
        self._native_window_chrome = None
        self._native_window_chromes = {}
        self._file_drop_filter = None
        self._status_message = "Ready"
        self._image_provider = image_provider
        self._summary_text = "No DICOM folder loaded"
        self._series_items = []
        self._series_info: dict[str, DicomSeriesRecord] = {}
        self._series_catalog = SeriesCatalog()
        if settings_path is None and pacs_config_path is not None:
            settings_path = Path(pacs_config_path).with_name("display-settings.json")
        self._settings_controller = SettingsController(self, path=settings_path)
        from qt_dicom_viewer.settings.dialog_locations import DialogLocations
        self._dialog_locations = DialogLocations(
            self._settings_controller._path.with_name("dialog-locations.json")
            if self._settings_controller._path else None)
        self._dialog_locations.activate()
        from qt_dicom_viewer.ui.controller.appearance_controller import AppearanceController
        from qt_dicom_viewer.ui.controller.language_controller import LanguageController
        self._appearance_controller = AppearanceController(self._settings_controller, self)
        language_root = Path(settings_path).parent / "languages" if settings_path else (False if settings_path is False else None)
        self._language_controller = LanguageController(self._settings_controller, self, root=language_root)
        self._series_export_controller = SeriesExportController(self._series_catalog, self._settings_controller, self)
        self._workspace_controller = WorkspaceController(self._series_catalog,self._image_provider,parent= self)
        self._panel_controller = PanelController(parent=self, series_catalog=self._series_catalog, image_provider=image_provider)
        from qt_dicom_viewer.ui.controller.window_manager import WindowManager
        self._window_manager = WindowManager(self, self._workspace_controller)
        self._export_controller = self._window_manager.mainWorkspace.exportController
        self._pacs_controller = PacsController(self, config_path=pacs_config_path, import_root=pacs_import_root)
        self._pacs_controller.imported.connect(self._panel_controller.acceptPacsImport)
        self._volume_manager = VolumeManager()
        self.render_service = RenderService(self._series_catalog, self._volume_manager, self)
        self._signal_connect()
        from qt_dicom_viewer.ui.file_drop_filter import NativeFileDropFilter
        self._file_drop_filter = NativeFileDropFilter(self)
        from qt_dicom_viewer.ui.controller.workspace_document_controller import WorkspaceDocumentController
        self._workspace_document_controller = WorkspaceDocumentController(self, settings_path=settings_path)
        from qt_dicom_viewer.ui.controller.update_controller import UpdateController
        self._update_controller = UpdateController(self._settings_controller, self,
            cache=Path(settings_path).parent / "updates" if settings_path else None)
        # The workspace document event filter handles save/discard/cancel for all
        # windows before accepting this normal Qt quit request.
        self._update_controller.exitRequested.connect(QCoreApplication.quit)


    @Slot(QObject)
    def configureNativeWindow(self, window):
        from PySide6.QtQml import qmlEngine
        self._language_controller.attach_engine(qmlEngine(window))
        self._configure_native_window(window, custom_title=True)

    @Slot(QObject)
    def configureNativeDialogWindow(self, window):
        self._configure_native_window(window, custom_title=False)

    def _configure_native_window(self, window, *, custom_title):
        from PySide6.QtGui import QWindow
        from qt_dicom_viewer.infrastructure.native_window import NativeWindowChrome
        if isinstance(window, QWindow) and window not in self._native_window_chromes:
            chrome = NativeWindowChrome(window, window, custom_title=custom_title)
            self._native_window_chromes[window] = chrome
            window.destroyed.connect(lambda: self._native_window_chromes.pop(window, None))
            if custom_title and self._native_window_chrome is None:
                self._native_window_chrome = chrome

    def _signal_connect(self):
        #  监听切换series
        self._panel_controller.tabCreateRequested.connect(
            self._workspace_controller.activeWorkspace
        )
        self._panel_controller.fusionCreateRequested.connect(self._workspace_controller.createFusionTab)
        self._panel_controller.compareController.openRequested.connect(self._workspace_controller.createCompareTab)
        self._panel_controller.compareController.mprOpenRequested.connect(self._workspace_controller.createMprCompareTab)

        self._panel_controller.compareController.multiOpenRequested.connect(self._workspace_controller.createMultiCompareTab)
        # renderService接收渲染请求。
        self._workspace_controller.renderRequested.connect(
            self.render_service.submit
        )
        self._workspace_controller.renderCancelled.connect(self.render_service.cancel)
        # workspace接收渲染结果
        self.render_service.rendered.connect(
            self._workspace_controller.handleRenderResult
        )
        self.render_service.failed.connect(
            self._workspace_controller.handleRenderFailure
        )


    @Property(QObject, constant=True)
    def windowManager(self):
        return self._window_manager

    @Property(QObject, constant=True)
    def seriesExportController(self):
        return self._series_export_controller

    @Property(QObject, constant=True)
    def appearanceController(self):
        return self._appearance_controller

    @Property(QObject, constant=True)
    def languageController(self):
        return self._language_controller

    @Property(QObject, constant=True)
    def updateController(self):
        return self._update_controller

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._settings_controller

    @Property(QObject, constant=True)
    def panelController(self) -> QObject:
        return self._panel_controller

    @Property(QObject, constant=True)
    def pacsController(self) -> QObject:
        return self._pacs_controller

    @Property(QObject, constant=True)
    def exportController(self):
        return self._export_controller

    @Property(QObject, constant=True)
    def workspaceDocumentController(self):
        return self._workspace_document_controller

    @Slot()
    def shutdown(self) -> None:
        self._update_controller.shutdown()
        self._dialog_locations.deactivate()
        self._workspace_document_controller.shutdown()
        self._series_export_controller.shutdown()
        self._window_manager.shutdown()
        self._pacs_controller.shutdown()
        self._panel_controller.shutdown()
        self._workspace_controller.shutdown()
        self.render_service.shutdown()
        self._panel_controller.cleanup_imports()
        self._workspace_document_controller.cleanup_imports()
        if self._file_drop_filter is not None:
            self._file_drop_filter.shutdown()
        self._language_controller.shutdown()

    @Property(QObject, constant=True)
    def workspaceController(self) -> QObject:
        return self._workspace_controller
