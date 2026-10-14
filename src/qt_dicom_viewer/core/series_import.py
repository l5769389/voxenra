"""Merge immutable import snapshots before publishing them on the GUI thread."""
from dataclasses import replace

from qt_dicom_viewer.core.dicom_scanner import _build_series_from_map


def _phase_sources(phase):
    return frozenset((i.study_instance_uid, i.series_instance_uid, *i.frame_identity)
                     for i in phase.instances)


def preserve_phase_identifiers(series, previous_phases):
    """Keep source identity stable while retaining the scanner's temporal order.

    IDs are opaque references used by open tabs, measurements and volume caches;
    their numeric order must not be used as the playback order. Existing source
    frames establish continuity even when another batch extends a phase stack.
    """
    if not series.phases or not previous_phases:
        return series
    previous = [(p.phase_identifier, _phase_sources(p)) for p in previous_phases]
    reserved = {identifier for identifier, _ in previous}
    assigned, phases = set(), []
    for phase in series.phases:
        sources = _phase_sources(phase)
        matches = {identifier for identifier, old_sources in previous if sources & old_sources}
        if len(matches) > 1:
            raise ValueError("Conflicting temporal source identities")
        if matches:
            identifier = matches.pop()
            if identifier in assigned:
                raise ValueError("Duplicate temporal source identity")
        else:
            identifier = phase.phase_identifier
            if identifier in reserved or identifier in assigned:
                identifier = max(reserved | assigned | {0}) + 1
        assigned.add(identifier)
        phases.append(replace(phase, phase_identifier=identifier))
    return replace(series, phases=tuple(phases))


def _preserve_series_phase_identifiers(rebuilt, previous_series):
    # Each previously published series keeps its own established mapping. New
    # peers inherit a matching existing group so adding an earlier timestamp
    # cannot silently redirect an open tab or historical ROI to another source.
    prior_groups = {}
    for series in previous_series.values():
        if series.phases:
            signature = tuple((p.phase_identifier, _phase_sources(p)) for p in series.phases)
            prior_groups[signature] = series.phases
    stable = []
    for series in rebuilt:
        prior = previous_series.get(series.series_instance_uid)
        phases = prior.phases if prior is not None else ()
        if not phases and series.phases and prior_groups:
            sources = frozenset().union(*(_phase_sources(p) for p in series.phases))
            matching = [(len(sources & frozenset().union(*(s for _, s in signature))), group)
                        for signature, group in prior_groups.items()]
            overlap, phases = max(matching, key=lambda item: item[0])
            if not overlap:
                phases = ()
        stable.append(preserve_phase_identifiers(series, phases))
    return stable


def merge_import_snapshot(result, base_series, *, phase_reference_series=None):
    incoming_uids = {s.series_instance_uid for s in result.series}
    incoming_studies = {s.study_instance_uid for s in result.series}
    # Progressive local previews can already have exposed new IDs to open tabs.
    # Their identity history is separate from the pre-import duplicate baseline.
    reference = base_series if phase_reference_series is None else phase_reference_series
    reference = {uid: series for uid, series in reference.items()
                 if series.study_instance_uid in incoming_studies}
    affected = [series for series in base_series.values()
                if series.study_instance_uid in incoming_studies]
    if not affected:
        return replace(result, series=_preserve_series_phase_identifiers(result.series, reference),
                       incoming_series_uids=frozenset(incoming_uids))
    grouped = {}
    # Reconsider the affected studies so newly imported phase peers can link
    # across batches, using the scanner's same geometry/temporal checks.
    # A restored catalog may contain only one member of a temporal group;
    # include its linked sources too so all members share refreshed paths.
    for series in affected:
        for group in (series, *series.phases):
            for instance in group.instances:
                key = (instance.study_instance_uid, instance.series_instance_uid)
                grouped.setdefault(key, {})[instance.frame_identity] = instance
    existing_files, new_files = set(), set()
    for series in result.series:
        for instance in series.instances:
            key = (instance.study_instance_uid, instance.series_instance_uid)
            combined = grouped.setdefault(key, {})
            files = existing_files if instance.frame_identity in combined else new_files
            files.add(instance.file_identity)
            combined[instance.frame_identity] = instance
    # An enhanced file is already present only when all incoming frames were
    # loaded before this batch, even if the file spans several display groups.
    rebuilt = _build_series_from_map(
        {key: list(instances.values()) for key, instances in grouped.items()})
    stable = _preserve_series_phase_identifiers(rebuilt, reference)
    return replace(result, series=[series for series in stable
        if series.series_instance_uid in incoming_uids
        or series != base_series.get(series.series_instance_uid)],
        existing_file_count=len(existing_files - new_files),
        incoming_series_uids=frozenset(incoming_uids))
