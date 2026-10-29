"""Portable CPR edits and view state; never contains volumes or derived images."""
from dataclasses import asdict

from qt_dicom_viewer.model.cpr import ALGORITHM_VERSION, CprError, CprPath, CprSettings, finite_number

MAX_PATHS = 64
ROLES = ("reference-a", "reference-b", "curved", "cross")


def default_cpr_session(series_uid: str, frame_of_reference_uid: str = "") -> dict:
    return dict(algorithmVersion=ALGORITHM_VERSION,
                source=dict(seriesUid=series_uid, frameOfReferenceUid=frame_of_reference_uid,
                            fingerprint=""), paths=[], selected="", draft=(),
                referencePlanes=("axial", "coronal"), referenceCenters=None,
                positionMm=0., rangeMm=(0., 0.), crossWidthMm=40., focusedRole="")


def path_record(path: CprPath, settings: CprSettings) -> dict:
    return dict(id=path.path_id, name=path.name, points=path.control_points,
                revision=path.revision, settings=asdict(settings))


def unpack_path(record: dict) -> tuple[CprPath, CprSettings]:
    if not isinstance(record, dict) or set(record) != {"id", "name", "points", "revision", "settings"}:
        raise CprError("Invalid saved CPR path")
    try:
        path = CprPath(record["id"], record["name"], record["points"], record["revision"])
        settings = CprSettings(**record["settings"])
    except (KeyError, TypeError) as error:
        raise CprError("Invalid saved CPR path settings") from error
    return path, settings


def _point(point):
    if not isinstance(point, (tuple, list)) or len(point) != 3:
        raise CprError("Saved CPR points must contain three coordinates")
    return tuple(finite_number(value, "coordinate") for value in point)


def validate_cpr_session(state: dict) -> dict:
    """Return normalized independent values or reject before modifying live state."""
    if not isinstance(state, dict) or set(state) != set(default_cpr_session("")):
        raise CprError("Invalid saved CPR session")
    if type(state["algorithmVersion"]) is not int or state["algorithmVersion"] != ALGORITHM_VERSION:
        raise CprError("Unsupported CPR algorithm version")
    source = state["source"]
    if (not isinstance(source, dict) or set(source) != {"seriesUid", "frameOfReferenceUid", "fingerprint"}
            or any(not isinstance(v, str) or len(v) > 4096 for v in source.values())
            or not source["seriesUid"]):
        raise CprError("Invalid saved CPR source identity")
    paths = state["paths"]
    if not isinstance(paths, (list, tuple)) or len(paths) > MAX_PATHS:
        raise CprError("A CPR session supports at most 64 paths")
    normalized = [path_record(*unpack_path(record)) for record in paths]
    ids = [record["id"] for record in normalized]
    selected = state["selected"]
    if len(ids) != len(set(ids)) or not isinstance(selected, str) or selected and selected not in ids:
        raise CprError("Invalid saved CPR path selection")
    draft = state["draft"]
    if not isinstance(draft, (list, tuple)) or len(draft) > 4096:
        raise CprError("A draft supports at most 4096 control points")
    draft = tuple(_point(point) for point in draft)
    planes = state["referencePlanes"]
    if (not isinstance(planes, (list, tuple)) or len(planes) != 2
            or any(plane not in ("axial", "coronal", "sagittal") for plane in planes)):
        raise CprError("Invalid saved CPR reference planes")
    centers = state["referenceCenters"]
    if centers is not None:
        if not isinstance(centers, (list, tuple)) or len(centers) != 2:
            raise CprError("Invalid saved CPR reference positions")
        centers = tuple(_point(point) for point in centers)
    position = finite_number(state["positionMm"], "position")
    width = finite_number(state["crossWidthMm"], "cross-section width")
    interval = state["rangeMm"]
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        raise CprError("Invalid saved CPR length interval")
    interval = tuple(finite_number(value, "interval position") for value in interval)
    if position < 0 or position > 10000 or not 0 < width <= 500 or not 0 <= interval[0] <= interval[1] <= 10000:
        raise CprError("Saved CPR distance or field width is out of range")
    focused = state["focusedRole"]
    if focused not in ("", *ROLES):
        raise CprError("Invalid saved CPR focused viewport")
    return dict(algorithmVersion=ALGORITHM_VERSION, source=dict(source), paths=normalized,
                selected=selected, draft=draft, referencePlanes=tuple(planes),
                referenceCenters=centers, positionMm=position, rangeMm=interval,
                crossWidthMm=width, focusedRole=focused)
