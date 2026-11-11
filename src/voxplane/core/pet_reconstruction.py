"""Linked PET MPR/fusion reconstruction on physical sampling grids."""
from voxplane.i18n import message as _msg
from collections import OrderedDict
from dataclasses import replace
from itertools import product

import numpy as np

from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.mpr_reslicer import MprReslicer
from voxplane.core.pet_fusion import transformed_volume, pet_rgb, blend_pet_ct
from voxplane.model import (MprFrame, MprState, MprPlane, MprViewAnchors, MprGridSpec,
                                  FrameDisplayMeta, ImageGeometryMeta, PixelSpacing,
                                  WindowLevel, TwoDViewType)
from voxplane.model.dicom_core import MprSlice
from voxplane.model.render_models import (PetBatchRenderResult,
                                                PetMipRenderResult, MprRenderResult)


class PetReconstructor:
    def __init__(self, catalog, volumes):
        self.catalog = catalog
        self.volumes = volumes
        self.reslicer = MprReslicer()
        self._cache = OrderedDict()
        self._mip_cache, self._display_cache, self._unit_cache = OrderedDict(), OrderedDict(), OrderedDict()
        self._gesture_volumes = OrderedDict()

    def _cached(self, key, build):
        cache, limit = ((self._mip_cache, 4) if key[0] == "mip" else
                        (self._unit_cache, 4) if key[0] == "unit" else
                        (self._display_cache, 16) if key[0] == "display" else (self._cache, 24))
        if key not in cache:
            cache[key] = build()
            while len(cache) > limit:
                cache.popitem(last=False)
        cache.move_to_end(key)
        return cache[key]

    @staticmethod
    def _grid_key(g):
        # Frame centers/anchors can vary while the patient-space grid is identical.
        # Round below a micron to remove floating-point cancellation noise only.
        return (g.rows, g.columns, *np.round([*g.image_origin_patient,
            *g.row_direction_patient, *g.column_direction_patient,
            g.row_spacing, g.column_spacing], 7))

    def _volumes(self, request, pet_series, ct_series):
        key = (request.viewport_id, request.interaction_id, id(pet_series), id(ct_series))
        interactive = request.interaction_kind == "locator" and not request.interaction_final
        if interactive and key in self._gesture_volumes:
            return self._gesture_volumes[key]
        result = (self.volumes.get_or_build(pet_series),
                  self.volumes.get_or_build(ct_series) if ct_series else None)
        for old in list(self._gesture_volumes):
            if old[0] == request.viewport_id:
                del self._gesture_volumes[old]
        if interactive:
            self._gesture_volumes[key] = result
            while len(self._gesture_volumes) > 4:
                self._gesture_volumes.popitem(last=False)
        return result

    def render(self, request):
        pet_series = self.catalog.get_series(request.series_uid)
        ct_series = self.catalog.get_series(request.ct_series_uid) if request.ct_series_uid else None
        if pet_series is None or pet_series.modality.upper() != "PT":
            raise ValueError(_msg('text.0147'))
        if request.ct_series_uid and (ct_series is None or ct_series.modality.upper() != "CT"):
            raise ValueError(_msg('text.0148'))
        pet_base, ct = self._volumes(request, pet_series, ct_series)
        available = {o.unit_id for o in pet_base.pixel_value_meta.unit_options if o.available}
        unit = request.value_unit if request.value_unit in available else pet_base.pixel_value_meta.unit_id
        pet = self._cached(("unit", pet_base.fingerprint, pet_base.series_uid, unit),
                           lambda: pet_base.in_unit(unit))
        transformed_pet = transformed_volume(pet, request.transform) if ct else pet
        reference = ct or pet
        state = request.state
        if state is None:
            frame = MprFrame.standard_lps(reference.geometry.center_patient)
            grids = self.reslicer.create_view_grids(reference, frame)
            state = MprState(frame=frame, view_grids=grids,
                             view_anchors=MprViewAnchors.centered(grids))
        pet_window = request.pet_window
        if pet_window is None or (request.value_unit and request.value_unit != unit):
            ratio = pet.pixel_value_meta.scale_from_source / pet_base.pixel_value_meta.scale_from_source
            upper = (pet_base.default_window.center + pet_base.default_window.width / 2) * ratio
            pet_window = WindowLevel(upper / 2, upper)
        minimum = 0.01 if pet.pixel_value_meta.is_suv else 0.001
        upper = max(minimum, pet_window.center + pet_window.width / 2)
        pet_window = WindowLevel(upper / 2, upper)
        ct_window = request.ct_window or (ct.default_window if ct else None)
        frames = []
        ct_samples = None
        warning = ""
        for role, viewport_id in request.viewports:
            self._check_cancelled(request.cancel_event)
            if role == "mip":
                key = ("mip", pet_base.fingerprint, pet_base.series_uid, unit,
                       request.transform, request.preview)
                mip, peaks = self._cached(key, lambda: self._full_mip(
                    transformed_pet, request.preview, request.cancel_event))
                pixels, geometry = mip.modality_pixels, mip.geometry
                content_key = ("display", key, pet_window, request.pet_color_map)
                def render_mip():
                    gray = DicomLoader.apply_window(pixels, pet_window, False, minimum)
                    return gray if request.pet_color_map == "grayscale" else pet_rgb(gray, request.pet_color_map)
                image = self._cached(content_key, render_mip)
                frames.append(PetMipRenderResult(
                    response_id=request.request_id, viewport_id=viewport_id, series_uid=pet.series_uid,
                    view_type=TwoDViewType.PET_MIP, image=image, modality_pixel=pixels,
                    frame_meta=self._meta(pet, mip, pet_window), mpr_frame=geometry.frame,
                    plane_geometry=geometry, peak_positions=peaks, preview=request.preview, content_key=content_key))
                continue
            plane = request.plane if ct else MprPlane(role)
            geometry, index, count = self.reslicer.prepare_plane(reference, plane, state.frame,
                view_roll_radians=state.view_rolls.for_plane(plane),
                grid_spec=state.view_grids.for_plane(plane) if state.view_grids else None,
                grid_anchor=state.view_anchors.for_plane(plane) if state.view_anchors else None)
            grid_key = self._grid_key(geometry)
            ref_key = ("plane", reference.fingerprint, reference.series_uid,
                       unit if not ct else "ct", grid_key)
            sampled_reference = self._cached(ref_key, lambda: self.reslicer._sample_plane(reference, geometry))
            ref_slice = MprSlice(sampled_reference, geometry, index, count)
            pet_key = ("pet-plane", pet_base.fingerprint, pet.series_uid, unit, request.transform, grid_key) if ct else ref_key
            pet_pixels = (self._cached(pet_key, lambda: self.reslicer._sample_plane(transformed_pet, geometry))
                          if ct else sampled_reference)
            pet_gray_key = ("display", pet_key, pet_window, "gray")
            pet_gray = self._cached(pet_gray_key, lambda: DicomLoader.apply_window(pet_pixels, pet_window, False, minimum))
            if ct:
                sampled_ct = sampled_reference
                ct_gray_key = ("display", ref_key, ct_window, "gray", request.ct_inverted)
                ct_gray = self._cached(ct_gray_key, lambda: DicomLoader.apply_window(sampled_ct, ct_window, request.ct_inverted))
                if role == "fusion":
                    ct_samples = sampled_ct
                    overlap = self._cached(("overlap", ref_key, pet_key),
                        lambda: bool((np.isfinite(sampled_ct) & np.isfinite(pet_pixels)).any()))
                    if not overlap:
                        warning = _msg('text.0149')
            if role == "ct":
                pixels, image, volume, window, content_key = sampled_ct, ct_gray, ct, ct_window, ct_gray_key
            elif role == "fusion":
                pixels, volume, window = pet_pixels, pet, pet_window
                content_key = ("display", ct_gray_key, pet_gray_key, request.opacity, request.fusion_color_map)
                image = self._cached(content_key, lambda: blend_pet_ct(ct_gray, pet_gray, pet_pixels, request.opacity, request.fusion_color_map))
            else:
                pixels, volume, window = pet_pixels, pet, pet_window
                content_key = ("display", pet_gray_key, request.pet_color_map)
                image = self._cached(content_key, lambda: pet_gray if request.pet_color_map == "grayscale" else pet_rgb(pet_gray, request.pet_color_map))
            frames.append(MprRenderResult(response_id=request.request_id, viewport_id=viewport_id,
                series_uid=volume.series_uid, view_type=plane, image=image, modality_pixel=pixels,
                frame_meta=self._meta(volume, ref_slice, window, request.ct_inverted if role == "ct" else False), mpr_frame=state.frame,
                plane_geometry=geometry, mpr_view_grids=state.view_grids, content_key=content_key,
                volume=ct if role == "ct" else transformed_pet))
        return PetBatchRenderResult(response_id=request.request_id, viewport_id=request.viewport_id,
            series_uid=pet.series_uid, frames=tuple(frames), state=state, pet_volume=pet,
            ct_volume=ct, pet_window=pet_window, ct_window=ct_window,
            ct_samples=ct_samples, warning=warning, request=request)

    @staticmethod
    def _meta(volume, sampled, window, inverted=False):
        g = sampled.geometry
        spacing = PixelSpacing(g.row_spacing, g.column_spacing)
        instance = replace(volume.representative_instance_meta, sop_instance_uid=None,
                           rows=g.rows, columns=g.columns, pixel_spacing=(g.row_spacing, g.column_spacing),
                           image_position=g.image_origin_patient)
        return FrameDisplayMeta(slice_index=sampled.slice_index, slice_count=sampled.slice_count,
            window=window, inverted=inverted, instance_meta=instance,
            geometry=ImageGeometryMeta(g.rows, g.columns, spacing, g.image_origin_patient,
                                       g.image_orientation_patient), pixel_value_meta=volume.pixel_value_meta)

    @staticmethod
    def _check_cancelled(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError(_msg('text.0150'))

    def _full_mip(self, volume, preview=False, cancel_event=None):
        frame = MprFrame.standard_lps(volume.geometry.center_patient)
        grid = self.reslicer.create_view_grids(volume, frame).for_plane(MprPlane.CORONAL)
        if preview:
            # Keep the physical field of view while bounding interactive work.
            rows, columns = min(128, grid.rows), min(128, grid.columns)
            grid = MprGridSpec(rows=rows, columns=columns,
                row_spacing=grid.row_spacing * grid.rows / rows,
                column_spacing=grid.column_spacing * grid.columns / columns)
        sampled = self.reslicer.reslice(volume, MprPlane.CORONAL, frame, grid_spec=grid)
        g = sampled.geometry
        corners = np.array([(*p, 1) for p in product(*[(0, n-1) for n in volume.modality_pixels.shape])])
        positions = (volume.geometry.voxel_to_patient @ corners.T).T[:, :3]
        normal = np.asarray(g.navigation_direction_patient)
        depths = (positions - g.image_origin_patient) @ normal
        count = max(2, int(np.ceil(np.ptp(depths) / g.navigation_spacing)) + 1)
        if preview:
            count = min(64, count)
        maximum = np.full((g.rows, g.columns), -np.inf, dtype=np.float32)
        peak_depth = np.full_like(maximum, np.nan)
        # Bounded memory: one sampled plane at a time, no full CT-grid PET copy.
        for offset in np.linspace(depths.min(), depths.max(), count):
            self._check_cancelled(cancel_event)
            pixels = self.reslicer._sample_plane(volume, g, float(offset))
            better = np.isfinite(pixels) & (pixels > maximum)
            maximum[better] = pixels[better]
            peak_depth[better] = offset
        maximum[~np.isfinite(maximum)] = np.nan
        row, col = np.indices(maximum.shape)
        peaks = (np.asarray(g.image_origin_patient)[None, None, :]
                 + row[..., None] * g.row_spacing * np.asarray(g.row_direction_patient)
                 + col[..., None] * g.column_spacing * np.asarray(g.column_direction_patient)
                 + peak_depth[..., None] * normal).astype(np.float32)
        return replace(sampled, modality_pixels=maximum), peaks
