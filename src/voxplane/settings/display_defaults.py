"""Validated preferences sampled only when a 2D/MPR slice view is created."""
import re

DEFAULTS = dict(zoom='fit', windowMode='dicom', ctPreset='', mrPreset='')


def validate_options(raw):
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise ValueError('Expected initial display options')
    options = dict(DEFAULTS, **raw)
    if options['zoom'] not in ('fit', 'pixel') or options['windowMode'] not in ('dicom', 'preset'):
        raise ValueError('Invalid initial display mode')
    for key in ('ctPreset', 'mrPreset'):
        value = options[key]
        if not isinstance(value, str) or (value and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', value)):
            raise ValueError('Invalid window template identifier')
    return options
