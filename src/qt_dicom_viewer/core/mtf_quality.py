"""Presentation of recorded processing sensitivity; never changes MTF values."""
import math

from qt_dicom_viewer.i18n import message
from qt_dicom_viewer.i18n.messages import localize, builtin


def _msg(key, **values):
    return localize(message(key, **values))


def metric_quality(axis, metric, threshold, direction):
    value = getattr(axis, metric)
    empty = dict(status='ok', message='', relativeChange=None, incomplete=False, missingCrossing=False)
    if value is None or not math.isfinite(value) or value <= 0:
        if metric in axis.unreliable_metrics:
            return dict(empty, status='unavailable', message=str(_msg('mtf.legacyWithheld',
                        direction=direction, metric=metric.upper())))
        return dict(empty, status='not-reached')
    if not axis.sensitivity or threshold is None:
        return empty
    incomplete = any(s.error for s in axis.sensitivity)
    missing = any(not s.error and getattr(s, metric) is None for s in axis.sensitivity)
    changes = [abs(getattr(s, metric)/value-1) for s in axis.sensitivity
               if not s.error and getattr(s, metric) is not None]
    change = max(changes) if changes else None
    args = dict(direction=direction, metric=metric.upper())
    messages = []
    status = 'ok'
    if change is not None and change > threshold:
        status = 'sensitive'
        messages.append(str(_msg('mtf.sensitiveValue', **args, percent=f'{change*100:.1f}')))
    if missing:
        status = status if status != 'ok' else 'missing-crossing'
        messages.append(str(_msg('mtf.comparisonCrossingMissing', **args)))
    if incomplete:
        status = status if status != 'ok' else 'incomplete'
        messages.append(str(_msg('mtf.checkIncomplete', **args)))
    return dict(status=status, message='\n'.join(messages), relativeChange=change,
                incomplete=incomplete, missingCrossing=missing)


def quality_warnings(result):
    warnings = list(result.warnings)
    for direction in ('X', 'Y'):
        for metric in ('mtf50', 'mtf10'):
            quality = metric_quality(getattr(result, direction.lower()), metric,
                                     result.sensitivity_threshold, direction)
            if quality['message']:
                warnings.append(quality['message'])
    return list(dict.fromkeys(warnings))


def sensitivity_details(result, unit):
    if result.sensitivity_threshold is None:
        return ''
    scale = 10 if unit == 'lp/cm' else 1
    lines = [str(_msg('mtf.sensitivityRecorded', percent=f'{result.sensitivity_threshold*100:g}'))]
    def number(value):
        return str(_msg('text.0589')) if value is None else f'{value*scale:.3f}'
    for name, axis in (('X', result.x), ('Y', result.y)):
        if not axis.sensitivity:
            continue
        lines.append(f'{name} · MTF50 / MTF10 · {unit}')
        label = _msg('mtf.baselineWithScale', percent=f'{result.integration_scale*100:.0f}')
        lines.append(f"{label}: {number(axis.mtf50)} / {number(axis.mtf10)}")
        for sample in axis.sensitivity:
            key = 'mtf.variant.' + sample.variant
            label = _msg(key) if key in builtin()['messages'] else sample.variant
            values = str(_msg('mtf.comparisonFailed')) if sample.error else (
                f'{number(sample.mtf50)} / {number(sample.mtf10)}')
            lines.append(f'{label}: {values}')
            if sample.error:
                lines.append(localize(sample.error))
    return '\n'.join(lines)
