"""Tab-wide measurement inventory. Locations belong to the measurement, not the cursor."""
from PySide6.QtCore import QObject, Property, Signal, Slot
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from qt_dicom_viewer.model.measure import AngleMeasurement, RoiMeasurement
from qt_dicom_viewer.core.measurement_format import format_measurement


class MeasurementResultsController(QObject):
    changed = Signal()
    _i18n_items = Signal()
    _i18n_message = Signal()

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self._watched = set()
        self._pending = None
        self._message = ""
        self.watch_views()
        tab.viewLayoutChanged.connect(self.watch_views)
        if hasattr(tab, "twoDLayout"):
            tab.twoDLayout.cellsChanged.connect(self.watch_views)

    def watch_views(self):
        current = set(self.tab.viewports_by_id.values())
        for view in self._watched - current:
            if self._pending is not None and self._pending[0] is view:
                self._pending = None
            try:
                view._measure_controller.measurementsChanged.disconnect(self._changed)
                view._measure_controller.selectionChanged.disconnect(self.changed.emit)
                view.imageSourceChanged.disconnect(self._select_pending)
                view.loadStateChanged.disconnect(self._check_failure)
            except RuntimeError:  # The view may already have been destroyed by Qt.
                pass
        self._watched.intersection_update(current)
        for view in self.tab.viewports_by_id.values():
            measure = getattr(view, "_measure_controller", None)
            if measure is None or view in self._watched:
                continue
            self._watched.add(view)
            measure.measurementsChanged.connect(self._changed)
            measure.selectionChanged.connect(self.changed.emit)
            view.imageSourceChanged.connect(self._select_pending)
            view.loadStateChanged.connect(self._check_failure)
        self.changed.emit()

    def _changed(self):
        self.changed.emit()

    def _find(self, key):
        for view in self.tab.viewports_by_id.values():
            measure = getattr(view, "_measure_controller", None)
            if measure:
                for item in measure.committed_measurements:
                    if key == view.viewportId + ":" + item.measurement_id:
                        return view, measure, item
        return None

    @_TextProperty(str, notify=_i18n_message, notify_name="_i18n_message", source_notify="changed")
    def message(self):
        return self._message

    @_TextProperty("QVariantList", notify=_i18n_items, notify_name="_i18n_items", source_notify="changed")
    def items(self):
        result = []
        for view in self.tab.viewports_by_id.values():
            measure = getattr(view, "_measure_controller", None)
            if measure is None:
                continue
            meta = view.viewport_config.series_meta
            for item in measure.committed_measurements:
                info = measure.presentation(item.measurement_id)
                kind = "angle" if isinstance(item, AngleMeasurement) else str(item.kind)
                fmt = lambda v: format_measurement(v, measure._decimal_places)
                value = (f"{fmt(item.metrics.area_mm2)} mm²" if isinstance(item, RoiMeasurement)
                         else f"{fmt(item.angle)}°" if isinstance(item, AngleMeasurement)
                         else "" if kind == "arrow" else f"{fmt(item.length_mm)} mm")
                source = measure.source(item.measurement_id)
                phase = source.get("parameters", {}).get("phase_identifier")
                if phase in meta.phase_identifiers:
                    phase = meta.phase_identifiers.index(phase) + 1
                view_type = view.viewport_config.viewport_type.value
                view_label = {"stack": _msg("layout.originalSlices"), "axial": _msg("plane.axial"),
                              "coronal": _msg("plane.coronal"), "sagittal": _msg("plane.sagittal")}.get(view_type, view_type)
                role = view.viewportRole
                group = (meta.series_description or meta.modality) + " · " + view_label
                if role not in ("", "image", "axial", "coronal", "sagittal"):
                    group += " · " + role
                result.append(dict(key=view.viewportId+":"+item.measurement_id,
                    name=measure.measurement_name(item), value=value,
                    group=group,
                    location=_msg("results.slice", value1=item.slice_index+1) +
                        (" · " + _msg("results.phase", value1=phase) if phase is not None else ""),
                    hidden=info["hidden"], locked=info["locked"],
                    selected=measure.selectedMeasurementId == item.measurement_id))
        return result

    @Slot(str, str)
    def rename(self, key, name):
        found = self._find(key)
        if found:
            found[1].update_presentation(found[2].measurement_id, name=name.strip()[:120])

    @Slot(str, bool)
    def setHidden(self, key, value):
        found = self._find(key)
        if found:
            found[1].update_presentation(found[2].measurement_id, hidden=value)

    @Slot(str, bool)
    def setLocked(self, key, value):
        found = self._find(key)
        if found:
            found[1].update_presentation(found[2].measurement_id, locked=value)

    @Slot(str)
    def remove(self, key):
        found = self._find(key)
        if found:
            found[1].delete_measurement(found[2].measurement_id)

    @Slot(str)
    def locate(self, key):
        self._pending = None
        found = self._find(key)
        if not found:
            return
        view, measure, item = found
        self.tab.pausePlayback()
        self.tab.activateViewport(view.viewportId)
        if measure.presentation(item.measurement_id)["hidden"]:
            measure.update_presentation(item.measurement_id, hidden=False)
        if measure.frame_for(item.measurement_id) == measure.frame_key and not view.render_pending:
            measure.select_completed(item.measurement_id)
            self._message = ""
            self.changed.emit()
            return
        source = measure.source(item.measurement_id)
        # Legacy stack records can be located by a verified instance; oblique
        # and projected records require their original sampling parameters.
        if not source and str(view.viewport_config.viewport_type.value) == "stack":
            from dataclasses import replace
            from qt_dicom_viewer.ui.measurement_source import capture_request
            source = capture_request(replace(view._build_render_request(initial=False), slice_index=item.slice_index))
        try:
            owner = getattr(self.tab, "_owners", {}).get(view.viewportId, self.tab)
            self._pending = (view, measure, item.measurement_id)
            owner.navigate_measurement(view, source)
            self._message = ""
        except (ValueError, TypeError, KeyError):
            self._pending = None
            self._message = _msg("results.locationUnavailable")
        self.changed.emit()

    def _check_failure(self):
        if self._pending is not None and self._pending[0].loadState == "error":
            self._pending = None
            self._message = _msg("results.locationUnavailable")
            self.changed.emit()

    def _select_pending(self):
        if self._pending is None:
            return
        view, measure, mid = self._pending
        if view.render_pending:
            return
        self._pending = None
        if measure.frame_for(mid) == measure.frame_key:
            measure.select_completed(mid)
        else:
            self._message = _msg("results.locationUnavailable")
        self.changed.emit()
