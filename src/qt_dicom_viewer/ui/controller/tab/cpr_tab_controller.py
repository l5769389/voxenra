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
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from qt_dicom_viewer.model import MprPlane, TwoDViewType, ViewportConfig
from qt_dicom_viewer.model.cpr import CprError, CprPath, CprSettings
from qt_dicom_viewer.model.render_models import VolumeLoadRequest, VolumeLoadResult
from qt_dicom_viewer.ui.controller.viewport.image_2d.cpr_viewport_controller import CprViewportController
from qt_dicom_viewer.ui.workers.cpr_render_task import CprRenderInput, CprRenderQueue
from .tab_controller import TabController


class CprTabController(TabController):
    _i18n_message = Signal()
    cprChanged = Signal()
    cprLoaded = Signal()
    snapshotCommitted = Signal()
    resultViewChanged = Signal()
    resultSplitChanged = Signal()
    pathInputStarted = Signal()

    def __init__(self, tab_config, parent=None):
        meta = tab_config.series_metas[0]
        if len(tab_config.series_metas) != 1 or meta.modality.upper() not in ("CT", "MR") or meta.is_color:
            raise CprError("CPR requires one grayscale CT or MR volume")
        self._session = default_cpr_session(meta.series_uid, meta.frame_of_reference_uid)
        self._volume = self._result = self._drag = None
        self._fingerprinted_volume = None
        self._fingerprint = ""
        self._source_mismatch = False
        self._export_scope = "curved"
        self._historical_requests = {}
        self._pending_restore_planes = {}
        self._drawing = self._closed = self._edit_transaction_active = False
        self._path_editing = False
        self._pending_results = self._path_return_results = False
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
        self._tool_controller.activePanelChanged.connect(self._tool_panel_changed)
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
        return self._tool_controller.activePanel == "cpr-path" and (self._drawing or self._path_editing)

    @Property(bool, notify=cprChanged)
    def canFinishPath(self):
        return self._drawing and len(self._session["draft"]) >= 2

    @Property(bool, notify=cprChanged)
    def finishing(self):
        return self._pending_results

    @Property(bool, notify=cprChanged)
    def canFinishEditing(self):
        return (not self._source_mismatch and self._drag is None and not self._pending_results
                and not self.resultView and (self.canFinishPath if self._drawing else bool(self.current_path)))

    @Property(bool, notify=cprChanged)
    def canCancelPath(self):
        return self._drawing or self._path_editing or self._drag is not None or self._pending_results

    @Property(bool, notify=cprChanged)
    def canDeletePoint(self):
        if self._drawing:
            return bool(self._session["draft"])
        path = self.current_path
        return bool(self.pathEditing and path and len(path.control_points) > 2
                    and 0 <= self._selected_point < len(path.control_points))

    @Property(bool, notify=resultViewChanged)
    def resultView(self):
        return self._session['resultView']

    @Property(float, notify=resultSplitChanged)
    def resultSplitRatio(self):
        return self._session['resultSplitRatio']

    @Slot(float)
    def setResultSplitRatio(self, ratio):
        if not .05 <= ratio <= .95 or abs(ratio - self.resultSplitRatio) < 1e-6:
            return
        self._session['resultSplitRatio'] = ratio
        self.resultSplitChanged.emit()
        self.persistenceChanged.emit()

    def _set_result_view(self, enabled, *, preserve_view=False):
        enabled = bool(enabled and self.current_path)
        self._session['resultView'] = enabled
        focused = self._viewport_dict.get(self.focusedViewportId)
        if not preserve_view or (enabled and focused and focused.viewportRole.startswith('reference')):
            self.focusSingleViewport('')
        active = self.activeViewport
        if not preserve_view or active is None or (enabled and active.viewportRole.startswith('reference')):
            role = 'curved' if enabled else 'reference-a'
            super().activateViewport(self.viewForRole(role).viewportId)
        self.resultViewChanged.emit()
        self.persistenceChanged.emit()
        self._notify()

    @Slot(str)
    def activateViewport(self, viewport_id):
        view = self._viewport_dict.get(viewport_id)
        if self.resultView and view and view.viewportRole.startswith('reference'):
            self._set_result_view(False)
        if view and self.focusedViewportId and self.focusedViewportId != viewport_id:
            self.focusSingleViewport(viewport_id)
        super().activateViewport(viewport_id)

    @Slot(str)
    def focusSingleViewport(self, viewport_id):
        view = self._viewport_dict.get(viewport_id)
        if self.resultView and view and view.viewportRole.startswith('reference'):
            self._set_result_view(False)
        super().focusSingleViewport(viewport_id)

    @Slot(result=bool)
    def finishEditing(self):
        if self._pending_results:
            return True
        if self._drag is not None or self._source_mismatch:
            return False
        if self._drawing and not self.finishPath():
            return False
        if not self.current_path:
            return False
        self._path_editing, self._selected_point = False, -1
        self._pending_results = True
        if self.ready:
            self._pending_results = False
            self._set_result_view(True)
        elif not self.busy:
            self._request_cpr()
        self._notify()
        return True

    @Slot(bool)
    def setPathEditing(self, enabled):
        if self._drawing:
            return
        if enabled:
            if self.pathEditing:
                return
            if not self.current_path or not self.referencesReady or self._source_mismatch:
                return
            self._tool_controller.activateTool("cpr-path")
            self._path_return_results = self.resultView
            self._pending_results = False
            self._set_result_view(False)
            self._path_editing = True
            self.pathInputStarted.emit()
        else:
            self.cancel_operation()
            self._selected_point = -1
        self._notify()

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
                and not self._edit_transaction_active and not self._drawing and not self._source_mismatch)

    @Property(bool, notify=cprChanged)
    def sourceMismatch(self):
        return self._source_mismatch

    @Property(bool, notify=cprChanged)
    def hasError(self):
        return self._source_mismatch or bool(self._message)

    @Property(str, notify=cprChanged)
    def exportScope(self):
        return self._export_scope

    @Slot(str)
    def setExportScope(self, scope):
        if scope not in ("curved", "cross", "combined"):
            return
        self._export_scope = scope
        if scope == "combined":
            self.focusSingleViewport("")
        else:
            view = self.viewForRole(scope)
            self.activateViewport(view.viewportId)
            if self.focusedViewportId:
                self.focusSingleViewport(view.viewportId)
        self._notify()

    def export_ready(self):
        if (self._source_mismatch or self._drawing or self._edit_transaction_active
                or self._queue.running or self._preview_timer.isActive()):
            return False
        if self._export_scope == "cross":
            view = self.viewForRole("cross")
            if view._historical:
                return not view.render_pending and view.loadState == "ready"
        if not self.ready:
            return False
        views = list(self._viewport_dict.values()) if self._export_scope == "combined" else [self.viewForRole(self._export_scope)]
        return all(not view.render_pending and view.loadState == "ready" for view in views)

    def export_revision(self):
        views = list(self._viewport_dict.values()) if self._export_scope == "combined" else [self.viewForRole(self._export_scope)]
        return repr((self._generation, self._export_scope, self.resultView, self.resultSplitRatio, self.focusedViewportId,
                     [(view.viewportId, view._image_revision, view.viewport_state) for view in views]))

    @_TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='cprChanged')
    def message(self):
        if self._source_mismatch:
            return _msg("cpr.sourceChanged")
        return self._message or _msg("cpr.drawHint" if self._drawing else
                                    "cpr.editHint" if self.pathEditing else "cpr.viewHint")

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
    def _tool_panel_changed(self):
        if self._tool_controller.activePanel != "cpr-path" and (self._path_editing or self._drawing or self._pending_results):
            self.cancel_operation()
        if self._tool_controller.activePanel == "export":
            self.setExportScope(self._export_scope)
        else:
            self._notify()

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
        pending = self._historical_requests.get(result.response_id)
        return (view is not None and pending is not None
                and pending[0] == self._generation and view.accepts_result(result))

    def handleRenderResult(self, result):
        if not self.accepts_render_result(result):
            return
        if isinstance(result, VolumeLoadResult):
            self._volume = result.volume
            self._source_mismatch = False
            source = self._session["source"]
            if self._volume.series_uid != source["seriesUid"]:
                self._reject_source()
                return
            catalog = getattr(self.parent(), "_series_catalog", None)
            record = catalog.get_series(result.series_uid) if catalog else None
            if record is not None:
                frame = record.frame_of_reference_uid or ""
                if source["frameOfReferenceUid"] and source["frameOfReferenceUid"] != frame:
                    self._reject_source()
                    return
                source["frameOfReferenceUid"] = frame
            if self._session["referenceCenters"] is None:
                self._session["referenceCenters"] = (self._volume.geometry.center_patient,) * 2
            self._request_cpr()
        else:
            view = self._viewport_dict[result.viewport_id]
            _, source = self._historical_requests.pop(result.response_id)
            if result.volume is None or result.volume.fingerprint != self._volume.fingerprint:
                self._reject_source()
                return
            metadata = source["cpr"]
            frame = replace(result.frame_meta, slice_index=metadata["frameIndex"],
                            slice_count=metadata["frameCount"], window=view.current_window,
                            inverted=view.inverted)
            view.plane_geometry = result.plane_geometry
            view.handleRenderResult(replace(result, frame_meta=frame))
            view._historical = True
            view.refresh_window_image()
            self._notify()

    def navigate_measurement(self, view, source):
        self._start_historical_planes([(view, source)])

    def _start_historical_planes(self, planes, *, activate=True):
        from qt_dicom_viewer.ui.measurement_source import restore_request, display_parameters
        for view, source in planes:
            metadata = source.get("cpr", {})
            if (source.get("kind") != "mpr" or not metadata or view.viewportRole == "curved"
                    or source.get("parameters", {}).get("series_uid") != self._session["source"]["seriesUid"]
                    or self._source_mismatch or metadata.get("fingerprint") != self._fingerprint):
                raise CprError(str(_msg("cpr.sourceChanged")))
        if activate:
            self._pending_results = False
        if self._queue.running or self._preview_timer.isActive():
            self._generation += 1
        self._queue.cancel()
        self._preview_timer.stop()
        for view, source in planes:
            request = restore_request(source, view.viewportId, display=display_parameters(view))
            self._historical_requests[request.request_id] = (self._generation, deepcopy(source))
            view._measurement_requests = {request.request_id: deepcopy(source)}
            view._independent_measurement_source = deepcopy(source)
            view._latest_request_id = request.request_id
            view.render_pending = True
            view.cancelMeasurement()
            if activate:
                self.activateViewport(view.viewportId)
            self.renderRequested.emit(request)
        self._notify()

    def restore_measurement_planes(self, views):
        from qt_dicom_viewer.ui.workspace_snapshot import view_key
        self._pending_restore_planes = {
            view.viewportId: views[view_key(view)]["independentSource"]
            for view in self._viewport_dict.values()
            if views.get(view_key(view), {}).get("independentSource")
        }

    def handleRenderFailure(self, failure):
        pending = self._historical_requests.pop(failure.request_id, None)
        if pending is not None and pending[0] == self._generation:
            self._viewport_dict[failure.viewport_id].handleRenderFailure(failure)
            self._message = _msg("cpr.error", reason=str(failure.error))
            self._notify()
        elif failure.request_id == self._volume_request_id:
            self._message = _msg("cpr.error", reason=str(failure.error))
            self._notify()

    def _request_cpr(self, *, preview=False):
        if self._volume is None or self._closed or self._source_mismatch:
            return
        self._message = ""
        self._historical_requests.clear()
        for view in self._viewport_dict.values():
            view._independent_measurement_source = None
            # The old plane is still displayed until present_cpr accepts its
            # replacement. Preserve its historical identity and distance.
        self._generation += 1
        request = CprRenderInput(self._generation, self._volume, self.current_path,
            self.current_settings, self.positionMm,
            tuple(MprPlane(p) for p in self._session["referencePlanes"]),
            self._session["referenceCenters"], self._session["crossWidthMm"], preview,
            self._result.cache if self._result else None,
            self._fingerprint if self._fingerprinted_volume is self._volume else "")
        self._queue.submit(request)
        self._notify()

    @Slot()
    def _render_preview(self):
        self._request_cpr(preview=True)

    @Slot(object)
    def _accept_cpr(self, result):
        if self._closed or result.generation != self._generation:
            return
        expected = self._session["source"]["fingerprint"]
        if expected and expected != result.source_fingerprint:
            self._reject_source()
            return
        self._fingerprinted_volume, self._fingerprint = self._volume, result.source_fingerprint
        self._session["source"]["fingerprint"] = self._fingerprint
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
                pathRevision=section.path_revision, pathName=self.current_path.name, distanceMm=section.distance_mm,
                algorithmVersion=section.algorithm_version))
        else:
            for role in ROLES[2:]:
                self.viewForRole(role).clear_cpr()
        self.cprLoaded.emit()
        self._notify()
        if self._pending_results and self.ready:
            self._pending_results = False
            self._set_result_view(True)
        if self._pending_restore_planes and not result.preview:
            planes, self._pending_restore_planes = self._pending_restore_planes, {}
            self._start_historical_planes([(self._viewport_dict[key], source) for key, source in planes.items()],
                                          activate=False)

    def _reject_source(self):
        self._pending_results = False
        self._set_result_view(False)
        self._queue.cancel()
        self._generation += 1
        self._source_mismatch = True
        self._result = None
        self._message = _msg("cpr.sourceChanged")
        for view in self._viewport_dict.values():
            view.clear_cpr()
        self.cprLoaded.emit()
        self._notify()

    @Slot(int, str)
    def _fail_cpr(self, generation, error):
        if generation == self._generation and not self._closed:
            self._pending_results = False
            self._message = _msg("cpr.error", reason=error)
            self.cprLoaded.emit()
            self._notify()

    def quantification_ready(self, view):
        if view.viewportRole == "curved" or self._edit_transaction_active or self._source_mismatch:
            return False
        if view._historical and not view.render_pending:
            return True
        return bool(self._result and self._result.generation == self._generation and not self._result.preview)

    def set_linked_window(self, change):
        for view in self._viewport_dict.values():
            view.set_window_state(change)
        self.persistenceChanged.emit()

    @Slot()
    def startPath(self):
        if not self.referencesReady or self._drawing or self._source_mismatch:
            return
        if len(self._session["paths"]) >= MAX_PATHS:
            self._message = _msg("cpr.pathLimit")
            self._notify()
            return
        self.cancel_operation()
        self._path_return_results = self.resultView
        self._set_result_view(False)
        self._tool_controller.activateTool("cpr-path")
        self._drawing, self._selected_point, self._message = True, -1, ""
        self._session["draft"] = ()
        self.persistenceChanged.emit()
        self._notify()
        self.pathInputStarted.emit()

    @Slot(result=bool)
    def finishPath(self):
        if not self._drawing:
            return False
        if len(self._session["draft"]) < 2:
            self._message = _msg("cpr.needTwoPoints")
            self._notify()
            return False
        try:
            path = CprPath(str(uuid4()), _msg("cpr.pathName", number=len(self.paths)+1), self._session["draft"])
        except CprError as error:
            self._message = _msg("cpr.error", reason=str(error))
            self._notify()
            return False
        self._session["paths"].append(path_record(path, self.current_settings))
        self._session["pathRanges"][path.path_id] = (0., 0.)
        self._session.update(selected=path.path_id, draft=(), positionMm=0., rangeMm=(0., 0.))
        self._drawing, self._message = False, ""
        self._path_editing, self._selected_point = False, -1
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
        self._session.update(selected=path_id, positionMm=0.,
                             rangeMm=self._session["pathRanges"].get(path_id, (0., 0.)))
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
        self._set_result_view(False)
        self._session["pathRanges"].pop(self.selectedPathId, None)
        self._session["paths"] = [r for r in self._session["paths"] if r["id"] != self.selectedPathId]
        self._session["selected"] = self._session["paths"][0]["id"] if self._session["paths"] else ""
        self._session["positionMm"] = 0.
        self._session["rangeMm"] = self._session["pathRanges"].get(self.selectedPathId, (0., 0.))
        self._selected_point = -1
        self._commit()

    @Slot()
    def deleteSelectedPoint(self):
        if not self.canDeletePoint:
            return
        if self._drawing:
            self._session["draft"] = self._session["draft"][:-1]
            self._selected_point = len(self._session["draft"])-1
            self.persistenceChanged.emit()
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
        interval = tuple(min(value, self.totalLength) for value in self._session["rangeMm"])
        self._session["rangeMm"] = self._session["pathRanges"][path.path_id] = interval
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
            if view.activeInteraction.startswith("annotate:"):
                return False
            self.setPositionMm(column*self._result.curve.centerline.spacing_mm)
            return True
        if not self.pathEditing or view.plane_geometry is None or not view.viewportRole.startswith("reference"):
            return False
        point = view.plane_geometry.image_point_to_patient(column=column, row=row)
        if self._drawing:
            draft = self._session["draft"]
            if draft:
                # Clicking an existing endpoint to finish must not create a
                # tiny segment from pointer jitter. A new slice is distinct.
                last = self.projected_points(view)[-1]
                if last["near"] and np.hypot(last["column"]-column, last["row"]-row) <= tolerance:
                    return True
            if len(draft) < 4096 and (not draft or np.linalg.norm(np.asarray(point)-draft[-1]) >= 1e-4):
                self._session["draft"] = (*draft, point)
                self._selected_point = len(draft)
                self._message = ""
                self.persistenceChanged.emit()
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
        self._drag = (deepcopy(self._selected_record()), hit, view.viewportId, view.plane_geometry, self._session["rangeMm"])
        self._edit_transaction_active = True
        self._notify()
        return True

    def move_path_drag(self, view, column, row):
        if self._drag is None or self._drag[2] != view.viewportId:
            return False
        record, index, _, geometry, _ = self._drag
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
        return_to_results = (self._drawing or self._path_editing) and self._path_return_results
        claimed = self._drawing or self._drag is not None or self._path_editing or self._pending_results
        self._pending_results = False
        if self._drag is not None:
            record = self._drag[0]
            self._selected_record().update(record)
            self._session["rangeMm"] = self._session["pathRanges"][record["id"]] = self._drag[4]
            self._drag = None
            self._edit_transaction_active = False
            self._preview_timer.stop()
            self._request_cpr()
        self._drawing, self._message = False, ""
        self._path_editing = False
        self._selected_point = -1
        self._path_return_results = False
        self._session["draft"] = ()
        if return_to_results:
            self._set_result_view(True)
        if claimed:
            self.persistenceChanged.emit()
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
        self.persistenceChanged.emit()

    @Slot(float)
    def setPositionMm(self, value):
        if not np.isfinite(value) or self.current_path is None:
            return
        value = float(np.clip(value, 0, self.totalLength))
        self._session["positionMm"] = value
        # Resolve against the current control points, even if an older path's
        # image is still on screen while the latest request is pending.
        points = np.asarray(self.current_path.control_points)
        lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
        cumulative = np.r_[0., np.cumsum(lengths)]
        count = max(1, int(np.ceil(cumulative[-1]/self.current_settings.step_mm)))
        value = round(value/cumulative[-1]*count)*cumulative[-1]/count
        index = min(len(lengths)-1, int(np.searchsorted(cumulative, value, side="right")-1))
        fraction = (value-cumulative[index])/lengths[index]
        center = tuple(points[index]*(1-fraction)+points[index+1]*fraction)
        self._session["positionMm"] = float(value)
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
        self.persistenceChanged.emit()

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
        self.persistenceChanged.emit()

    @Slot(str, 'QVariant')
    def setParameter(self, key, value):
        record = self._selected_record()
        if record is None or self._drawing:
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
                self._session["pathRanges"][self.selectedPathId] = tuple(interval)
            else:
                return
        except (CprError, ValueError, TypeError) as error:
            self._message = _msg("cpr.error", reason=str(error))
            self._notify()
            return
        self._commit()

    def session_state(self):
        state = deepcopy(self._session)
        if self._drag is not None:
            original, _, _, _, interval = self._drag
            state["paths"] = [original if record["id"] == original["id"] else record for record in state["paths"]]
            state["rangeMm"] = state["pathRanges"][original["id"]] = interval
        return validate_cpr_session(state)

    def restore_session(self, state):
        state = validate_cpr_session(state)
        if state["source"]["seriesUid"] != self._tab_config.series_metas[0].series_uid:
            raise CprError("Saved CPR paths belong to another series")
        self.cancel_operation()
        self._session = state
        self.resultSplitChanged.emit()
        self._set_result_view(state['resultView'], preserve_view=True)
        self._drawing = bool(state["draft"])
        self._selected_point = -1
        frame = self._tab_config.series_metas[0].frame_of_reference_uid or ""
        if state["source"]["frameOfReferenceUid"] and state["source"]["frameOfReferenceUid"] != frame:
            self._reject_source()
            return
        if (self._fingerprint and state["source"]["fingerprint"]
                and self._fingerprint != state["source"]["fingerprint"]):
            self._reject_source()
            return
        self._request_cpr()
        self._notify()

    def dispose(self):
        self._closed = True
        self._preview_timer.stop()
        self._queue.close()
        super().dispose()
