"""CPR workspace: editable LPS paths, ordinary reference views and curved output."""
from copy import deepcopy
from dataclasses import replace
from math import degrees, radians
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from qt_dicom_viewer.core.cpr_session import (
    MAX_PATHS, ROLES, default_cpr_session, path_record, unpack_path, validate_cpr_session,
)
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.model import MprPlane, TwoDViewType, ViewportConfig
from qt_dicom_viewer.model.cpr import CprError, CprPath, CprSettings
from qt_dicom_viewer.model.render_models import VolumeLoadRequest, VolumeLoadResult
from qt_dicom_viewer.ui.controller.viewport.image_2d.cpr_viewport_controller import CprViewportController
from qt_dicom_viewer.ui.workers.cpr_render_task import CprRenderInput, CprRenderQueue
from .tab_controller import TabController


class CprTabController(TabController):
    cprChanged = Signal()
    cprLoaded = Signal()
    snapshotCommitted = Signal()

    def __init__(self, tab_config, parent=None):
        meta = tab_config.series_metas[0]
        if len(tab_config.series_metas) != 1 or meta.modality.upper() not in ("CT", "MR") or meta.is_color:
            raise CprError("CPR requires one grayscale CT or MR volume")
        self._session = default_cpr_session(meta.series_uid, meta.frame_of_reference_uid)
        self._volume = self._result = self._drag = None
        self._drawing = self._closed = self._edit_transaction_active = False
        self._selected_point = -1
        self._generation = 0
        self._message = self._volume_request_id = ""
        super().__init__(tab_config, parent, enable_mpr_layout=False)
        self._queue = CprRenderQueue(self)
        self._queue.finished.connect(self._accept_cpr)
        self._queue.failed.connect(self._fail_cpr)
        self._queue.busyChanged.connect(self.cprChanged)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(35)
        self._preview_timer.timeout.connect(self._render_preview)
        self._tool_controller.activePanelChanged.connect(self._notify)
        self._tool_controller.activateTool("cpr-path")

    def _create_viewport_dict(self):
        meta = self._tab_config.series_metas[0]
        for role in ROLES:
            identity = str(uuid4())
            view = CprViewportController(ViewportConfig(identity, self._tab_config.tab_id,
                TwoDViewType.CPR, meta.series_uid, meta, role), self._tool_controller, self)
            self._viewport_dict[identity] = view
            self.connect_signal(view)
        self._active_viewport_id = next(iter(self._viewport_dict))

    @Property(QObject, constant=True)
    def cprController(self):
        return self

    @Slot(str, result=QObject)
    def viewForRole(self, role):
        return next((view for view in self._viewport_dict.values() if view.viewportRole == role), None)

    @Property('QVariantList', constant=True)
    def cprViews(self):
        return list(self._viewport_dict.values())

    @property
    def current_path(self):
        record = self._selected_record()
        return unpack_path(record)[0] if record else None

    @property
    def current_settings(self):
        record = self._selected_record()
        return unpack_path(record)[1] if record else CprSettings()

    def _selected_record(self):
        return next((r for r in self._session["paths"] if r["id"] == self.selectedPathId), None)

    @Property(str, notify=cprChanged)
    def selectedPathId(self):
        return self._session["selected"]

    @Property('QVariantList', notify=cprChanged)
    def paths(self):
        return [dict(pathId=r["id"], name=r["name"], selected=r["id"] == self.selectedPathId)
                for r in self._session["paths"]]

    @Property('QVariantList', notify=cprChanged)
    def controlPoints(self):
        points = self._session["draft"] if self._drawing else self.current_path.control_points if self.current_path else ()
        return [dict(index=i, x=p[0], y=p[1], z=p[2], selected=i == self._selected_point)
                for i, p in enumerate(points)]

    @Property(bool, notify=cprChanged)
    def drawing(self):
        return self._drawing

    @Property(bool, notify=cprChanged)
    def pathEditing(self):
        return self._tool_controller.activePanel == "cpr-path"

    @Property(bool, notify=cprChanged)
    def referencesReady(self):
        return self._result is not None

    @Property(bool, notify=cprChanged)
    def busy(self):
        return self._queue.running

    @Property(bool, notify=cprChanged)
    def ready(self):
        return (self._result is not None and self._result.generation == self._generation
                and self._result.curve is not None and not self._result.preview
                and not self._edit_transaction_active and not self._drawing)

    @Property(str, notify=cprChanged)
    def message(self):
        return self._message or _msg("cpr.drawHint" if self._drawing else "cpr.editHint")

    @Property(float, notify=cprChanged)
    def positionMm(self):
        return self._session["positionMm"]

    @Property(float, notify=cprChanged)
    def totalLength(self):
        path = self.current_path
        return float(np.linalg.norm(np.diff(path.control_points, axis=0), axis=1).sum()) if path else 0.

    @Property('QVariantMap', notify=cprChanged)
    def parameters(self):
        settings = self.current_settings
        return dict(step=settings.step_mm, width=settings.width_mm,
                    angle=degrees(settings.angle_radians), projection=settings.projection,
                    thickness=settings.thickness_mm, crossWidth=self._session["crossWidthMm"],
                    rangeStart=self._session["rangeMm"][0], rangeEnd=self._session["rangeMm"][1])

    @Property('QVariantList', notify=cprChanged)
    def referencePlanes(self):
        return list(self._session["referencePlanes"])

    @Slot()
    def _notify(self):
        self.cprChanged.emit()
        for view in self._viewport_dict.values():
            view.cprChanged.emit()

    def init_render(self):
        self._volume_request_id = str(uuid4())
        self.renderRequested.emit(VolumeLoadRequest(request_id=self._volume_request_id,
            viewport_id=self.viewForRole("reference-a").viewportId,
            series_uid=self._tab_config.series_metas[0].series_uid))

    def accepts_render_result(self, result):
        if self._closed:
            return False
        if isinstance(result, VolumeLoadResult):
            return result.response_id == self._volume_request_id
        view = self._viewport_dict.get(result.viewport_id)
        return view is not None and view.accepts_result(result)

    def handleRenderResult(self, result):
        if not self.accepts_render_result(result):
            return
        if isinstance(result, VolumeLoadResult):
            self._volume = result.volume
            source = self._session["source"]
            if source["fingerprint"] and source["fingerprint"] != self._volume.fingerprint:
                self._message = _msg("cpr.sourceChanged")
                self.cprLoaded.emit()
                self._notify()
                return
            source["fingerprint"] = self._volume.fingerprint
            catalog = getattr(self.parent(), "_series_catalog", None)
            record = catalog.get_series(result.series_uid) if catalog else None
            if record is not None:
                source["frameOfReferenceUid"] = record.frame_of_reference_uid or ""
            if self._session["referenceCenters"] is None:
                self._session["referenceCenters"] = (self._volume.geometry.center_patient,) * 2
            self._request_cpr()
        else:
            self._viewport_dict[result.viewport_id].handleRenderResult(result)

    def _request_cpr(self, *, preview=False):
        if self._volume is None or self._closed:
            return
        self._generation += 1
        request = CprRenderInput(self._generation, self._volume, self.current_path,
            self.current_settings, self.positionMm,
            tuple(MprPlane(p) for p in self._session["referencePlanes"]),
            self._session["referenceCenters"], self._session["crossWidthMm"], preview,
            self._result.cache if self._result else None)
        self._queue.submit(request)
        self._notify()

    @Slot()
    def _render_preview(self):
        self._request_cpr(preview=True)

    @Slot(object)
    def _accept_cpr(self, result):
        if self._closed or result.generation != self._generation:
            return
        self._result = result
        for role, reference in zip(ROLES[:2], result.references):
            self.viewForRole(role).present_cpr(reference.modality_pixels, reference.geometry,
                index=reference.slice_index, count=reference.slice_count)
        if result.curve is not None:
            curve, section = result.curve, result.section
            self._session["positionMm"] = section.distance_mm
            count = len(curve.centerline.distances_mm)
            index = int(np.argmin(abs(curve.centerline.distances_mm-section.distance_mm)))
            self.viewForRole("curved").present_cpr(curve.modality_pixels, None,
                index=index, count=count, spacing=(curve.row_spacing_mm, curve.centerline.spacing_mm))
            self.viewForRole("cross").present_cpr(section.modality_pixels, section.geometry,
                index=index, count=count, provenance=dict(pathId=section.path_id,
                pathRevision=section.path_revision, distanceMm=section.distance_mm,
                algorithmVersion=section.algorithm_version))
        else:
            for role in ROLES[2:]:
                self.viewForRole(role).clear_cpr()
        self.cprLoaded.emit()
        self._notify()

    @Slot(int, str)
    def _fail_cpr(self, generation, error):
        if generation == self._generation and not self._closed:
            self._message = _msg("cpr.error", reason=error)
            self.cprLoaded.emit()
            self._notify()

    def quantification_ready(self, view):
        if view.viewportRole == "curved" or self._edit_transaction_active:
            return False
        return bool(self._result and self._result.generation == self._generation and not self._result.preview)

    def set_linked_window(self, change):
        for view in self._viewport_dict.values():
            view.set_window_state(change)
        self.persistenceChanged.emit()

    @Slot()
    def startPath(self):
        if not self.referencesReady:
            return
        if len(self._session["paths"]) >= MAX_PATHS:
            self._message = _msg("cpr.pathLimit")
            self._notify()
            return
        self.cancel_operation()
        self._tool_controller.activateTool("cpr-path")
        self._drawing, self._selected_point, self._message = True, -1, ""
        self._session["draft"] = ()
        self._notify()

    @Slot(result=bool)
    def finishPath(self):
        if not self._drawing:
            return False
        try:
            path = CprPath(str(uuid4()), _msg("cpr.pathName", number=len(self.paths)+1), self._session["draft"])
        except CprError as error:
            self._message = _msg("cpr.error", reason=str(error))
            self._notify()
            return False
        self._session["paths"].append(path_record(path, self.current_settings))
        self._session.update(selected=path.path_id, draft=(), positionMm=0., rangeMm=(0., 0.))
        self._drawing, self._message = False, ""
        self._commit()
        return True

    def _commit(self):
        self._preview_timer.stop()
        self._message = ""
        self._request_cpr()
        self.snapshotCommitted.emit()
        self.persistenceChanged.emit()
        self._notify()

    @Slot(str)
    def selectPath(self, path_id):
        if path_id == self.selectedPathId or path_id not in [r["id"] for r in self._session["paths"]]:
            return
        self.cancel_operation()
        self._session.update(selected=path_id, positionMm=0., rangeMm=(0., 0.))
        self._selected_point = -1
        self._request_cpr()
        self.persistenceChanged.emit()

    @Slot(str)
    def renamePath(self, name):
        record = self._selected_record()
        if record and name.strip() and len(name) <= 256:
            record["name"] = name.strip()
            self.snapshotCommitted.emit()
            self.persistenceChanged.emit()
            self._notify()

    @Slot()
    def deletePath(self):
        self.cancel_operation()
        self._session["paths"] = [r for r in self._session["paths"] if r["id"] != self.selectedPathId]
        self._session["selected"] = self._session["paths"][0]["id"] if self._session["paths"] else ""
        self._session["positionMm"] = 0.
        self._selected_point = -1
        self._commit()

    @Slot()
    def deleteSelectedPoint(self):
        if self._drawing:
            self._session["draft"] = self._session["draft"][:-1]
            self._selected_point = len(self._session["draft"])-1
            self._notify()
            return
        path = self.current_path
        if path is None or not 0 <= self._selected_point < len(path.control_points):
            return
        points = list(path.control_points)
        del points[self._selected_point]
        if self._replace_points(points):
            self._selected_point = min(self._selected_point, len(points)-1)
            self._commit()

    def _replace_points(self, points, *, revision=None):
        try:
            path = replace(self.current_path, control_points=tuple(points),
                           revision=revision or self.current_path.revision+1)
        except CprError as error:
            self._message = _msg("cpr.error", reason=str(error))
            self._notify()
            return False
        self._selected_record().update(path_record(path, self.current_settings))
        return True

    def projected_points(self, view):
        geometry = view.plane_geometry
        if geometry is None or not view.viewportRole.startswith("reference"):
            return []
        points = self._session["draft"] if self._drawing else self.current_path.control_points if self.current_path else ()
        items = []
        for i, point in enumerate(points):
            normal, row, column, _ = geometry.patient_to_image_index @ (*point, 1.)
            items.append(dict(column=float(column), row=float(row), index=i,
                              near=abs(normal) <= .65, selected=i == self._selected_point))
        return items

    def _hit_point(self, view, column, row, tolerance):
        items = self.projected_points(view)
        if not items:
            return -1
        distances = [np.hypot(item["column"]-column, item["row"]-row) for item in items]
        index = int(np.argmin(distances))
        return index if distances[index] <= tolerance else -1

    def path_tap(self, view, column, row, tolerance):
        if view.viewportRole == "curved" and self._result and self._result.curve:
            self.setPositionMm(column*self._result.curve.centerline.spacing_mm)
            return True
        if not self.pathEditing or view.plane_geometry is None or not view.viewportRole.startswith("reference"):
            return False
        point = view.plane_geometry.image_point_to_patient(column=column, row=row)
        if self._drawing:
            draft = self._session["draft"]
            if len(draft) < 4096 and (not draft or np.linalg.norm(np.asarray(point)-draft[-1]) >= 1e-4):
                self._session["draft"] = (*draft, point)
                self._selected_point = len(draft)
                self._message = ""
                self._notify()
            return True
        hit = self._hit_point(view, column, row, tolerance)
        if hit >= 0:
            self._selected_point = hit
            self._notify()
            return True
        projected = self.projected_points(view)
        for i, (a, b) in enumerate(zip(projected, projected[1:])):
            start, end = np.array((a["column"], a["row"])), np.array((b["column"], b["row"]))
            delta = end-start
            if np.dot(delta, delta) < 1e-8:
                continue
            t = float(np.clip(np.dot(np.array((column, row))-start, delta)/np.dot(delta, delta), 0, 1))
            if np.linalg.norm(start+t*delta-(column, row)) <= tolerance:
                points = list(self.current_path.control_points)
                patient = np.asarray(points[i])*(1-t)+np.asarray(points[i+1])*t
                points.insert(i+1, tuple(patient))
                if self._replace_points(points):
                    self._selected_point = i+1
                    self._commit()
                break
        return True

    def begin_path_drag(self, view, column, row, tolerance):
        if not self.pathEditing or not view.viewportRole.startswith("reference"):
            return False
        if self._drawing:
            return True
        hit = self._hit_point(view, column, row, tolerance)
        if hit < 0:
            return True
        history = getattr(self, "_edit_history", None)
        if history is not None:
            history.capture()
        self._selected_point = hit
        self._drag = (deepcopy(self._selected_record()), hit, view.viewportId, view.plane_geometry)
        self._edit_transaction_active = True
        self._notify()
        return True

    def move_path_drag(self, view, column, row):
        if self._drag is None or self._drag[2] != view.viewportId:
            return False
        record, index, _, geometry = self._drag
        old = np.asarray(record["points"][index])
        target = np.asarray(geometry.image_point_to_patient(column=column, row=row))
        normal = np.asarray(geometry.navigation_direction_patient)
        point = target + normal*np.dot(old-target, normal)
        points = list(self.current_path.control_points)
        points[index] = tuple(point)
        if self._replace_points(points, revision=record["revision"]+1):
            self._preview_timer.start()
            self._notify()
        return True

    def end_path_drag(self, view, column, row):
        if self._drag is None:
            return self.pathEditing and view.viewportRole.startswith("reference")
        self.move_path_drag(view, column, row)
        self._drag = None
        self._edit_transaction_active = False
        self._commit()
        return True

    @Slot(result=bool)
    def cancel_operation(self):
        claimed = self._drawing or self._drag is not None
        if self._drag is not None:
            record = self._drag[0]
            self._selected_record().update(record)
            self._drag = None
            self._edit_transaction_active = False
            self._preview_timer.stop()
            self._request_cpr()
        self._drawing, self._message = False, ""
        self._session["draft"] = ()
        self._notify()
        return claimed

    @Slot(int)
    def locatePoint(self, index):
        points = self._session["draft"] if self._drawing else self.current_path.control_points if self.current_path else ()
        if not 0 <= index < len(points):
            return
        self._selected_point = index
        self._session["referenceCenters"] = (points[index],)*2
        if not self._drawing:
            self._session["positionMm"] = float(np.linalg.norm(np.diff(points[:index+1], axis=0), axis=1).sum()) if index else 0.
        self._request_cpr()

    @Slot(float)
    def setPositionMm(self, value):
        if not np.isfinite(value) or self.current_path is None:
            return
        value = float(np.clip(value, 0, self.totalLength))
        self._session["positionMm"] = value
        curve = self._result.curve if self._result else None
        if curve is not None:
            index = int(np.argmin(abs(curve.centerline.distances_mm-value)))
            center = tuple(curve.centerline.points_patient[index])
            self._session["referenceCenters"] = (center, center)
        self._request_cpr()
        self.persistenceChanged.emit()

    def navigate_view(self, view, index):
        if view.viewportRole in ("curved", "cross"):
            if self._result and self._result.curve:
                self.setPositionMm(index*self._result.curve.centerline.spacing_mm)
            return
        geometry = view.plane_geometry
        if geometry is None:
            return
        view._prepare_slice_index_change(index)
        offset = (index-view._frame_meta.slice_index)*geometry.navigation_spacing
        center = np.asarray(geometry.frame.center_patient)+np.asarray(geometry.navigation_direction_patient)*offset
        centers = list(self._session["referenceCenters"])
        centers[ROLES.index(view.viewportRole)] = tuple(center)
        self._session["referenceCenters"] = tuple(centers)
        self._request_cpr()

    @Slot(int, str)
    def setReferencePlane(self, index, plane):
        if index not in (0, 1) or plane not in ("axial", "coronal", "sagittal"):
            return
        if self._drag is not None:
            self.cancel_operation()
        planes = list(self._session["referencePlanes"])
        planes[index] = plane
        self._session["referencePlanes"] = tuple(planes)
        self._request_cpr()

    @Slot(str, 'QVariant')
    def setParameter(self, key, value):
        record = self._selected_record()
        if record is None:
            return
        values = dict(record["settings"])
        fields = dict(step="step_mm", width="width_mm", angle="angle_radians",
                      projection="projection", thickness="thickness_mm")
        try:
            if key in fields:
                values[fields[key]] = radians(float(value)) if key == "angle" else value
                record.update(path_record(self.current_path, CprSettings(**values)))
            elif key == "crossWidth":
                width = float(value)
                if not np.isfinite(width) or not 0 < width <= 500:
                    raise CprError("Cross-section width must be between 0 and 500 mm")
                self._session["crossWidthMm"] = width
            elif key in ("rangeStart", "rangeEnd"):
                interval = list(self._session["rangeMm"])
                interval[0 if key == "rangeStart" else 1] = float(value)
                if not 0 <= interval[0] <= interval[1] <= self.totalLength:
                    raise CprError("Interval must lie on the centerline")
                self._session["rangeMm"] = tuple(interval)
            else:
                return
        except (CprError, ValueError, TypeError) as error:
            self._message = _msg("cpr.error", reason=str(error))
            self._notify()
            return
        self._commit()

    def session_state(self):
        return validate_cpr_session(self._session)

    def restore_session(self, state):
        state = validate_cpr_session(state)
        self.cancel_operation()
        self._session = state
        self._drawing = bool(state["draft"])
        self._selected_point = -1
        self._request_cpr()
        self._notify()

    def dispose(self):
        self._closed = True
        self._preview_timer.stop()
        self._queue.close()
        super().dispose()
