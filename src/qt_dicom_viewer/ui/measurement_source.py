"""Data-only sampling records shared by navigation and independent report rendering."""
from dataclasses import fields, replace
from uuid import uuid4

from qt_dicom_viewer.model.render_models import StackRenderRequest, MprRenderRequest

REQUESTS = {"stack": StackRenderRequest, "mpr": MprRenderRequest}


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
