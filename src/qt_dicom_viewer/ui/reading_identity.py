"""Source-derived reading labels; these values never identify tabs or studies."""
from datetime import date
from hashlib import sha256
import re

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import JoinedMessage


def format_study_date(value: str) -> str:
    """Format a valid DICOM DA without guessing missing or invalid dates."""
    value = str(value or '').strip()
    if len(value) == 8 and value.isdigit():
        try:
            date(int(value[:4]), int(value[4:6]), int(value[6:]))
        except ValueError:
            pass
        else:
            return f'{value[:4]}/{value[4:6]}/{value[6:]}'
    return ''


def format_study_time(value: str) -> str:
    """Preserve DICOM TM precision, including fractional seconds, for details."""
    value = str(value or '').strip()
    match = re.fullmatch(r"([0-9]{2})(?:([0-9]{2})(?:([0-9]{2}(?:\.[0-9]{1,6})?))?)?", value)
    if match and int(match[1]) < 24 and (match[2] is None or int(match[2]) < 60) and (match[3] is None or float(match[3]) < 61):
        return ':'.join(part for part in match.groups() if part is not None)
    return value


def _join(values, separator=' · '):
    parts = []
    for value in values:
        if parts:
            parts.append(separator)
        parts.append(value)
    return JoinedMessage(parts)


def _visible_identity(meta):
    return (meta.patient_name, format_study_date(meta.study_date),
            meta.series_number, meta.series_description)


def _source_code(uid):
    # A presentation discriminator, never a replacement for a DICOM/workspace key.
    return sha256(uid.encode('utf-8')).hexdigest()[:8]


def tab_presentation(tab, *, sources=(), hide_identity=False):
    config = tab.tab_config
    metas = tuple(meta for meta in config.series_metas if meta is not None)
    row = dict(tabId=config.tab_id, tabType=config.tab_type)
    if not metas:
        return dict(row, tabLabel=config.tab_label, tabPrimary=config.tab_label,
                    tabSecondary='', tabTooltip=config.tab_label, tabPatient='', tabDescription=config.tab_label)
    if hide_identity:
        hidden = _msg('reading.hiddenIdentity')
        return dict(row, tabLabel=hidden, tabPrimary=hidden, tabSecondary='', tabTooltip=hidden, tabPatient='', tabDescription=hidden)
    primary, secondary, details, patients = [], [], [], []
    for meta in metas:
        patient = meta.patient_name or _msg('text.0258')
        description = meta.series_description or _msg('text.0259')
        study_date = format_study_date(meta.study_date) or _msg('reading.invalidDate' if meta.study_date.strip() else 'reading.missingDate')
        number = (_msg('reading.seriesNumber', number=meta.series_number)
                  if meta.series_number is not None else _msg('reading.missingNumber'))
        duplicates = {getattr(other, 'series_uid', getattr(other, 'series_instance_uid', ''))
                      for other in sources if _visible_identity(other) == _visible_identity(meta)}
        if len(duplicates) > 1:
            description = _join(('[' + _source_code(meta.series_uid) + ']', description))
        if meta.patient_name.strip():
            patients.append(meta.patient_name)
        primary.append(description)
        context = []
        if format_study_date(meta.study_date):
            context.append(format_study_date(meta.study_date))
        if meta.series_number is not None:
            context.append(number)
        if context:
            secondary.append(_join(context))
        details.append(_msg('reading.sourceDetails', patient=patient, patientId=meta.patient_id or '—', time=format_study_time(meta.study_time) or '—',
                            date=format_study_date(meta.study_date) or meta.study_date or study_date, study=meta.study_description or _msg('text.0259'),
                            number=meta.series_number if meta.series_number is not None else _msg('reading.missingNumber'),
                            description=meta.series_description or _msg('text.0259'), source=_source_code(meta.series_uid)))
    label_parts = [_join(values, ' ↔ ') for values in (primary, patients, secondary) if values]
    return dict(row, tabLabel=_join(label_parts),
                tabPrimary=_join(primary, ' ↔ '), tabSecondary=_join(secondary, ' ↔ '),
                tabTooltip=_join(details, '\n\n'), tabPatient=_join(patients, ' ↔ '),
                tabDescription=_join(primary, ' ↔ '))


def tab_hides_identity(tab, *, default=False):
    states = [getattr(view, '_state', None) for view in tab.viewports_by_id.values()]
    displays = [state.display_settings for state in states if hasattr(state, 'display_settings')]
    return any(display.hide_sensitive_info for display in displays) if displays else default
