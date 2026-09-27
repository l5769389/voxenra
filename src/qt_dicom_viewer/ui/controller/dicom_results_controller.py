"""Snapshot current-tab measurements and masks, then export off the GUI thread."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
import numpy as np

from PySide6.QtCore import QObject, Property, Signal, Slot
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from qt_dicom_viewer.i18n.widgets import QFileDialog
from qt_dicom_viewer.ui.file_location import reveal_path


def _instances(catalog, uid, phase=None, sop=None):
    series = catalog.get_series(uid)
    if series is None:
        raise ValueError(_msg("results.invalidSource"))
    if phase is not None:
        selected = series.phase_by_identifier(phase)
        if selected is None:
            raise ValueError(_msg("results.changedSource"))
        return tuple(selected.instances)
    if sop:
        phases = [
            p
            for p in series.phases
            if any(i.sop_instance_uid == sop for i in p.instances)
        ]
        if len(phases) == 1:
            return tuple(phases[0].instances)
    return tuple(series.instances)


def capture_dicom_results(workspace, catalog, *, report=True):
    tab = workspace.activeTab
    if tab is None:
        raise ValueError(_msg("results.noResults"))
    from qt_dicom_viewer.core.dicom_results import PlanarResult, SegmentResult

    planar, segments = [], []
    if report:
        for view in tab.viewports_by_id.values():
            measure = getattr(view, "_measure_controller", None)
            if measure is None:
                continue
            if measure.has_active_transaction:
                raise ValueError(_msg("text.0383"))
            measurements = [
                item
                for item in measure.committed_measurements
                if str(getattr(item, "kind", "")) != "arrow"
            ]
            owner = getattr(view, "owner", None)
            if (
                measurements
                and getattr(owner, "isFusion", False)
                and getattr(view, "viewportRole", "") in ("pet", "fusion")
                and not np.allclose(owner.matrix, np.eye(4))
            ):
                raise ValueError(_msg("results.geometryMismatch"))
            settings = getattr(
                getattr(view, "_tool_controller", None), "mpr_projection_settings", None
            )
            if measurements and (
                (settings is not None and settings.enabled)
                or getattr(view, "viewportRole", "") == "mip"
            ):
                raise ValueError(_msg("results.projectedMeasurement"))
            for item in measurements:
                planar.append(
                    PlanarResult(
                        item,
                        measure._measurement_frames.get(item.measurement_id),
                        _instances(catalog, item.series_uid, sop=item.sop_instance_uid),
                        is_mpr=getattr(view, "_plane_geometry", None) is not None,
                    )
                )
    voi = getattr(tab, "_voi_controller", None)
    if voi is not None:
        records = [
            r for r in voi.current_records if report or r["kind"] == "segmentation"
        ]
        if records and (voi.busy or voi._draft):
            raise ValueError(_msg("text.0390"))
        for record in records:
            evaluation = voi.evaluations.get(record["id"])
            if evaluation is None:
                raise ValueError(_msg("text.0391"))
            # Background export owns its mask snapshot, independent of edits,
            # phase changes, closure and deletion in the live workspace.
            frozen = replace(
                evaluation,
                mask=evaluation.mask.copy(),
                offset=evaluation.offset.copy(),
                metrics=dict(evaluation.metrics),
            )
            segments.append(
                SegmentResult(
                    dict(record),
                    frozen,
                    _instances(catalog, record["series"], record.get("phase")),
                )
            )
    if not planar and not segments:
        raise ValueError(_msg("results.noResults"))
    return tuple(planar), tuple(segments)


class DicomResultsController(QObject):
    changed = Signal()
    _i18n_message = Signal()
    completed = Signal(object, bool, str)
    masksCompleted = Signal(object)

    def __init__(self, workspace, catalog, parent=None):
        super().__init__(parent)
        self.workspace, self.catalog = workspace, catalog
        self._busy = self._error = self._closed = False
        self._message = self._result_path = self._operation = ""
        self._cancel = Event()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="dicom-results"
        )
        self.completed.connect(self._finish)
        self.masksCompleted.connect(self._accept_masks)

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(bool, notify=changed)
    def isError(self):
        return self._error

    @_TextProperty(
        str, notify=_i18n_message, notify_name="_i18n_message", source_notify="changed"
    )
    def message(self):
        return self._message

    @Property(str, notify=changed)
    def operation(self):
        return self._operation

    @Property(str, notify=changed)
    def resultPath(self):
        return self._result_path

    @Slot(result=bool)
    def openResultLocation(self):
        return reveal_path(self._result_path)

    @Slot()
    def cancel(self):
        self._cancel.set()

    @Slot(str)
    def exportResults(self, kind):
        if self._busy or self._closed:
            return
        # Validate before showing a destination chooser.
        self._operation = "export"
        try:
            capture_dicom_results(self.workspace, self.catalog, report=kind == "sr")
        except ValueError as error:
            self._finish(error_message(error), True, "")
            return
        path = QFileDialog.getExistingDirectory(None, _msg("results.chooseDirectory"))
        if path:
            self.export_to(path, kind=kind)

    def export_to(self, path, *, kind="sr"):
        if self._busy or self._closed:
            return False
        self._operation = "export"
        try:
            if kind not in ("seg", "sr"):
                raise ValueError(_msg("text.0397"))
            planar, segments = capture_dicom_results(
                self.workspace, self.catalog, report=kind == "sr"
            )
        except ValueError as error:
            self._finish(error_message(error), True, "")
            return False
        self._cancel.clear()
        self._busy, self._error, self._message, self._result_path = (
            True,
            False,
            _msg("results.writing"),
            "",
        )
        self.changed.emit()

        def write():
            from qt_dicom_viewer.core.dicom_results import write_results

            return write_results(
                path,
                planar,
                segments,
                report=kind == "sr",
                cancelled=self._cancel.is_set,
            )

        def done(future):
            try:
                output, count = future.result()
                message, error, path = (
                    _msg("results.written", count=count),
                    False,
                    str(output.resolve()),
                )
            except InterruptedError:
                message, error, path = _msg("results.cancelled"), False, ""
            except Exception as exc:
                message, error, path = (
                    _msg("results.failed", reason=error_message(exc)),
                    True,
                    "",
                )
            if not self._closed:
                self.completed.emit(message, error, path)

        self._executor.submit(write).add_done_callback(done)
        return True

    def _mask_target(self):
        tab = self.workspace.activeTab
        view = getattr(tab, "activeViewport", None)
        voi = getattr(tab, "_voi_controller", None)
        volume = getattr(view, "_voi_volume", None)
        if (
            tab is None
            or str(tab.tab_config.tab_type) not in ("mpr", "4d")
            or voi is None
            or volume is None
            or not voi._phase_ready
            or getattr(view, "render_pending", False)
        ):
            raise ValueError(_msg("seg.openMpr"))
        if voi.busy or voi._draft:
            raise ValueError(_msg("text.0390"))
        if view._tool_controller.mpr_projection_settings.enabled:
            raise ValueError(_msg("results.projectedMeasurement"))
        instances = _instances(self.catalog, volume.series_uid, voi._phase)
        return tab, voi, view, volume, instances

    @Slot()
    def importSegmentation(self):
        if self._busy or self._closed:
            return
        self._operation = "import"
        try:
            self._mask_target()
        except ValueError as error:
            self._finish(error_message(error), True, "")
            return
        path, _ = QFileDialog.getOpenFileName(
            None, _msg("seg.chooseFile"), "", "Segmentation (*.dcm *.DCM *.nrrd *.nhdr);;All files (*)"
        )
        if path:
            self.import_from(path)

    def import_from(self, path):
        if self._busy or self._closed:
            return False
        self._operation = "import"
        try:
            tab, voi, view, volume, instances = self._mask_target()
        except ValueError as error:
            self._finish(error_message(error), True, "")
            return False
        from qt_dicom_viewer.core.segmentation_import import read_segmentation

        if str(path).lower().endswith((".nrrd", ".nhdr")):
            from qt_dicom_viewer.core.nrrd_exchange import read_segmentation as read_nrrd_segmentation
            phase = voi._phase
            return self._start_masks(voi, volume, phase,
                lambda: read_nrrd_segmentation(path, volume, phase=phase, cancelled=self._cancel.is_set))

        phase = voi._phase
        return self._start_masks(
            voi,
            volume,
            phase,
            lambda: read_segmentation(
                path, volume, instances, phase=phase, cancelled=self._cancel.is_set
            ),
        )

    @Slot()
    def exportNrrd(self):
        if self._busy or self._closed:
            return
        self._operation = "export"
        try:
            self._mask_target()
        except ValueError as error:
            self._finish(error_message(error), True, "")
            return
        path = QFileDialog.getExistingDirectory(None, _msg("results.chooseDirectory"))
        if path:
            self.export_nrrd_to(path)

    def export_nrrd_to(self, path):
        """Export the current phase's source plus all its segmentation masks."""
        if self._busy or self._closed:
            return False
        self._operation = "export"
        try:
            _, voi, _, volume, _ = self._mask_target()
            records = [dict(r) for r in voi.current_records if r["kind"] == "segmentation" and r["series"] == volume.series_uid]
            evaluations = {r["id"]: replace(voi.evaluations[r["id"]], mask=voi.evaluations[r["id"]].mask.copy()) for r in records}
            # Scalar pixels and evaluations are immutable during rendering;
            # keep the volume reference alive until the worker completes.
        except (KeyError, ValueError) as error:
            self._finish(error_message(error), True, "")
            return False
        self._cancel.clear()
        self._busy, self._error, self._message, self._result_path = True, False, _msg("results.writing"), ""
        self.changed.emit()

        def write():
            from pathlib import Path
            import shutil
            import tempfile
            from uuid import uuid4
            from qt_dicom_viewer.core.nrrd_exchange import write_nrrd, write_segmentation
            root = Path(path)
            staging = Path(tempfile.mkdtemp(prefix=".nrrd-", dir=root))
            try:
                write_nrrd(staging / "source.nrrd", volume.modality_pixels,
                    volume.geometry.voxel_to_patient,
                    metadata={"Voxenra_SourceSeriesUID": volume.series_uid, "Voxenra_Unit": volume.pixel_value_meta.unit or "Source"},
                    cancelled=self._cancel.is_set)
                if records:
                    write_segmentation(staging / "segmentation.seg.nrrd", volume, records, evaluations, cancelled=self._cancel.is_set)
                if self._cancel.is_set():
                    raise InterruptedError()
                target = root / ("Voxenra-NRRD-" + uuid4().hex[:8])
                staging.rename(target)
                return str(target), 2 if records else 1
            finally:
                if staging.exists():
                    shutil.rmtree(staging)

        def done(future):
            try:
                target, count = future.result()
                payload = (_msg("results.written", count=count), False, target)
            except InterruptedError:
                payload = (_msg("results.cancelled"), False, "")
            except Exception as error:
                payload = (_msg("results.failed", reason=error_message(error)), True, "")
            if not self._closed:
                self.completed.emit(*payload)
        self._executor.submit(write).add_done_callback(done)
        return True

    @Slot(result=bool)
    def convertSelectedRoi(self):
        if self._busy or self._closed:
            return False
        self._operation = "convert"
        try:
            tab, voi, view, volume, instances = self._mask_target()
            measure = view._measure_controller
            item = next(
                (
                    m
                    for m in measure.visible_measurements
                    if m.measurement_id == measure.selectedMeasurementId
                ),
                None,
            )
            if (
                item is None
                or str(getattr(item, "kind", "")) != "freehand"
                or measure.has_active_transaction
            ):
                raise ValueError(_msg("seg.roiRequired"))
            frame = measure._measurement_frames.get(item.measurement_id)
        except ValueError as error:
            self._finish(error_message(error), True, "")
            return False
        from qt_dicom_viewer.core.segmentation_masks import roi_to_mask

        phase = voi._phase

        def convert():
            record, evaluation = roi_to_mask(volume, item, frame, phase=phase)
            return [record], {record["id"]: evaluation}

        return self._start_masks(voi, volume, phase, convert)

    def _start_masks(self, voi, volume, phase, action):
        import weakref

        target = weakref.ref(voi)
        self._cancel.clear()
        self._busy, self._error, self._message, self._result_path = (
            True,
            False,
            _msg("seg.reading"),
            "",
        )
        self.changed.emit()

        def done(future):
            try:
                records, evaluations = future.result()
                payload = (target, volume, phase, records, evaluations, None)
            except Exception as error:
                payload = (target, volume, phase, [], {}, error)
            if not self._closed:
                self.masksCompleted.emit(payload)

        self._executor.submit(action).add_done_callback(done)
        return True

    @Slot(object)
    def _accept_masks(self, payload):
        if self._closed:
            return
        target, volume, phase, records, evaluations, error = payload
        try:
            if self._cancel.is_set() or isinstance(error, InterruptedError):
                raise InterruptedError()
            if error is not None:
                raise error
            voi = target()
            if (
                voi is None
                or voi._closed
                or voi._phase != phase
                or not voi._phase_ready
                or voi._draft
                or voi.sources.get(volume.series_uid) is None
                or voi.sources[volume.series_uid].geometry != volume.geometry
            ):
                raise ValueError(_msg("seg.targetChanged"))
            # Reject a result that could not survive undo/save before mutating
            # the live scene. Masks stay embedded; the SEG file may be moved.
            from qt_dicom_viewer.core.workspace_state import dumps, MAX_MASK_VOXELS

            combined = [*voi.records, *records]
            if sum(r["mask"].size for r in combined if "mask" in r) > MAX_MASK_VOXELS:
                raise ValueError(_msg("seg.tooLarge"))
            dumps({"voi": combined})
            voi.add_masks(records, evaluations)
            self._finish(_msg("seg.loaded", count=len(records)), False, "")
        except InterruptedError:
            self._finish(_msg("results.cancelled"), False, "")
        except Exception as exc:
            self._finish(_msg("seg.failed", reason=error_message(exc)), True, "")

    @Slot(object, bool, str)
    def _finish(self, message, error, path):
        self._busy, self._message, self._error, self._result_path = (
            False,
            message,
            error,
            path,
        )
        self.changed.emit()

    def shutdown(self):
        self._closed = True
        self._cancel.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
