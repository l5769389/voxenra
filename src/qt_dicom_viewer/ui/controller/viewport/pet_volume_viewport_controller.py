"""Independent 3D display, following committed PET/CT registration snapshots."""
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from dataclasses import replace
import numpy as np
from qt_dicom_viewer.volume_presets import VOLUME_PRESET_BY_ID
from PySide6.QtCore import Property, Signal, Slot

from qt_dicom_viewer.core.pseudocolor import color_map_options, COLOR_MAP_SPECS
from qt_dicom_viewer.core.volume_view import VolumeViewState
from qt_dicom_viewer.model import ToolType
from .volume_viewport_controller import VolumeViewportController


class PetVolumeViewportController(VolumeViewportController):
    _i18n_colorMapOptions = Signal()
    _i18n_petUnit = Signal()
    _i18n_sceneLabel = Signal()

    sceneChanged = Signal()

    def __init__(self, config, tools, source, parent=None):
        self.scene = None
        self.source_workspace = None
        self._mode = "fusion"
        self._ct_opacity, self._pet_opacity = .25, .8
        self._threshold_fraction = .1
        self._ct_preset = "bone"
        self._palette = "hotIron"
        self._source_open = False
        super().__init__(config, tools, parent)
        self.attach_source(source)

    @Property(bool, constant=True)
    def supportsCtWindow(self): return True

    @Property(bool, constant=True)
    def isFusionVolume(self): return True

    @Property(str, notify=sceneChanged)
    def volumeMode(self): return self._mode

    @_TextProperty(str, notify=_i18n_sceneLabel, notify_name='_i18n_sceneLabel', source_notify='sceneChanged')
    def sceneLabel(self):
        mode = {"ct": "CT 3D", "pet": "PET 3D", "fusion": _msg('text.0555')}[self._mode]
        return mode + (_msg('text.0556') if self._source_open else _msg('text.0557'))

    @Property(float, notify=sceneChanged)
    def ctOpacity(self): return self._ct_opacity

    @Property(float, notify=sceneChanged)
    def petOpacity(self): return self._pet_opacity

    @Property(float, notify=sceneChanged)
    def petUpper(self):
        return self.scene.pet_window.width if self.scene else 1.

    @Property(float, notify=sceneChanged)
    def petThreshold(self): return self._threshold_fraction * self.petUpper

    @_TextProperty(str, notify=_i18n_petUnit, notify_name='_i18n_petUnit', source_notify='sceneChanged')
    def petUnit(self):
        return self.scene.pet_volume.pixel_value_meta.unit if self.scene else ""

    @Property(str, notify=sceneChanged)
    def petUnitId(self):
        return self.scene.pet_volume.pixel_value_meta.unit_id if self.scene else ""

    @Property(str, notify=sceneChanged)
    def ctPreset(self): return self._ct_preset

    @Property(str, notify=sceneChanged)
    def petPalette(self): return self._palette

    @_TextProperty('QVariantList', notify=_i18n_colorMapOptions, notify_name='_i18n_colorMapOptions')
    def colorMapOptions(self): return color_map_options()

    @Slot(str)
    def setVolumeMode(self, mode):
        if not self._disposed and mode in ("ct", "pet", "fusion") and mode != self._mode:
            self._mode = mode
            self.cancel_drag()
            self._scene_changed()

    @Slot(float)
    def setCtOpacity(self, value):
        if not self._disposed and np.isfinite(value):
            self._ct_opacity = float(np.clip(value, 0, 1))
            self._scene_changed()

    @Slot(float)
    def setPetOpacity(self, value):
        if not self._disposed and np.isfinite(value):
            self._pet_opacity = float(np.clip(value, 0, 1))
            self._scene_changed()

    @Slot(float)
    def setPetThreshold(self, value):
        if not self._disposed and np.isfinite(value):
            self._threshold_fraction = float(np.clip(value / self.petUpper, 0, .99))
            self._scene_changed()

    @Slot(str)
    def setCtPreset(self, value):
        if not self._disposed and value in ("bone", "general", "lung"):
            self._ct_preset = value
            self._set_display_state(replace(self.display_state,
                window=VOLUME_PRESET_BY_ID[value].default_window or self.scene.ct_window))
            self._scene_changed()

    @Slot(str)
    def setPetPalette(self, value):
        if not self._disposed and value in COLOR_MAP_SPECS:
            self._palette = value
            self._scene_changed()

    def _scene_changed(self):
        self.sceneChanged.emit()
        self.displayStateChanged.emit()

    def attach_source(self, source):
        if self._disposed or source._closed:
            return
        self._detach_source()
        self.source_workspace = source
        self._source_open = True
        source.snapshotCommitted.connect(self.accept_snapshot)
        source.sourceClosed.connect(self._detach_source)
        self.accept_snapshot(source._last_result)

    def _detach_source(self):
        if self.source_workspace is not None:
            self.source_workspace.snapshotCommitted.disconnect(self.accept_snapshot)
            self.source_workspace.sourceClosed.disconnect(self._detach_source)
        self.source_workspace = None
        self._source_open = False
        self.sceneChanged.emit()

    @Slot(object)
    def accept_snapshot(self, result):
        if self._disposed or result is None or result.ct_volume is None:
            return
        initial = self.scene is None
        self.scene = result
        self.volume = result.ct_volume
        if initial:
            self._reset_ct_window()
        self._set_status("ready")
        self._scene_changed()

    @Slot()
    def ensureNativeView(self):
        if self._host is not None or self._disposed:
            return
        from qt_dicom_viewer.ui.volume_viewport_host import VolumeViewportHost
        from qt_dicom_viewer.ui.pet_volume_render_backend import PetVolumeRenderBackend
        self._host = VolumeViewportHost(self, lambda widget: PetVolumeRenderBackend(widget, self))
        self.nativeWindowChanged.emit()
        self._host.sync_status()

    def request_render(self):
        # Both volumes have already been decoded by the linked workspace.
        if self.scene is not None and not self._disposed:
            self._set_status("ready")
            self._scene_changed()

    def _reset_ct_window(self):
        if self.scene:
            self._set_display_state(replace(self.display_state,
                window=VOLUME_PRESET_BY_ID[self._ct_preset].default_window or self.scene.ct_window))

    @Slot()
    def resetSceneDisplay(self):
        if self._disposed:
            return
        self._ct_opacity, self._pet_opacity = .25, .8
        self._threshold_fraction, self._ct_preset, self._palette = .1, "bone", "hotIron"
        self._reset_ct_window()
        self._scene_changed()

    def reset_tool_state(self, tool):
        if tool == ToolType.WINDOW:
            self._reset_ct_window()
        elif tool == ToolType.VOLUME_PRESET:
            self.resetSceneDisplay()
        else:
            super().reset_tool_state(tool)

    def reset_all_view_state(self):
        self._set_state(VolumeViewState())
        self.resetSceneDisplay()

    def dispose(self):
        self._detach_source()
        super().dispose()
        self.scene = None
