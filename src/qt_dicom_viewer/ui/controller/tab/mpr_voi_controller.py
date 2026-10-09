"""Tab-owned VOIs shared by CT and PET MPR viewports."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer
from PySide6.QtGui import QColor

from qt_dicom_viewer.core.segmentation_masks import evaluate_mask
from qt_dicom_viewer.core.measurement_format import format_measurement
from qt_dicom_viewer.core.mpr_voi import (automatic_depth, box_from_drag, circle_from_drag,
                                         editing_handles, evaluate_voi, plane_polygon)
from qt_dicom_viewer.ui.segmentation_overlay_renderer import SegmentationOverlayRenderer


class MprVoiController(QObject):
    _i18n_error = Signal()
    _i18n_items = Signal()
    _i18n_selected = Signal()

    changed = Signal()
    editsChanged = Signal()  # Committed data only, not display/selection/results.
    selectionChanged = Signal()
    overlaysChanged = Signal()
    masksChanged = Signal()
    itemsChanged = Signal()
    completed = Signal(object)

    def __init__(self, tools, parent=None):
        super().__init__(parent)
        self.tools = tools
        self.records = []
        self._phase = None
        self._phase_ready = True
        self.sources = {}
        self.evaluations = {}
        self._overlay_cache = {}
        self._contour_cache = {}
        self._mask_renderer = SegmentationOverlayRenderer()
        self.changed.connect(self.overlaysChanged.emit)
        self.changed.connect(self.masksChanged.emit)
        self._selected = ""
        self._enabled = True
        self._draft = None
        self._edit_mode = "paint" if tools._modality == "MR" else "threshold"
        self._brush_diameter = 5.0
        self._brush_relative = False
        self._brush_percent = 3.0
        self._brush_sphere = False
        self._display_mode = "fill-outline"
        self._fill_opacity = 30
        self._error = ""
        self._revision = 0
        self._running = False
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mpr-voi")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._launch)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self.masksChanged.emit)
        self.completed.connect(self._accept)
        tools.activeInteractionChanged.connect(self.cancel)
        tools.activeInteractionChanged.connect(self._activate)
        tools.settingsController.sectionChanged.connect(self._preferences_changed)

    def _preferences_changed(self, section):
        if section == "measurement":
            self.changed.emit()

    @Property(str, notify=changed)
    def editMode(self):
        return self._edit_mode

    @Property(float, notify=changed)
    def brushDiameter(self):
        return self._brush_diameter

    @Property(bool, notify=changed)
    def brushRelative(self):
        return self._brush_relative

    @Property(float, notify=changed)
    def brushPercent(self):
        return self._brush_percent

    @Slot(bool)
    def setBrushRelative(self, enabled):
        self.cancel()
        self._brush_relative = enabled
        self.changed.emit()
        self.selectionChanged.emit()

    @Slot(float)
    def setBrushPercent(self, value):
        if np.isfinite(value) and 1 <= value <= 25:
            self._brush_percent = value
            self.changed.emit()
            self.selectionChanged.emit()

    def brush_diameter_for_view(self, viewport):
        if not self._brush_relative:
            return self._brush_diameter
        scale, size = getattr(viewport, "_brush_view_metrics", (0., 0.))
        if not np.isfinite([scale, size]).all() or min(scale, size) <= 0:
            return None
        return size * self._brush_percent / 100 / scale

    @Property(bool, notify=changed)
    def brushSphere(self):
        return self._brush_sphere

    @Slot(str)
    def setEditMode(self, mode):
        if mode == "threshold" and self.tools._modality == "MR":
            return
        if mode in ("threshold", "paint", "erase", "keep", "remove"):
            self.cancel()
            self._edit_mode = mode
            self.changed.emit()
            self.selectionChanged.emit()

    @Slot(float)
    def setBrushDiameter(self, value):
        if np.isfinite(value) and .1 <= value <= 100:
            self._brush_diameter = value
            self.changed.emit()
            self.selectionChanged.emit()

    @Slot(bool)
    def setBrushSphere(self, enabled):
        self._brush_sphere = enabled
        self.changed.emit()
        self.selectionChanged.emit()

    @Property(str, notify=changed)
    def displayMode(self):
        return self._display_mode

    @Property(int, notify=changed)
    def fillOpacity(self):
        return self._fill_opacity

    @Slot(str)
    def setDisplayMode(self, mode):
        if mode in ("fill", "outline", "fill-outline") and mode != self._display_mode:
            self._display_mode = mode
            self.changed.emit()
            self.selectionChanged.emit()

    @Slot(int)
    def setFillOpacity(self, value):
        if 0 <= value <= 100 and value != self._fill_opacity:
            self._fill_opacity = value
            self.changed.emit()
            self.selectionChanged.emit()

    def persistent_selection(self):
        """Workspace tool preferences, separate from undoable segmentation data."""
        return dict(version=1, mode=self._edit_mode, selected=self._selected,
                    diameter=self._brush_diameter, relative=self._brush_relative,
                    percent=self._brush_percent, sphere=self._brush_sphere,
                    enabled=self._enabled, displayMode=self._display_mode,
                    fillOpacity=self._fill_opacity)

    def restore_selection(self, state):
        if not isinstance(state, dict) or state.get("version") != 1:
            return
        self.cancel()
        display_mode = state.get("displayMode")
        if display_mode in ("fill", "outline", "fill-outline"):
            self._display_mode = display_mode
        opacity = state.get("fillOpacity")
        if type(opacity) in (int, float) and np.isfinite(opacity) and 0 <= opacity <= 100:
            self._fill_opacity = round(opacity)
        mode = state.get("mode")
        if mode in ("threshold", "paint", "erase", "keep", "remove"):
            self._edit_mode = "paint" if mode == "threshold" and self.tools._modality == "MR" else mode
        for key, attribute, low, high in (("diameter", "_brush_diameter", .1, 100),
                                           ("percent", "_brush_percent", 1, 25)):
            value = state.get(key)
            if type(value) in (int, float) and np.isfinite(value) and low <= value <= high:
                setattr(self, attribute, float(value))
        for key, attribute in (("relative", "_brush_relative"), ("sphere", "_brush_sphere"),
                               ("enabled", "_enabled")):
            if type(state.get(key)) is bool:
                setattr(self, attribute, state[key])
        selected = state.get("selected")
        if selected == "" or any(r["id"] == selected for r in self.current_records):
            self._selected = selected
        self._overlay_cache.clear()
        self.changed.emit()

    def _next_color(self):
        # Include hidden/imported regions and other phases: hiding a segment
        # must not make its color available to a new one.
        used = {QColor(r["color"]).name().lower() for r in self.records}
        palette = ("#ed55ed", "#43c6dc", "#ffbb55", "#87d980",
                   "#ff7070", "#9292ff", "#e6dc65", "#5fe0b3")
        for color in palette:
            if color not in used:
                return color
        for index in range(len(used) + 1):
            color = QColor.fromHsv((index * 137) % 360, 120 + (index // 360) % 136, 235).name()
            if color not in used:
                return color
        return palette[0]

    @Slot()
    def newSegment(self):
        self.cancel()
        if not self._phase_ready or self._closed:
            return
        viewport = getattr(self.parent(), "activeViewport", None)
        if viewport is not None and (getattr(viewport, "render_pending", False)
                or getattr(viewport, "_voi_phase", self.phaseIndex) != self.phaseIndex):
            return
        volume = getattr(viewport, "_voi_volume", None)
        # A single-source workspace is unambiguous even while the 3D view is active.
        if volume is None and len(self.sources) == 1:
            volume = next(iter(self.sources.values()))
        if volume is None or volume.series_uid not in self.sources:
            return
        from qt_dicom_viewer.core.segmentation_masks import mask_record
        record, result = mask_record(volume, np.zeros((1, 1, 1), bool), (0, 0, 0),
            name=f'{_msg("seg.segmentName")} {len(self.records)+1}',
            color=self._next_color(), phase=self._phase, allow_empty=True, mask_origin="manual")
        self.records.append(record)
        self.evaluations[record["id"]] = result
        self._selected = record["id"]
        self._enabled = True
        self._edit_mode = "paint"
        self.itemsChanged.emit()
        self._commit()
        self.selectionChanged.emit()

    def _begin_refine(self, viewport, column, row):
        from qt_dicom_viewer.core.segmentation_refine import connected_component
        volume, g = viewport._voi_volume, viewport._plane_geometry
        record = self._record()
        if record is not None and (record["kind"] != "segmentation" or record["series"] != volume.series_uid):
            return
        if record is not None and not record["visible"]:
            self._error = _msg("seg.editHidden")
            self.changed.emit()
            return
        result = self.evaluations.get(record["id"]) if record else None
        if record and result is None:
            return
        if result is None and self._edit_mode != "paint":
            self._error = _msg("seg.selectFirst")
            self.changed.emit()
            return
        diameter = self.brush_diameter_for_view(viewport)
        if self._edit_mode in ("paint", "erase") and diameter is None:
            return  # No reliable view scale yet; never guess a physical size.
        mask = result.mask.copy() if result else np.zeros((1, 1, 1), bool)
        empty = result is None or not result.metrics.get("count")
        mask = np.zeros((1, 1, 1), bool) if empty else mask
        offset = result.offset.copy() if not empty else np.clip(np.floor(volume.geometry.patient_to_voxel[:3] @ [*self._patient_point(g, column, row), 1] + .5).astype(int), 0, np.array(volume.modality_pixels.shape)-1)
        self._draft = dict(mode="brush", record=record, viewport=viewport, geometry=g,
            volume=volume, mask=mask, offset=offset, region=None, last=None,
            kind="segmentation", edit=self._edit_mode, changed=False,
            diameter=diameter, sphere=self._brush_sphere,
            color=record["color"] if record else self._next_color(),
            id=record["id"] if record else str(uuid4()))
        try:
            if self._edit_mode in ("keep", "remove"):
                point = self._patient_point(g, column, row)
                seed = np.floor((volume.geometry.patient_to_voxel @ [*point, 1])[:3] + .5).astype(int) - offset
                component = connected_component(mask, seed)
                self._draft["mask"] = component if self._edit_mode == "keep" else mask & ~component
                self._draft["changed"] = not np.array_equal(mask, self._draft["mask"])
            else:
                self.update(viewport, column, row)
        except ValueError:
            self.cancel()
            self._error = _msg("seg.clickInside")
            self.changed.emit()

    @staticmethod
    def _patient_point(g, column, row):
        return (np.asarray(g.image_origin_patient) + column * g.column_spacing * np.asarray(g.column_direction_patient)
                + row * g.row_spacing * np.asarray(g.row_direction_patient))

    def _refined_record(self, d):
        from qt_dicom_viewer.core.segmentation_masks import mask_record
        original = d["record"]
        record, result = mask_record(d["volume"], d["mask"], d["offset"],
            name=original["name"] if original else f'{_msg("seg.segmentName")} {len(self.records)+1}',
            color=d["color"], phase=self._phase, allow_empty=True)
        if original:
            # Preserve identity/source metadata, but replace geometry and pixels.
            record = {**original, **record, "id": original["id"], "unit": original["unit"],
                      "unitLabel": original["unitLabel"]}
            result = evaluate_mask(d["volume"].in_unit(record["unit"]), record)
        record["mask_origin"] = "manual"
        record["id"] = d["id"]
        return record, result

    def _activate(self):
        if self.tools.restoring_selection:
            return
        if self.tools.activeInteraction in ("mpr:segmentation", "mpr:voi"):
            self.tools.setMprProjectionEnabled(False)
            if getattr(self.parent(), "registrationActive", False):
                self.parent().setRegistrationActive(False)
            kind = self.tools.activeInteraction.split(":")[1]
            if self._record() is None or self._record()["kind"] != kind:
                self._selected = next((r["id"] for r in self.current_records if r["kind"] == kind), "")
                self._overlay_cache.clear()
                self.changed.emit()

    @Property(bool, constant=True)
    def canDraw(self):
        return self.tools._modality != "MR"

    @Property(bool, notify=changed)
    def enabled(self):
        return self._enabled

    @Property(bool, notify=changed)
    def busy(self):
        return not self._error and any(r["id"] not in self.evaluations for r in self.current_records)

    @Property(int, notify=changed)
    def phaseIndex(self): return self._phase if self._phase is not None else -1

    @property
    def current_records(self):
        return [r for r in self.records if r.get("phase") == self._phase] if self._phase_ready else []

    def set_phase(self, phase, *, ready=True):
        if self._phase == phase and self._phase_ready == ready:
            return
        self.cancel()
        if self._phase != phase:
            self.sources.clear()
        self._phase, self._phase_ready = phase, ready
        # Invalidate in-flight statistics and masks before accepting new pixels.
        self.evaluations.clear()
        self._mask_renderer.clear()
        self._contour_cache.clear()
        self._selected = next((r["id"] for r in self.current_records if r["kind"] == self.tools.activePanel), "")
        self.itemsChanged.emit()
        self._schedule()

    @_TextProperty(str, notify=_i18n_error, notify_name='_i18n_error', source_notify='changed')
    def error(self):
        return self._error

    @Property(str, notify=changed)
    def selectedId(self):
        return self._selected

    @_TextProperty('QVariantList', notify=_i18n_items, notify_name='_i18n_items', source_notify='itemsChanged')
    def items(self):
        return [dict({key: r[key] for key in ("id", "kind", "name", "color", "visible")},
                     fixedMask="mask" in r) for r in self.current_records]

    @_TextProperty('QVariantMap', notify=_i18n_selected, notify_name='_i18n_selected', source_notify='changed')
    def selected(self):
        record = self._record()
        return self._present(record) if record else {}

    def _record(self):
        return next((r for r in self.current_records if r["id"] == self._selected), None)

    def _present(self, record):
        result = self.evaluations.get(record["id"])
        metrics = result.metrics if result else {}
        unit = record["unitLabel"]
        places = self.tools.settingsController.section("measurement")["decimalPlaces"]
        fmt = lambda value: format_measurement(value, places, missing="--")
        minimum, maximum = result.value_range if result else record.get("valueRange", (0., 1000.))
        return dict(fixedMask="mask" in record, id=record["id"], kind=record["kind"], name=record["name"], color=record["color"],
            visible=record["visible"], depth=record["region"].size[2], threshold=record["threshold"],
            diameter=record["region"].size[0], depthAuto=record["depthAuto"],
            percent=record["percent"], pet=record["pet"], unit=unit, unitId=record["unit"],
            unitOptions=record["unitOptions"], depthMax=record["depthMax"],
            fraction=fmt(metrics.get("fraction")) + " %",
            thresholdMin=min(minimum, record["threshold"]),
            thresholdMax=max(maximum, minimum + 1, record["threshold"]),
            rule=(_msg("seg.fixedMask") if "mask" in record else _msg('text.0566') if record["kind"] == "voi" else
                  f"{unit} ≥ {fmt(result.threshold) if result else '--'}"),
            metrics=[dict(label=label, value=value) for label, value in (
                ("MEAN", fmt(metrics.get("mean"))),
                ("MAX", fmt(metrics.get("maximum"))),
                ("MIN", fmt(metrics.get("minimum"))),
                ("SD", fmt(metrics.get("sd"))),
                ("VOL · cm³", fmt(metrics.get("volume"))),
                (_msg('text.0567'), str(metrics.get("count", "--"))))])

    def set_source(self, volume):
        if volume is None:
            return
        old = self.sources.get(volume.series_uid)
        self.sources[volume.series_uid] = volume
        if old is not None and old.modality_pixels is volume.modality_pixels and old.geometry == volume.geometry:
            return
        changed = [r["id"] for r in self.current_records if r["series"] == volume.series_uid]
        if changed:
            for key in changed:
                self.evaluations.pop(key, None)
            self._schedule()

    def edit_target(self, viewport, column, row, tolerance):
        """The same geometric hit test drives both hover and drag start."""
        if self.tools.activePanel == "segmentation" and self._edit_mode != "threshold":
            return None
        g = viewport._plane_geometry
        record = self._record()
        if (not self._enabled or g is None or not record or not record["visible"]
                or "mask" in record or record["kind"] != self.tools.activePanel or not np.isfinite([column, row]).all()):
            return None
        region = record["region"]
        if not editing_handles(region, g):
            return None
        local = np.asarray(region.center) - g.image_origin_patient
        center = np.array([local @ region.axes[0] / g.column_spacing,
                           local @ region.axes[1] / g.row_spacing])
        half = np.asarray(region.size[:2]) / [g.column_spacing, g.row_spacing] / 2
        delta = np.array([column, row]) - center
        opposite = None
        if region.shape == "ellipsoid":
            distance = np.linalg.norm(delta / half)
            edge_distance = np.linalg.norm(delta - delta / distance) if distance > 1e-9 else float("inf")
            mode = "radius" if edge_distance <= tolerance else "move" if distance < 1 else ""
        else:
            corners = [center + half * signs for signs in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            hit = next((i for i, p in enumerate(corners) if np.linalg.norm(p - [column, row]) <= tolerance), None)
            mode = "resize" if hit is not None else "move" if np.all(np.abs(delta) < half) else ""
            if hit is not None:
                opposite = corners[(hit + 2) % 4]
        return dict(mode=mode, center=center, opposite=opposite) if mode else None

    def begin(self, viewport, column, row, tolerance):
        if self.tools.activePanel == "segmentation" and self._edit_mode != "threshold":
            if (self._phase_ready and self._enabled and viewport._plane_geometry is not None
                    and viewport._voi_volume is not None
                    and not getattr(viewport, "render_pending", False)
                    and getattr(viewport, "_voi_phase", self.phaseIndex) == self.phaseIndex):
                self.cancel()
                self._begin_refine(viewport, column, row)
            return
        if (viewport.viewport_config.series_meta.modality.upper() == "MR"
                or not self._phase_ready or not self._enabled or viewport._plane_geometry is None or viewport._voi_volume is None
                or getattr(viewport, "_voi_phase", self.phaseIndex) != self.phaseIndex):
            return
        if not np.isfinite([column, row]).all():
            return
        geometry = viewport._plane_geometry
        # Hover and press must resolve to exactly the same operation.
        record = self._record()
        target = self.edit_target(viewport, column, row, tolerance)
        if target:
            self._draft = dict(viewport=viewport, geometry=geometry, start=(column, row),
                region=record["region"], original=record["region"], record=record, kind=record["kind"], **target)
            self.masksChanged.emit()
            return
        self._draft = dict(viewport=viewport, geometry=geometry, start=(column, row), region=None,
                           original=None, record=None, mode="new", opposite=None, kind=self.tools.activePanel)

    def update(self, viewport, column, row):
        d = self._draft
        if d and d["mode"] == "brush":
            if d["viewport"] is not viewport or d["edit"] in ("keep", "remove"):
                return
            from qt_dicom_viewer.core.segmentation_refine import brush
            g = d["geometry"]
            if not (0 <= column < g.columns and 0 <= row < g.rows):
                d["last"] = None
                return
            point = self._patient_point(g, column, row)
            normal = None if d["sphere"] else np.cross(g.column_direction_patient, g.row_direction_patient)
            try:
                mask, offset = brush(d["mask"], d["offset"], d["volume"].geometry,
                    d["volume"].modality_pixels.shape, point if d["last"] is None else d["last"], point,
                    d["diameter"], erase=d["edit"] == "erase", normal=normal)
                changed = mask is not d["mask"]
                d["changed"] |= changed
                d.update(mask=mask, offset=offset, last=point)
                if changed and not self._preview_timer.isActive():
                    self._preview_timer.start()
            except ValueError:
                self.cancel()
                self._error = _msg("seg.tooLarge")
                self.changed.emit()
            return
        if not d or d["viewport"] is not viewport or not np.isfinite([column, row]).all():
            return
        g = d["geometry"]
        column, row = float(np.clip(column, -.5, g.columns - .5)), float(np.clip(row, -.5, g.rows - .5))
        if d["mode"] == "move":
            delta = np.array([column, row]) - d["start"]
            shift = (delta[0] * g.column_spacing * np.asarray(g.column_direction_patient)
                     + delta[1] * g.row_spacing * np.asarray(g.row_direction_patient))
            d["region"] = replace(d["original"], center=tuple(np.asarray(d["original"].center) + shift))
        else:
            start = d["opposite"] if d["mode"] == "resize" else d["start"]
            depth = d["original"].size[2] if d["original"] else max(.1, g.navigation_spacing)
            if d["kind"] == "voi":
                start = d["center"] if d["mode"] == "radius" else start
                distance = np.linalg.norm((np.array([column, row]) - start) * [g.column_spacing, g.row_spacing])
                if distance < max(.05, min(g.column_spacing, g.row_spacing) * .25):
                    d["region"] = d["original"]
                    self._overlay_cache.clear()
                    self.overlaysChanged.emit()
                    return
                region = circle_from_drag(g, start, (column, row), depth)
            else:
                if abs(column-start[0]) < .5 or abs(row-start[1]) < .5:
                    d["region"] = d["original"]
                    self._overlay_cache.clear()
                    self.overlaysChanged.emit()
                    return
                region = box_from_drag(g, start, (column, row), depth)
            if d["record"] is None or d["record"]["depthAuto"]:
                region = replace(region, size=(*region.size[:2], automatic_depth(region, g.navigation_spacing)))
            d["region"] = region
        self._overlay_cache.clear()
        self.overlaysChanged.emit()

    def finish(self, viewport, column, row):
        self.update(viewport, column, row)
        d = self._draft
        if not d or d["viewport"] is not viewport:
            return
        self._preview_timer.stop()
        self._draft = None
        if d["mode"] == "brush":
            self._mask_renderer.discard(d["id"])
            if d["record"] is None and not d["mask"].any():
                self.masksChanged.emit()
                return
            if d["changed"]:
                record, result = self._refined_record(d)
                from qt_dicom_viewer.core.workspace_state import MAX_MASK_VOXELS
                if sum(r["mask"].size for r in self.records if "mask" in r and r is not d["record"]) + record["mask"].size > MAX_MASK_VOXELS:
                    self._error = _msg("seg.tooLarge")
                    self.changed.emit()
                    return
                if d["record"] is not None:
                    self.records = [record if r is d["record"] else r for r in self.records]
                else:
                    self.records.append(record)
                self._selected = record["id"]
                self.evaluations[record["id"]] = result
                self.itemsChanged.emit()
                self._commit()
            else:
                self.masksChanged.emit()
            return
        if d["region"] is None:
            return
        if d["record"]:
            d["record"]["region"] = d["region"]
            d["record"]["depthMax"] = max(d["record"]["depthMax"], *d["region"].size)
            self.evaluations.pop(d["record"]["id"], None)
        else:
            volume = viewport._voi_volume
            meta = volume.pixel_value_meta
            pet = viewport.viewport_config.series_meta.modality.upper() == "PT"
            kind = self.tools.activePanel
            key = str(uuid4())
            self.records.append(dict(id=key, region=d["region"], kind=kind, series=volume.series_uid, phase=self._phase,
                depthAuto=True, normalSpacing=d["geometry"].navigation_spacing,
                name=(_msg('text.0276') if kind == "segmentation" else "VOI") + f" {len(self.records)+1}",
                color=self._next_color(), visible=True,
                unit=meta.unit_id, unitLabel=meta.unit or ("HU" if viewport.viewport_config.series_meta.modality.upper() == "CT" else _msg('text.0568')),
                unitOptions=[dict(id=o.unit_id, label=o.unit) for o in meta.unit_options if o.available],
                pet=pet, threshold=2.5 if meta.is_suv else 300. if not pet else 0., percent=False,
                depthMax=max(d["region"].size[2], float(np.linalg.norm(
                    np.asarray(volume.modality_pixels.shape) * [volume.geometry.slice_spacing,
                    volume.geometry.row_spacing, volume.geometry.column_spacing])))))
            self._selected = key
            self.itemsChanged.emit()
        self._commit()

    @Slot()
    def cancel(self):
        self._preview_timer.stop()
        if self._draft:
            if self._draft["mode"] == "brush":
                self._mask_renderer.discard(self._draft["id"])
            self._draft = None
            self._overlay_cache.clear()
            self.changed.emit()

    @Slot(bool)
    def setEnabled(self, enabled):
        self._enabled = enabled
        self.cancel()
        self._overlay_cache.clear()
        self.changed.emit()
        self.selectionChanged.emit()

    @Slot(str)
    def select(self, key):
        if key == self._selected and self._record() and self.tools.activePanel == self._record()["kind"]:
            return
        self.cancel()
        if any(r["id"] == key for r in self.current_records):
            self._selected = key
            self.tools.activateTool(self._record()["kind"])
            self._overlay_cache.clear()
            self.changed.emit()
            self.selectionChanged.emit()

    def add_masks(self, records, evaluations):
        existing = {(r.get("source_seg_uid"), r.get("source_segment_number"), r.get("phase"))
                    for r in self.records if r.get("source_seg_uid")}
        if any((r.get("source_seg_uid"), r.get("source_segment_number"), r.get("phase")) in existing
               for r in records if r.get("source_seg_uid")):
            raise ValueError(_msg("seg.alreadyImported"))
        self.cancel()
        self.records.extend(records)
        self.evaluations.update(evaluations)
        self._selected = records[0]["id"]
        self._enabled = True
        self.itemsChanged.emit()
        self._commit()

    @Slot(str, str)
    def setColor(self, key, color):
        if not QColor(color).isValid():
            return
        for record in self.current_records:
            if record["id"] == key:
                record["color"] = QColor(color).name()
                self._overlay_cache.clear()
                self.itemsChanged.emit()
                self.changed.emit()
                self.editsChanged.emit()
                return

    @Slot(str)
    def rename(self, name):
        if self._record():
            self._record()["name"] = name[:120]
            self.itemsChanged.emit()
            self.changed.emit()
            self.editsChanged.emit()

    @Slot(str, str)
    def renameItem(self, key, name):
        for record in self.current_records:
            if record["id"] == key:
                record["name"] = name.strip()[:120] or record["name"]
                self.itemsChanged.emit()
                self.changed.emit()
                self.editsChanged.emit()
                return

    @Slot(float)
    def setDepth(self, value):
        record = self._record()
        if record and "mask" not in record and np.isfinite(value) and .1 <= value <= record["depthMax"]:
            record["depthAuto"] = False
            record["region"] = replace(record["region"], size=(*record["region"].size[:2], value))
            self._invalidate_selected()

    @Slot(bool)
    def setAutoDepth(self, enabled):
        record = self._record()
        if record is None or "mask" in record or record["depthAuto"] == enabled:
            return
        record["depthAuto"] = enabled
        if enabled:
            region = record["region"]
            record["region"] = replace(region, size=(*region.size[:2], automatic_depth(region, record["normalSpacing"])))
        self._invalidate_selected()

    @Slot(float)
    def setDiameter(self, diameter):
        record = self._record()
        if record and record["kind"] == "voi" and np.isfinite(diameter) and .1 <= diameter <= record["depthMax"]:
            depth = diameter if record["depthAuto"] else record["region"].size[2]
            record["region"] = replace(record["region"], size=(diameter, diameter, depth))
            self._invalidate_selected()

    @Slot(float)
    def setThreshold(self, value):
        r = self._record()
        if r and "mask" not in r and np.isfinite(value) and (not r["percent"] or 0 <= value <= 100):
            r["threshold"] = value
            self._invalidate_selected()

    @Slot(bool)
    def setPercent(self, enabled):
        r = self._record()
        if r and "mask" not in r and r["percent"] != enabled:
            result = self.evaluations.get(r["id"])
            r["percent"] = enabled
            r["threshold"] = 40. if enabled else result.threshold if result else 0.
            self._invalidate_selected()

    @Slot(str)
    def setUnit(self, unit):
        r = self._record()
        if not r or unit == r["unit"]:
            return
        option = next((o for o in r["unitOptions"] if o["id"] == unit), None)
        if option:
            r["unit"], r["unitLabel"] = unit, option["label"]
            # Per-slice SUV factors can differ. An absolute threshold is not
            # safely convertible by a single global multiplier; reset explicitly.
            if not r["percent"] and "mask" not in r:
                r["threshold"] = 2.5 if unit.startswith("suv") else 0.
            self._invalidate_selected()

    @Slot(str)
    def toggleVisible(self, key):
        for r in self.current_records:
            if r["id"] == key:
                r["visible"] = not r["visible"]
        self.itemsChanged.emit()
        self._overlay_cache.clear()
        self.changed.emit()
        self.editsChanged.emit()

    @Slot(str)
    def remove(self, key):
        if not any(r["id"] == key for r in self.current_records):
            return
        self.cancel()
        self.records = [r for r in self.records if r["id"] != key]
        self.itemsChanged.emit()
        self.evaluations.pop(key, None)
        if self._selected == key:
            self._selected = self.current_records[-1]["id"] if self.current_records else ""
        self._commit()

    @Slot(str)
    def clear(self, kind):
        for key in [r["id"] for r in self.current_records if not kind or r["kind"] == kind]:
            self.remove(key)

    def _invalidate_selected(self):
        self.evaluations.pop(self._selected, None)
        self._commit()

    def _commit(self):
        self.editsChanged.emit()
        self._schedule()

    def _schedule(self):
        self._revision += 1
        self._error = ""
        self._overlay_cache.clear()
        ids = {r["id"] for r in self.records}
        self._contour_cache = {k: v for k, v in self._contour_cache.items() if k[1] in ids}
        self._mask_renderer.retain(self.evaluations)
        self.changed.emit()
        if not self._closed:
            self._timer.start()

    def _launch(self):
        if self._closed or self._running or not self._phase_ready:
            return
        revision = self._revision
        jobs = [(r.copy(), self.sources[r["series"]]) for r in self.current_records
                if r["id"] not in self.evaluations and r["series"] in self.sources]
        if not jobs:
            return
        self._running = True
        def calculate():
            results = {}
            try:
                for record, volume in jobs:
                    if "mask" in record:
                        results[record["id"]] = evaluate_mask(volume.in_unit(record["unit"]), record)
                        continue
                    results[record["id"]] = evaluate_voi(volume.in_unit(record["unit"]), record["region"],
                        threshold=record["threshold"] if record["kind"] == "segmentation" else None,
                        percent=record["percent"], pet=record["pet"])
                return revision, results, ""
            except Exception as error:
                return revision, {}, error_message(error)
        future = self._executor.submit(calculate)
        def done(f):
            if not self._closed:
                self.completed.emit(f.result())
        future.add_done_callback(done)

    @Slot(object)
    def _accept(self, payload):
        self._running = False
        revision, results, error = payload
        if self._closed:
            return
        if revision == self._revision:
            self.evaluations.update(results)
            for record in self.records:
                if record["id"] in results:
                    record["valueRange"] = results[record["id"]].value_range
            self._error = error
            self._overlay_cache.clear()
            self.changed.emit()
        else:
            self._launch()

    def overlays(self, viewport):
        g = viewport._plane_geometry
        if (not self._enabled or g is None or not self._phase_ready
                or getattr(viewport, "_voi_phase", self.phaseIndex) != self.phaseIndex):
            return []
        key = (viewport.viewportId, g)
        if key in self._overlay_cache:
            return self._overlay_cache[key]
        items = []
        for r in self.current_records:
            if not r["visible"] or "mask" in r:
                continue
            if self._draft and self._draft["mode"] == "brush" and self._draft["record"] is r:
                continue
            box = self._draft["region"] if self._draft and self._draft["record"] is r else r["region"]
            cache_key = (viewport.viewportId, r["id"])
            signature = (g, box, self._selected, r["color"])
            cached = self._contour_cache.get(cache_key)
            if cached is None or cached[0] != signature:
                item = dict(id=r["id"], polygon=plane_polygon(box, g), color=r["color"],
                            selected=r["id"] == self._selected, handles=editing_handles(box, g), fill=r["kind"] == "voi")
                self._contour_cache[cache_key] = (signature, item)
            else:
                item = cached[1]
            if item["polygon"]:
                items.append(item)
        if self._draft and self._draft["record"] is None and self._draft["region"]:
            polygon = plane_polygon(self._draft["region"], g)
            if polygon:
                items.append(dict(id="draft", polygon=polygon, color=self._next_color(), source="", selected=True,
                                  handles=editing_handles(self._draft["region"], g), fill=True))
        # A view can navigate through many planes; retain only its latest geometry.
        self._overlay_cache = {k: v for k, v in self._overlay_cache.items() if k[0] != viewport.viewportId}
        self._overlay_cache[key] = items
        return items

    def masks(self, viewport):
        """Raster masks update on results/slice changes, never on pointer moves."""
        g = viewport._plane_geometry
        if (not self._enabled or g is None or not self._phase_ready
                or getattr(viewport, "_voi_phase", self.phaseIndex) != self.phaseIndex):
            return []
        items = []
        records = self.current_records
        preview = None
        if self._draft and self._draft["mode"] == "brush":
            from qt_dicom_viewer.core.mpr_voi import VoiEvaluation
            d = self._draft
            record = dict(id=d["id"], color=d["color"], visible=True, kind="segmentation")
            preview = VoiEvaluation(d["mask"], d["offset"], d["volume"].geometry, {}, None, (0, 0))
            records = [record if r is d["record"] else r for r in records]
            if d["record"] is None:
                records = [*records, record]
        for record in records:
            result = self.evaluations.get(record["id"])
            if preview is not None and record["id"] == self._draft["id"]:
                result = preview
            if (not record["visible"] or record["kind"] != "segmentation" or result is None
                    or (self._draft and self._draft["mode"] != "brush" and self._draft["record"] is record)):
                continue
            source = self._mask_renderer.source(viewport.viewportId, record["id"], result, g,
                                                record["color"], self._display_mode, self._fill_opacity)
            items.append(dict(id=record["id"], source=source))
        return items

    def dispose(self):
        self._closed = True
        self._timer.stop()
        self._preview_timer.stop()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._mask_renderer.clear()
