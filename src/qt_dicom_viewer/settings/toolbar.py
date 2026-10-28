"""Stable toolbar preferences, independent of translations and current capability."""
import re

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.model.toolbar_priorities import toolbar_groups

LEFT_VIEWS = ('2d', 'mpr', '3d', 'montage', '4d', 'tag', 'fusion')
MODES = ('2d', 'mpr', '3d', 'montage', '4d', 'compare2d', 'comparempr', 'petctfusion')
CAPABILITIES = ('ct', 'mr', 'pt', 'other', 'color', 'petct3d')


def profile_key(tab_type, modality, is_color=False):
    capability = 'color' if is_color else modality.lower() if modality.lower() in CAPABILITIES else 'other'
    return f'{tab_type or TabType.TWO_D}:{capability}'


def validate_toolbar(key, value):
    def identifiers(values, limit):
        if (not isinstance(values, list) or len(values) > limit
                or any(not isinstance(v, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', v) for v in values)
                or len(set(values)) != len(values)):
            raise ValueError(_msg('toolbar.invalid'))
        return list(values)

    if key == 'leftViews':
        result = identifiers(value, len(LEFT_VIEWS))
        if any(v not in LEFT_VIEWS for v in result):
            raise ValueError(_msg('toolbar.invalid'))
        return result
    if not isinstance(value, dict) or len(value) > 128:
        raise ValueError(_msg('toolbar.invalid'))
    result = {}
    for profile, groups in value.items():
        if (not isinstance(profile, str) or not re.fullmatch(r'[a-z0-9-]{1,40}:[a-z0-9-]{1,40}', profile)
                or not isinstance(groups, dict) or set(groups) != {'common', 'more'}):
            raise ValueError(_msg('toolbar.invalid'))
        common, more = identifiers(groups['common'], 7), identifiers(groups['more'], 128)
        if set(common) & set(more):
            raise ValueError(_msg('toolbar.invalid'))
        result[profile] = dict(common=common, more=more)
    return result


def navigation_order(saved):
    return list(saved) + [key for key in LEFT_VIEWS if key not in saved]


def resolved_groups(tab_type, modality, is_color, tools, profiles):
    """Filter only the rendered result; saved unavailable IDs remain untouched."""
    saved = profiles.get(profile_key(tab_type, modality, is_color))
    tool_ids = [t['toolType'] for t in tools]
    available = {t['toolType'] for t in tools if t.get('available', True)}
    if saved is None:
        default = toolbar_groups(tab_type, modality, is_color, tools)
        common = default['common'] + default['primary']
        more = [key for key in tool_ids if key not in common and key not in ('import', 'export', 'reset')]
        more += [key for key in tool_ids if key in ('import', 'export', 'reset')]
        return dict(**default, more=more, customized=False)
    common = [key for key in saved['common'] if key in available]
    more = [key for key in saved['more'] if key in tool_ids]
    more += [key for key in tool_ids if key not in common and key not in more]
    return dict(common=common[:4], primary=common[4:7], more=more, customized=True)
