"""Existing image interactions applied to CPR references and true cross-sections."""
from dataclasses import replace
from uuid import uuid4

import numpy as np
from PySide6.QtCore import Property, Signal, Slot

from qt_dicom_viewer.model import MprPlane
from qt_dicom_viewer.model.dicom_core import MprFrame, MprGridSpec
from qt_dicom_viewer.model.dicom_types import FrameDisplayMeta, ImageGeometryMeta, PixelSpacing
from qt_dicom_viewer.model.render_models import MprRenderRequest, StackRenderResult
from qt_dicom_viewer.ui.measurement_source import capture_request, display_parameters
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from .image_2d_viewport_controller import Image2DViewportController


class CprViewportController(Image2DViewportController):
    cprChanged = Signal()
    exportReadinessChanged = Signal()

    def __init__(self, config, tools, parent):
        self._cpr = parent
        self.plane_geometry = None
        self._historical = False
        super().__init__(config, tools, parent=parent)
        parent.cprChanged.connect(self.exportReadinessChanged)
        self.cprChanged.connect(self.overlayChanged)

    @Property(bool, notify=exportReadinessChanged)
    def exportReady(self):
        return self._cpr.export_ready()

    @Property(str, notify=exportReadinessChanged)
    def exportRevision(self):
        return self._cpr.export_revision()

    @Property(bool, constant=True)
    def isCprViewport(self):
        return True

    @_TextProperty('QVariantMap', notify=Image2DViewportController._i18n_overlayInfo,
                   notify_name='_i18n_overlayInfo', source_notify='overlayChanged')
    def overlayInfo(self):
        info = Image2DViewportController.overlayInfo.fget(self)
        info.update(cprRole=self.viewportRole, cprReconstruction='', cprDistance='')
        result = self._cpr._result
        if self.viewportRole == 'curved' and result is not None and result.curve is not None:
            # Describe the accepted raster, not controls awaiting reconstruction.
            settings = result.curve.settings
            mode = 'THIN'
            if settings.projection != 'thin' and settings.thickness_mm > 0:
                mode = ('MIP' if settings.projection == 'mip' else 'MEAN')
                mode += f' {settings.thickness_mm:g} mm'
            info['cprReconstruction'] = f'CPR · {mode}'
        if self._frame_meta is not None and self.viewportRole in ('curved', 'cross'):
            if self._historical:
                source = self._measure_controller.current_source.get('cpr', {})
                distance = source.get('distanceMm')
                if distance is not None:
                    # Older paths may have a different length. Only use the
                    # distance saved with this exact measurement plane.
                    info['cprDistance'] = f's: {distance:.1f} mm'
            elif result is not None and result.curve is not None and result.section is not None:
                # A requested position can already be ahead of the displayed
                # section. Keep both numbers tied to the accepted result.
                info['cprDistance'] = (f's: {result.section.distance_mm:.1f} / '
                                       f'{result.curve.centerline.length_mm:.1f} mm')
        return info

    @Property(bool, notify=cprChanged)
    def hasPhysicalSpacing(self):
        return self.viewportRole != "curved" and self.plane_geometry is not None

    @Property('QVariantList', notify=cprChanged)
    def cprPoints(self):
        return self._cpr.projected_points(self)

    @Property(bool, notify=cprChanged)
    def historicalPlane(self):
        return self._historical

    @Property(str, notify=cprChanged)
    def historicalDescription(self):
        if not self._historical:
            return ""
        from qt_dicom_viewer.i18n import message
        source = self._measure_controller.current_source.get("cpr", {})
        if source.get("role") == "cross":
            return str(message("cpr.historicalDescription", revision=source["pathRevision"],
                               distance=f'{source["distanceMm"]:.1f}'))
        return str(message("cpr.historical"))

    @Property(bool, notify=cprChanged)
    def cprEditing(self):
        return self._cpr.pathEditing and self.viewportRole.startswith("reference")

    @Property(bool, notify=cprChanged)
    def cprDrawing(self):
        return self.cprEditing and self._cpr.drawing

    @Property(float, notify=cprChanged)
    def cprMarkerColumn(self):
        result = self._cpr._result
        if result is None or result.curve is None:
            return -1.
        return self._cpr.positionMm / result.curve.centerline.spacing_mm

    def present_cpr(self, pixels, geometry, *, index=0, count=1, spacing=None, provenance=None):
        self.plane_geometry = geometry
        self._historical = False
        volume = self._cpr._volume
        rows, columns = pixels.shape
        spacing = spacing or (geometry.row_spacing, geometry.column_spacing)
        position = geometry.image_origin_patient if geometry is not None else None
        orientation = geometry.image_orientation_patient if geometry is not None else None
        meta = replace(volume.representative_instance_meta, instance_number=None,
                       sop_instance_uid=None, frame_index=None, rows=rows, columns=columns,
                       pixel_spacing=spacing if geometry is not None else None,
                       image_position=position, slice_location=None)
        frame = FrameDisplayMeta(index, count, self.current_window or volume.default_window,
                    self.inverted, meta, ImageGeometryMeta(rows, columns,
                    PixelSpacing(*spacing), position, orientation), volume.pixel_value_meta)
        request_id = str(uuid4())
        self._latest_request_id = request_id
        source = {}
        if geometry is not None:
            # Capture an ordinary physical MPR plane for navigation/reporting.
            center = geometry.image_point_to_patient(column=(columns-1)/2, row=(rows-1)/2)
            column = np.asarray(orientation[:3])
            row = np.asarray(orientation[3:])
            request = MprRenderRequest(request_id=request_id, viewport_id=self.viewportId,
                series_uid=volume.series_uid, plane=MprPlane.AXIAL,
                mpr_frame=MprFrame(center, tuple(column), tuple(row), tuple(np.cross(column, row))),
                mpr_grid=MprGridSpec(rows, columns, *spacing),
                **display_parameters(self))
            source = capture_request(request)
            source["cpr"] = dict(provenance or {}, frameIndex=index, frameCount=count,
                                  role=self.viewportRole, fingerprint=self._cpr._fingerprint)
        self._measurement_requests = {request_id: source}
        result = StackRenderResult(response_id=request_id, viewport_id=self.viewportId,
            series_uid=volume.series_uid, view_type=self.viewport_config.viewport_type,
            image=None, modality_pixel=pixels, frame_meta=frame)
        self.handleRenderResult(result)
        if self.viewportRole == "curved" and self._cpr.current_path is not None:
            from hashlib import blake2b
            path = self._cpr.current_path
            identity = blake2b(repr((path.path_id, path.revision, path.control_points,
                                     self._cpr.current_settings)).encode(), digest_size=16).hexdigest()
            # Section navigation leaves the full curved raster unchanged.
            self._text_annotation_controller.set_frame(volume.series_uid,
                replace(frame, slice_index=0), source_context=("cpr", identity))
        self.refresh_window_image()
        self.cprChanged.emit()

    def clear_cpr(self):
        self.cancelMeasurement()
        self._historical = False
        self._frame_meta = self._modality_pixel = self.plane_geometry = None
        self._has_image = False
        self._measure_controller.hide_frame()
        self.imageSourceChanged.emit()
        self.imageDimensionChanged.emit()
        self.cprChanged.emit()

    def _build_render_request(self, *, initial):
        raise RuntimeError("CPR samples are scheduled by the CPR workspace")

    def request_render(self):
        self.refresh_window_image()

    def _validate_render_result(self, result):
        if result.modality_pixel is None or result.modality_pixel.ndim != 2:
            raise ValueError("CPR viewport requires a two-dimensional image")

    def _apply_specific_render_result(self, result):
        pass

    def apply_slice_index(self, index):
        self._cpr.navigate_view(self, index)

    def apply_window_level(self, result):
        self._cpr.set_linked_window(result)

    def _measurement_context(self, *args, **kwargs):
        if self.viewportRole == "curved" or not self._cpr.quantification_ready(self):
            return None
        return super()._measurement_context(*args, **kwargs)

    @Slot(float, float, float, result=bool)
    def cprTap(self, column, row, tolerance):
        return self._cpr.path_tap(self, column, row, tolerance)

    @Slot(float, float, float, result=bool)
    def cprBeginDrag(self, column, row, tolerance):
        return self._cpr.begin_path_drag(self, column, row, tolerance)

    @Slot(float, float, result=bool)
    def cprMoveDrag(self, column, row):
        return self._cpr.move_path_drag(self, column, row)

    @Slot(float, float, result=bool)
    def cprEndDrag(self, column, row):
        return self._cpr.end_path_drag(self, column, row)

    @Slot(result=bool)
    def cprDoubleClick(self):
        # One dispatcher owns this gesture: finishing a draft must never also
        # maximize after finishPath changes the editing state during the event.
        if self.cprFinish() or self.cprEditing:
            return True
        if self.activeInteraction in ("measure:freehand", "measure:curve"):
            return False
        self._cpr.activateViewport(self.viewportId)
        self._cpr.focusSingleViewport("" if self._cpr.focusedViewportId else self.viewportId)
        return True

    @Slot(result=bool)
    def cprFinish(self):
        if self.cprEditing:
            self._cpr.finishEditing()
            return True
        return False

    @Slot(result=bool)
    def cprCancel(self):
        return self._cpr.cancel_operation()

    @Slot(result=bool)
    def cprDelete(self):
        if self.cprEditing:
            self._cpr.deleteSelectedPoint()
            return True
        return False
