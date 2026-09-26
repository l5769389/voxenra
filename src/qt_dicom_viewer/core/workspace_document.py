"""Workspace manifests reference original files/archives, never temporary extracts."""
from qt_dicom_viewer.i18n import message as _msg
from pathlib import Path

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner, _build_series_from_map, _build_series_record
from qt_dicom_viewer.core.workspace_state import loads, MAX_DOCUMENT_BYTES
from qt_dicom_viewer.model import DicomFolderScanSnapshot

FORMAT = "VoxenraWorkspace"
VERSION = 1


def instance_signature(instance):
    result = {key: getattr(instance, key, None) for key in (
        "sop_instance_uid", "rows", "columns", "number_of_frames",
        "image_position_patient", "image_orientation_patient", "pixel_spacing")}
    if instance.frame_index is not None:
        result["frame_index"] = instance.frame_index
    if instance.file_identity[1] != instance.sop_instance_uid:
        result["media_storage_sop_instance_uid"] = instance.file_identity[1]
    return result


def _signature_identity(signature):
    uid = signature["sop_instance_uid"]
    return (uid, signature.get("media_storage_sop_instance_uid") or uid,
            signature.get("frame_index"))


def _resolve_signature(signature, current):
    instance = current.get(_signature_identity(signature))
    if instance is not None and instance_signature(instance) == signature:
        return instance
    if "media_storage_sop_instance_uid" in signature:
        return None
    # Older workspaces had no file-meta identity. Only restore when their
    # complete saved geometry identifies exactly one source object.
    matches = []
    for candidate in current.values():
        if (candidate.sop_instance_uid != signature["sop_instance_uid"]
                or candidate.frame_index != signature.get("frame_index")):
            continue
        actual = instance_signature(candidate)
        actual.pop("media_storage_sop_instance_uid", None)
        if actual == signature:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def source_manifest(series, store, document_path):
    instances = {i.frame_identity: i for group in (series, *series.phases) for i in group.instances}
    paths = {store.source_for(i.path) for i in instances.values()}
    sources = []
    for source in sorted(paths):
        relative = ""
        try:
            relative = source.relative_to(Path(document_path).parent).as_posix()
        except ValueError:
            pass
        sources.append({"path": str(source), "relative": relative})
    return {"uid": series.series_instance_uid, "sources": sources,
            "instances": [instance_signature(i) for i in instances.values()]}


def read_document(path):
    path = Path(path)
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError(_msg('text.0127'))
    document = loads(path.read_bytes())
    if not isinstance(document, dict) or document.get("format") != FORMAT or document.get("version") != VERSION:
        raise ValueError(_msg('text.0210'))
    series, tabs = document.get("series"), document.get("tabs")
    if (not isinstance(series, list) or not isinstance(tabs, list)
            or len(series) > 10000 or len(tabs) > 64):
        raise ValueError(_msg('text.0211'))
    known = set()
    count = 0
    for record in series:
        if not isinstance(record, dict) or not isinstance(record.get("uid"), str) or record["uid"] in known:
            raise ValueError(_msg('text.0212'))
        known.add(record["uid"])
        if not isinstance(record.get("sources"), list) or not record["sources"]:
            raise ValueError(_msg('text.0213'))
        for source in record["sources"]:
            if not isinstance(source, dict):
                raise ValueError(_msg('text.0213'))
            for key in ("path", "relative"):
                value = source.get(key)
                if not isinstance(value, str) or len(value) > 32768 or "\0" in value:
                    raise ValueError(_msg('text.0214'))
        signatures = record.get("instances")
        if not isinstance(signatures, list) or not signatures or any(
                not isinstance(sig, dict) or not isinstance(sig.get("sop_instance_uid"), str)
                or not isinstance(sig.get("media_storage_sop_instance_uid", ""), str)
                for sig in signatures):
            raise ValueError(_msg('text.0215'))
        count += len(signatures)
    if count > 100000:
        raise ValueError(_msg('text.0216'))
    for tab in tabs:
        if (not isinstance(tab, dict) or not isinstance(tab.get("series"), list)
                or any(uid not in known for uid in tab["series"])
                or tab.get("type") not in ("2d", "compare2d", "comparempr", "mpr", "3d", "4d", "montage", "tag", "petctfusion", "settings", "pacs", "manual")):
            raise ValueError(_msg('text.0217'))
        _validate_tab(tab)
    for key in ("sidebar", "selected", "collapsed"):
        if not isinstance(document.get(key, []), list) or any(not isinstance(x, str) for x in document.get(key, [])):
            raise ValueError(_msg('text.0218'))
    if (not isinstance(document.get("search", ""), str)
            or not isinstance(document.get("activeSeries", ""), str)
            or not isinstance(document.get("layout", {}), dict)):
        raise ValueError(_msg('text.0219'))
    sidebar = document.get("sidebarLayout", {"width": 300., "collapsed": False})
    if (not isinstance(sidebar, dict) or type(sidebar.get("width")) not in (int, float)
            or not 200 <= sidebar["width"] <= 350 or type(sidebar.get("collapsed")) is not bool):
        raise ValueError(_msg('text.0220'))
    return document


def _validate_tab(tab):
    from qt_dicom_viewer.model import ViewportState, MprState, MprProjectionSettings, WindowLevelChange
    from qt_dicom_viewer.model.measure import LengthMeasurement, AngleMeasurement, RoiMeasurement
    from qt_dicom_viewer.ui.controller.viewport.controller.text_annotation_controller import TextAnnotation
    utility = tab["type"] in ("settings", "pacs", "manual")
    if (not isinstance(tab.get("label"), str) or len(tab["series"]) not in ((0,) if utility else range(1, 37) if tab["type"] == "2d" else (2, 3, 4) if tab["type"] == "compare2d" else (1, 2))):
        raise ValueError(_msg('text.0221'))
    if "twoDLayout" in tab:
        from qt_dicom_viewer.core.scene_layout import validate_scene
        validate_scene(tab["twoDLayout"], tab["series"])
    if tab["type"] == "comparempr":
        record = tab.get("mprCompare")
        if (len(tab["series"]) != 2 or len(set(tab["series"])) != 2
                or not isinstance(record, dict)
                or record.get("pairPlane") not in ("", "axial", "coronal", "sagittal")
                or any(type(record.get(key)) is not bool for key in ("positionLinked", "rotationLinked"))
                or not isinstance(record.get("groups"), list) or len(record["groups"]) != 2):
            raise ValueError(_msg('text.0222'))
        from math import isfinite
        scales = record.get("zoomScales", {})
        if (any(type(record.get(key, False)) is not bool for key in ("windowLinked", "zoomLinked"))
                or not isinstance(scales, dict)
                or any(key not in ("axial", "coronal", "sagittal") or type(value) not in (int, float)
                       or not isfinite(value) or value <= 0 for key, value in scales.items())):
            raise ValueError(_msg('text.0222'))
        for uid, group in zip(tab["series"], record["groups"]):
            if (not isinstance(group, dict) or group.get("type") != "mpr"
                    or group.get("series") != [uid] or "mprCompare" in group):
                raise ValueError(_msg('text.0222'))
            _validate_tab(group)
    if tab["type"] == "compare2d":
        from qt_dicom_viewer.core.compare import SYNC_OPERATIONS
        sync = tab.get("compareSync", {})
        if (not 2 <= len(tab["series"]) <= 4 or len(set(tab["series"])) != len(tab["series"])
                or tab.get("compareScrollMode", "relative") not in ("relative", "spatial")
                or not isinstance(sync, dict) or any(key not in SYNC_OPERATIONS or type(value) is not bool
                                                   for key, value in sync.items())):
            raise ValueError(_msg('text.0222'))
    if utility or tab["type"] == "tag":
        return
    if (not isinstance(tab.get("views"), dict) or not isinstance(tab.get("edits"), dict)
            or not isinstance(tab.get("projection"), MprProjectionSettings)
            or tab.get("mpr") is not None and not isinstance(tab["mpr"], MprState)
            or tab.get("linkedWindow") is not None and not isinstance(tab["linkedWindow"], WindowLevelChange)
            or type(tab.get("phase")) is not int or tab["phase"] < 0
            or type(tab.get("fps")) not in (int, float) or not 1 <= tab["fps"] <= 60):
        raise ValueError(_msg('text.0222'))
    from qt_dicom_viewer.model import MprFrame
    for state in tab["views"].values():
        if not isinstance(state, dict): raise ValueError(_msg('text.0222'))
        source = state.get("independentSource")
        if source is not None:
            from qt_dicom_viewer.ui.measurement_source import restore_request
            try:
                if not isinstance(source, dict) or source.get("kind") != "mpr":
                    raise ValueError("Invalid independent plane")
                request = restore_request(source, "validate")
                if (request.series_uid not in tab["series"] or not isinstance(request.mpr_frame, MprFrame)
                        or source.get("navigation") is not None and not isinstance(source["navigation"], MprState)):
                    raise ValueError("Invalid independent source")
            except (KeyError, TypeError, ValueError):
                raise ValueError(_msg('text.0222')) from None
        if state.get("sliceFrame") is not None and not isinstance(state["sliceFrame"], MprFrame):
            raise ValueError(_msg('text.0222'))
        from qt_dicom_viewer.core.analysis_records import validate_analysis_records
        validate_analysis_records(state.get("analyses", {}))
        image = state.get("image")
        if image is not None and (not isinstance(image, ViewportState) or image.zoom <= 0
                                  or image.slice_index is not None and image.slice_index < 0):
            raise ValueError(_msg('text.0223'))
    edits = tab["edits"]
    if not isinstance(edits.get("views"), dict): raise ValueError(_msg('text.0224'))
    for state in edits["views"].values():
        if not isinstance(state, dict): raise ValueError(_msg('text.0224'))
        presentation = state.get("presentation", {})
        if (not isinstance(presentation, dict) or any(not isinstance(v, dict)
                or not isinstance(v.get("name", ""), str) or len(v.get("name", "")) > 120
                or type(v.get("hidden", False)) is not bool or type(v.get("locked", False)) is not bool
                or type(v.get("ordinal", 1)) is not int for v in presentation.values())):
            raise ValueError(_msg('text.0225'))
        sources = state.get("sources", {})
        if not isinstance(sources, dict) or any(not isinstance(v, dict) for v in sources.values()):
            raise ValueError(_msg('text.0225'))
        for field, classes in (("measurements", (LengthMeasurement, AngleMeasurement, RoiMeasurement)),
                               ("annotations", (TextAnnotation,))):
            items = state.get(field, {})
            if not isinstance(items, dict) or any(not isinstance(item, classes) for item in items.values()):
                raise ValueError(_msg('text.0225'))


def load_referenced_series(document, path, store, *, extra_paths=(), cancelled=lambda: False, progress=lambda text: None):
    paths = set(map(Path, extra_paths))
    for record in document["series"]:
        for source in record["sources"]:
            relative = Path(path).parent / source["relative"] if source["relative"] else None
            candidate = relative if relative is not None and relative.is_file() else Path(source["path"])
            if candidate.is_file():
                paths.add(candidate)
    if not paths:
        return None, [record["uid"] for record in document["series"]]
    files = store.prepare(sorted(paths), cancelled=cancelled, progress=progress)
    latest = None
    progress(_msg('text.0226'))
    for latest in DicomFolderScanner().scan_files(files, folder=Path(path).parent,
                                                cancelled=cancelled, can_publish=lambda: False):
        pass
    available = {s.series_instance_uid: s for s in latest.series} if latest else {}
    missing, selected, all_instances, legacy_groups = [], [], {}, {}
    for record in document["series"]:
        series = available.get(record["uid"])
        if series is None:
            # Earlier classic-MR workspaces used the original Series UID. Match
            # saved source identities before rebuilding that display group.
            legacy = [i for group in available.values() if group.modality.upper() == "MR"
                      for i in group.instances if i.frame_index is None
                      and i.series_instance_uid == record["uid"]]
            if legacy:
                series = _build_series_record(legacy)
                legacy_groups[record["uid"]] = record["instances"]
        current = {i.frame_identity: i for group in (series, *series.phases)
                   for i in group.instances} if series else {}
        resolved = [_resolve_signature(sig, current) for sig in record["instances"]]
        if series is None or any(instance is None for instance in resolved):
            missing.append(record["uid"])
            continue
        for instance in resolved:
            all_instances[instance.frame_identity] = instance
        if record["uid"] in legacy_groups:
            legacy_groups[record["uid"]] = resolved
        selected.append(record["uid"])
    # Exclude newly added files in a referenced folder from the saved workspace.
    groups = {}
    for instance in all_instances.values():
        groups.setdefault((instance.study_instance_uid, instance.series_instance_uid), []).append(instance)
    series = [s for s in _build_series_from_map(groups) if s.series_instance_uid in selected]
    for uid, instances in legacy_groups.items():
        if uid in selected:
            series.append(_build_series_record(instances))
    file_count = len({i.path for i in all_instances.values()})
    return DicomFolderScanSnapshot(Path(path).parent, len(files), file_count, 0, series), missing
