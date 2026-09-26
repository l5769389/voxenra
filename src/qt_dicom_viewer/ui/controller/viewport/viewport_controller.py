from PySide6.QtCore import QObject, Property, Signal, Slot

from qt_dicom_viewer.model import RenderResult, ViewportConfig


class ViewportController(QObject):
    """所有 viewport controller 的最小 Qt 接口。"""


    # Publish a display-only image before notifying QML of its new source URL.
    imageUpdateRequested = Signal(str, object)
    renderRequested = Signal(object)
    viewportTypeChanged = Signal()

    def __init__(
        self,
        viewport_config: ViewportConfig,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.viewport_config = viewport_config
        self._mapping_editor = self.displayMappingEditor
        for name in ("overlayChanged", "displayStateChanged", "petDisplayChanged"):
            signal = getattr(self, name, None)
            if signal is not None:
                signal.connect(self.displayMappingChanged)

    displayMappingChanged = Signal()
    displayMappingKindChanged = Signal()

    @Slot()
    def closeTab(self):
        """Close the owning tab, including a reference view in an MPR layout."""
        owner = self.parent()
        while owner is not None:
            config = getattr(owner, "tab_config", None)
            if config is not None and config.tab_id == self.viewport_config.tab_id:
                owner.closeRequested.emit()
                return
            owner = owner.parent()

    @Property(str, notify=displayMappingKindChanged)
    def displayMappingEditor(self):
        # Editor structure must not depend on high-frequency range/layout signals.
        # Rebuilding a Loader during viewport resize creates a QML binding cycle.
        if self.viewportType == 'volume':
            return 'transfer'
        frame = self._mapping_frame()
        if frame is not None and frame.supplemental_overlay is not None:
            return 'palette'
        series = self.viewport_config.series_meta
        if series.modality.upper() == 'PT':
            return 'pet-range'
        if not series.supports_ct_analysis:
            return 'scalar-range'
        return 'window'


    def _mapping_frame(self):
        return getattr(self, '_frame_meta', None) or getattr(self, '_mapping_frame_meta', None)

    @Property('QVariantMap', notify=displayMappingChanged)
    def displayMapping(self):
        from qt_dicom_viewer.model.display_mapping import capabilities, DisplayMappingIntent
        from qt_dicom_viewer.core.color_maps import COLOR_MAPS
        import numpy as np
        frame = self._mapping_frame()
        series = self.viewport_config.series_meta
        volume = getattr(self, "volume", None) if self.viewportType == "volume" else None
        meta = frame.pixel_value_meta if frame else volume.pixel_value_meta if volume else None
        caps = capabilities(modality=series.modality.upper(), value_meta=meta,
            supplemental=frame is not None and frame.supplemental_overlay is not None,
            hu_analysis=series.supports_ct_analysis, volume=self.viewportType == "volume")
        state = getattr(self, '_state', None)
        intent = getattr(state, 'display_mapping', DisplayMappingIntent())
        palette = frame.source_palette if frame else None
        unit = caps.unit
        mode = 'custom' if intent.applies_to(unit) else 'source'
        lower, upper = 0., 1.
        if palette:
            lower, upper = palette.lower, palette.upper
        else:
            lower, upper = getattr(self, '_mapping_default_range', (0., 1.))
        if mode == 'custom':
            lower, upper = intent.lower, intent.upper
        window = getattr(state, 'window', None)
        if caps.kind == 'window' and window:
            lower, upper = window.center-window.width/2, window.center+window.width/2
        if caps.fixed_lower is not None:
            lower = caps.fixed_lower
            upper = getattr(self, 'petDisplayUpper', upper)
            visible = getattr(getattr(self, '_pet_display', None), 'visible', None)
            unit = visible.meta.unit if visible else unit
        colors = ['#{:02x}{:02x}{:02x}'.format(*rgb) for rgb in palette.colors] if palette else list(
            COLOR_MAPS.get(getattr(self, 'activeColorMap', 'grayscale'), COLOR_MAPS['grayscale'])[1])
        return dict(kind=caps.kind, domain=caps.domain, unit=unit, mode=mode,
            lower=lower, upper=upper, colors=colors, presets=caps.presets,
            customRange=caps.custom_range, canCustomize=frame is not None and caps.custom_range
                and (caps.kind != 'palette' or palette is not None),
            grayscaleBackground=caps.grayscale_background,
            warning=meta.warning or '' if meta else '', fixedLower=caps.fixed_lower is not None)

    def accept_mapping_frame(self, frame):
        from dataclasses import replace
        from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent
        self._mapping_frame_meta = frame
        editor = self.displayMappingEditor
        if editor != self._mapping_editor:
            self._mapping_editor = editor
            self.displayMappingKindChanged.emit()
        if not self.viewport_config.series_meta.supports_ct_analysis and frame.source_palette is None:
            import numpy as np
            pixels = getattr(self, '_modality_pixel', None)
            if pixels is None:
                pixels = next(iter(getattr(self, '_display_values', {}).values()), None)
            finite = pixels[np.isfinite(pixels)] if pixels is not None else np.array([])
            if finite.size:
                low, high = (float(v) for v in np.percentile(finite, [1,99]))
                self._mapping_default_range = (low, max(high, low+0.001))
        state = getattr(self, '_state', None)
        if state is not None and state.display_mapping.mode == 'custom' and (
                state.display_mapping.unit != frame.pixel_value_meta.unit or frame.pixel_value_meta.quantification == 'color'):
            self._state = replace(state, display_mapping=DisplayMappingIntent())
        self.displayMappingChanged.emit()

    def _set_display_mapping(self, intent):
        from dataclasses import replace
        if intent == self._state.display_mapping:
            self.displayMappingChanged.emit()
            return
        self._state = replace(self._state, display_mapping=intent)
        self.displayMappingChanged.emit()
        if hasattr(self, 'overlayChanged'):
            self.overlayChanged.emit()
        if hasattr(self, 'refresh_window_image'):
            self.refresh_window_image()
        self.request_render()

    @Slot(str)
    def setDisplayMappingMode(self, mode):
        from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent
        info = self.displayMapping
        if mode == 'source':
            self._set_display_mapping(DisplayMappingIntent())
        elif mode == 'custom' and info['canCustomize']:
            self._set_display_mapping(DisplayMappingIntent('custom', info['lower'], info['upper'], info['unit']))

    @Slot(float, float)
    def setDisplayRange(self, lower, upper):
        from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent
        info = self.displayMapping
        if not info['canCustomize'] or info['mode'] != 'custom':
            return
        try:
            intent = DisplayMappingIntent('custom', lower, upper, info['unit'])
        except ValueError:
            self.displayMappingChanged.emit()
            return
        self._set_display_mapping(intent)

    def mapping_drag_window(self, window):
        from qt_dicom_viewer.model import WindowLevel
        info = self.displayMapping
        if not info['customRange']:
            return window
        return WindowLevel((info['lower']+info['upper'])/2, info['upper']-info['lower']) if info['mode'] == 'custom' else None

    def apply_mapping_drag(self, window):
        if not self.displayMapping['customRange']:
            return False
        self.setDisplayRange(window.center-window.width/2, window.center+window.width/2)
        return True

    @Property(str, constant=True)
    def viewportId(self) -> str:
        return self.viewport_config.viewport_id

    @Property(str, notify=viewportTypeChanged)
    def viewportType(self) -> str:
        return self.viewport_config.viewport_type.value

    @Property(str, constant=True)
    def viewportRole(self):
        return self.viewport_config.role

    @Property(QObject, constant=True)
    def reconstructionController(self):
        return getattr(self, "owner", None)

    @Property(QObject, constant=True)
    def workspaceTab(self):
        owner = self.parent()
        return getattr(owner, "_workspace_tab", owner) if hasattr(owner, "focusSingleViewport") else None

    def request_first_loader(self) -> None:
        raise NotImplementedError

    def request_render(self) -> None:
        raise NotImplementedError

    def handleRenderResult(self, result: RenderResult) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        """关闭视口时释放后台任务；没有后台资源的视口无需处理。"""
