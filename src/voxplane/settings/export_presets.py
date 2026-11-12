"""Bounded, validated named preferences. No image or per-report content is stored."""
from copy import deepcopy
import re

KINDS = ('screenshot', 'report')
MAX_PRESETS = 20


def validate_options(kind, value):
    if hasattr(value, 'toVariant'):
        value = value.toVariant()
    if not isinstance(value, dict):
        raise ValueError('preset.invalidOptions')
    if kind == 'screenshot':
        from .screenshot_presets import validate_options as validate
    elif kind == 'report':
        from voxplane.core.report_options import validate_options as validate
    else:
        raise ValueError('preset.invalidKind')
    return validate(deepcopy(value))


def validate_name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40 or any(ord(c) < 32 or ord(c)==127 for c in value):
        raise ValueError('preset.invalidName')
    return value.strip()


def validate_entries(kind, entries):
    if kind not in KINDS or not isinstance(entries, list) or len(entries) > MAX_PRESETS:
        raise ValueError('preset.invalidList')
    result, ids, names = [], set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'id', 'name', 'options'}:
            raise ValueError('preset.invalidList')
        identifier = entry['id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identifier) or identifier in ids:
            raise ValueError('preset.invalidList')
        name = validate_name(entry['name'])
        if name.casefold() in names:
            raise ValueError('preset.duplicateName')
        result.append(dict(id=identifier,name=name,options=validate_options(kind,entry['options'])))
        ids.add(identifier); names.add(name.casefold())
    return result
