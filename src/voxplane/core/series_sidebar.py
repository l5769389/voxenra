"""Patient / study / series rows for the virtualized sidebar."""
from voxplane.i18n import message as _msg

from hashlib import sha1

from voxplane.model import DicomSeriesRecord


def patient_key(series: DicomSeriesRecord) -> str:
    # Names are not unique identifiers. With no patient ID, keep studies separate.
    identity = (series.patient_id, series.patient_id_issuer) if series.patient_id else (
        "study", series.study_instance_uid or series.series_instance_uid)
    return "patient-" + sha1(repr(identity).encode()).hexdigest()


def study_label(series: DicomSeriesRecord) -> str:
    date, time = series.study_date, series.study_time.split(".")[0]
    label = f"{date[:4]}/{date[4:6]}/{date[6:8]}" if len(date) == 8 and date.isdigit() else _msg('text.0257')
    if len(time) >= 4 and time.isdigit():
        label += f" {time[:2]}:{time[2:4]}" + (f":{time[4:6]}" if len(time) >= 6 else "")
    return label



def series_sort_key(series: DicomSeriesRecord):
    """Keep MR subgroups in acquisition order, independent of their hashed UID."""
    number = series.series_number if series.series_number is not None else 1_000_000
    if series.modality.upper() != "MR" or not series.instances:
        return number, series.series_instance_uid, ()
    instance = series.instances[0]
    params = instance.mr_parameters
    if params is None:
        return number, instance.series_instance_uid, ((), series.series_instance_uid)
    def numeric(value):
        return (value is None, value if value is not None else 0)
    dimensions = (numeric(params.temporal_position), numeric(params.echo_number),
                  numeric(params.echo_time), numeric(params.b_value),
                  params.component, params.diffusion_direction, params.stack_id,
                  instance.mr_dimension_indices)
    return number, instance.series_instance_uid, (dimensions, series.series_instance_uid)


def build_sidebar_rows(records, query: str, collapsed: set[str], thumbnails: dict[str, str]):
    patients = {}
    for series in records:
        key = patient_key(series)
        patient = patients.setdefault(key, {"series": series, "studies": {}})
        study_uid = series.study_instance_uid or series.series_instance_uid
        patient["studies"].setdefault(study_uid, []).append(series)
    query = query.strip().casefold()
    rows = []

    def row(kind, key, label, **kwargs):
        return dict(kind=kind, key=key, label=label, subtitle="", seriesInstanceUid="",
                    modality="", thumbnailUrl="", dicomFileCount=0, countLabel="",
                    supports4D=False, expanded=True, **kwargs)

    for key, patient in sorted(patients.items(), key=lambda entry: (
        entry[1]["series"].patient_name.casefold(), entry[1]["series"].patient_id, entry[0])):
        first = patient["series"]
        if query and not any(query in f"{s.patient_name} {s.patient_id}".casefold()
                             for study in patient["studies"].values() for s in study):
            continue
        expanded = bool(query) or key not in collapsed
        item = row("patient", key, first.patient_name or _msg('text.0258'))
        item.update(subtitle=first.patient_id, expanded=expanded)
        rows.append(item)
        if not expanded:
            continue
        for study_uid, series_list in sorted(patient["studies"].items(), key=lambda entry: (
            entry[1][0].study_date, entry[1][0].study_time, entry[0]), reverse=True):
            first_series = series_list[0]
            study_key = key + "/study-" + study_uid
            expanded = bool(query) or study_key not in collapsed
            item = row("study", study_key, study_label(first_series))
            item.update(subtitle=first_series.study_description, expanded=expanded)
            rows.append(item)
            if not expanded:
                continue
            for series in sorted(series_list, key=series_sort_key):
                item = row("series", series.series_instance_uid, series.series_description or _msg('text.0259'))
                item.update(
                    seriesInstanceUid=series.series_instance_uid,
                    seriesNumber=series.series_number if series.series_number is not None else -1,
                    modality=series.modality,
                    subtitle=" · ".join(filter(None, [series.modality,
                        f"Series {series.series_number}" if series.series_number is not None else ""])),
                    thumbnailUrl=thumbnails.get(series.series_instance_uid, ""),
                    dicomFileCount=series.dicom_file_count,
                    countLabel=_msg("series.frameFileCount", frames=sum(1 if i.frame_index is not None else max(1, i.number_of_frames) for i in series.instances), files=len({i.path for i in series.instances})),
                    supports4D=series.supports_four_d,
                )
                rows.append(item)
    return rows
