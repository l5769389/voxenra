"""A PET-only volume tab with quantitative display and independent crop state."""
from voxplane.i18n import message as _msg
from voxplane.i18n.qt import translated_property as _TextProperty
import uuid
import numpy as np
from PySide6.QtCore import Property, Signal, Slot
from voxplane.core.pseudocolor import COLOR_MAP_SPECS, color_map_options
from voxplane.model import ToolType
from voxplane.model.render_models import VolumeLoadRequest
from .volume_viewport_controller import VolumeViewportController


class StandalonePetVolumeController(VolumeViewportController):
    _i18n_colorMapOptions = Signal()
    _i18n_petUnit = Signal()
    _i18n_petUnitOptions = Signal()

    petDisplayChanged = Signal()

    def __init__(self, config, tools, parent=None):
        super().__init__(config, tools, parent)
        self._unit = None
        self._upper = 1.
        self._threshold_fraction = .1
        self._opacity = .8
        self._palette = tools.settingsController.values["colormap"]["pet"]
        self._initial_palette = self._palette
        self._initial_unit = None
        self._initial_upper = None
        self._reset_display_pending = False
        self._workspace_upper = None

    def restore_pet_display(self, state):
        self._unit = state["_unit"]
        self._upper = state["_upper"]
        self._threshold_fraction = state["_threshold_fraction"]
        self._opacity, self._palette = state["_opacity"], state["_palette"]
        if self.petUnitId != self._unit:
            if self._unit not in {o["unitId"] for o in self.petUnitOptions}:
                raise ValueError(_msg('text.0558'))
            self._workspace_upper = self._upper
            self._request_volume()
        else:
            self._display_changed()

    @Property(bool, constant=True)
    def isStandalonePetVolume(self): return True

    @Property(float, notify=petDisplayChanged)
    def petUpper(self): return self._upper

    @Property(float, notify=petDisplayChanged)
    def petThreshold(self): return self._threshold_fraction * self._upper

    @Property(float, notify=petDisplayChanged)
    def petOpacity(self): return self._opacity

    @Property(str, notify=petDisplayChanged)
    def petPalette(self): return self._palette

    @_TextProperty(str, notify=_i18n_petUnit, notify_name='_i18n_petUnit', source_notify='petDisplayChanged')
    def petUnit(self): return self.volume.pixel_value_meta.unit if self.volume else ""

    @Property(str, notify=petDisplayChanged)
    def petUnitId(self): return self.volume.pixel_value_meta.unit_id if self.volume else ""

    @_TextProperty('QVariantList', notify=_i18n_petUnitOptions, notify_name='_i18n_petUnitOptions', source_notify='petDisplayChanged')
    def petUnitOptions(self):
        return [dict(unitId=o.unit_id, label=o.label) for o in self.volume.pixel_value_meta.unit_options
                if o.available] if self.volume else []

    @_TextProperty('QVariantList', notify=_i18n_colorMapOptions, notify_name='_i18n_colorMapOptions')
    def colorMapOptions(self): return color_map_options()

    def _display_changed(self):
        self.petDisplayChanged.emit()
        self.displayStateChanged.emit()

    @Slot(float)
    def setPetUpper(self, value):
        if not self._disposed and np.isfinite(value) and value > 0:
            self._upper = float(value)
            self._display_changed()

    @Slot(float)
    def setPetThreshold(self, value):
        if not self._disposed and np.isfinite(value) and 0 <= value < self._upper:
            self._threshold_fraction = float(value / self._upper)
            self._display_changed()

    @Slot(float)
    def setPetOpacity(self, value):
        if not self._disposed and np.isfinite(value) and 0 <= value <= 1:
            self._opacity = float(value)
            self._display_changed()

    @Slot(str)
    def setPetPalette(self, value):
        if not self._disposed and value in COLOR_MAP_SPECS:
            self._palette = value
            self._display_changed()

    @Slot(str)
    def setPetUnit(self, value):
        if self._disposed or not self.volume or value == self._unit:
            return
        if value not in {o["unitId"] for o in self.petUnitOptions}:
            return
        self._reset_display_pending = False
        self._unit = value
        self._request_volume()

    def _request_volume(self):
        self._request_id = str(uuid.uuid4())
        self._set_status("loading")
        self.renderRequested.emit(VolumeLoadRequest(request_id=self._request_id,
            viewport_id=self.viewportId, series_uid=self.viewport_config.series_uid,
            value_unit=self._unit))

    def request_render(self):
        if not self._disposed and self.loadState != "loading":
            self._request_volume()

    def handleRenderResult(self, result):
        if not self.accepts_result(result):
            return
        self._request_id = None
        previous, self.volume = self.volume, result.volume
        self._unit = self.volume.pixel_value_meta.unit_id
        if previous is None:
            self._upper = max(.01 if self.volume.pixel_value_meta.is_suv else .001,
                self.volume.default_window.center + self.volume.default_window.width / 2)
            self._initial_unit, self._initial_upper = self._unit, self._upper
        else:
            self._upper *= (self.volume.pixel_value_meta.scale_from_source /
                            previous.pixel_value_meta.scale_from_source)
        if self._reset_display_pending:
            self._upper = self._initial_upper
            self._reset_display_pending = False
        if self._workspace_upper is not None:
            self._upper, self._workspace_upper = self._workspace_upper, None
        # The voxel grid is unchanged by unit conversion: retain camera and mask.
        self._display_changed()
        self._set_status("ready")

    @Slot()
    def ensureNativeView(self):
        if self._host is not None or self._disposed:
            return
        from voxplane.ui.volume_viewport_host import VolumeViewportHost
        from voxplane.ui.standalone_pet_volume_backend import StandalonePetVolumeBackend
        self._host = VolumeViewportHost(self, lambda widget: StandalonePetVolumeBackend(widget, self))
        self.nativeWindowChanged.emit()
        self._host.sync_status()

    @Slot()
    def resetPetDisplay(self):
        if self._disposed or self._initial_unit is None:
            return
        self._threshold_fraction, self._opacity = .1, .8
        self._palette = self._initial_palette
        if self.petUnitId != self._initial_unit or self.loadState == "loading":
            self._reset_display_pending = True
            self._unit = self._initial_unit
            self._request_volume()
        else:
            self._upper = self._initial_upper
        self._display_changed()

    def reset_tool_state(self, tool):
        if tool == ToolType.VOLUME_PRESET:
            self.resetPetDisplay()
        else:
            super().reset_tool_state(tool)

    def reset_all_view_state(self):
        super().reset_all_view_state()
        self.resetPetDisplay()
