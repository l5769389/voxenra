"""Data-only sampling records shared by navigation and independent report rendering."""
from dataclasses import fields, replace
from uuid import uuid4
import math
import re

from qt_dicom_viewer.model.render_models import StackRenderRequest, MprRenderRequest

REQUESTS = {"stack": StackRenderRequest, "mpr": MprRenderRequest}


def validate_cpr_source(source):
    """CPR sources are real planes with bounded, data-only provenance."""
    from qt_dicom_viewer.model.dicom_core import MprFrame, MprGridSpec
    metadata = source.get("cpr")
    if metadata is None:
        return None
    if not isinstance(metadata, dict) or source.get("kind") != "mpr":
        raise ValueError("Invalid CPR measurement source")
    role = metadata.get("role")
    index, count = metadata.get("frameIndex"), metadata.get("frameCount")
    if (role not in ("reference-a", "reference-b", "cross") or type(index) is not int
            or type(count) is not int or not 0 <= index < count
            or role == "cross" and count > 4097
            or not isinstance(metadata.get("fingerprint"), str)
            or re.fullmatch(r"[a-f0-9]{64}", metadata["fingerprint"]) is None):
        raise ValueError("Invalid CPR plane provenance")
    parameters = source.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("Invalid CPR measurement parameters")
    grid = parameters.get("mpr_grid")
    if (not isinstance(parameters.get("mpr_frame"), MprFrame) or not isinstance(grid, MprGridSpec)
            or not 1 <= grid.rows <= 4097 or not 1 <= grid.columns <= 4097
            or grid.rows*grid.columns > 4_194_304):
        raise ValueError("Invalid CPR measurement plane")
    if role == "cross":
        distance = metadata.get("distanceMm")
        if (not isinstance(metadata.get("pathId"), str) or not 1 <= len(metadata["pathId"]) <= 128
                or type(metadata.get("pathRevision")) is not int or metadata["pathRevision"] < 1
                or type(metadata.get("algorithmVersion")) is not int or metadata["algorithmVersion"] != 1
                or type(distance) not in (int, float) or not math.isfinite(distance) or not 0 <= distance <= 10000
                or not isinstance(metadata.get("pathName", ""), str) or len(metadata.get("pathName", "")) > 256):
            raise ValueError("Invalid CPR path provenance")
    return metadata


def capture_request(request):
    kind = next((key for key, cls in REQUESTS.items() if isinstance(request, cls)), None)
    if kind is None:
        return {}
    return {"kind": kind, "parameters": {f.name: getattr(request, f.name) for f in fields(request)
            if f.name not in ("request_id", "viewport_id", "cancel_event")}}


def restore_request(source, viewport_id, *, display=None, cancel_event=None):
    cls = REQUESTS.get(source.get("kind"))
    if cls is None:
        raise ValueError("Reference sampling information is unavailable")
    params = dict(source["parameters"])
    if display:
        params.update(display)
    return cls(request_id=str(uuid4()), viewport_id=viewport_id, cancel_event=cancel_event, **params)


def display_parameters(view):
    state = view.viewport_state
    result = dict(window=state.window, inverted=state.inverted, color_map=state.display_style.color_map)
    if hasattr(view, "display_mapping_intent"):
        result["display_mapping"] = view.display_mapping_intent
    return result


def frame_identity(series_uid, frame, projection=None, slab=0., role="", phase=None):
    geometry = frame.geometry
    pose = (geometry.pixel_spacing.row, geometry.pixel_spacing.column,
            *(geometry.image_position_patient or ()), *(geometry.image_orientation_patient or ()))
    key = (series_uid, frame.instance_meta.sop_instance_uid, frame.slice_index,
           geometry.rows, geometry.columns, tuple(round(float(v), 7) for v in pose))
    context = ()
    if projection is not None or role == "mip":
        context = ("projection", str(projection or "mip"), slab)
    if phase is not None:
        context += ("phase", phase)
    if context:
        key += (context,)
    return key
