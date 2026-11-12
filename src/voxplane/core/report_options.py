"""Patient-free report styling shared by preferences and frozen exports."""
DEFAULTS = dict(orientation='portrait', fontSize='standard', pageNumbers=True,
                organization='', department='', softwareName='', tableDetail='summary',
                imageColumns=1, anonymous=True, includeImages=True)


def validate_options(raw):
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise ValueError('Unknown report options')
    result = dict(DEFAULTS, **raw)
    enums = dict(orientation=('portrait', 'landscape'), fontSize=('standard', 'large'),
                 tableDetail=('summary', 'detailed'), imageColumns=(1, 2))
    for key, value in result.items():
        if type(value) is not type(DEFAULTS[key]):
            raise ValueError('Invalid report option: '+key)
        if key in enums and value not in enums[key]:
            raise ValueError('Invalid report option: '+key)
        if isinstance(value, str) and key not in enums:
            if len(value) > (80 if key == 'softwareName' else 120) or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError('Invalid report label: '+key)
            result[key] = value.strip()
    return result


def validate_content(raw=None):
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {'title', 'operator', 'reviewer', 'notes', 'conclusion'}:
        raise ValueError('Unknown report content')
    if any(not isinstance(v, str) or len(v) > (4000 if k in ('notes', 'conclusion') else 120) for k, v in raw.items()):
        raise ValueError('Invalid report content')
    return dict(raw)


def fitting_prefix(text, metrics, width):
    """Longest prefix fitting a line, using logarithmic shaping calls."""
    lo, hi = 1, len(text)
    while lo < hi:
        middle = (lo+hi+1)//2
        if metrics.horizontalAdvance(text[:middle]) <= width:
            lo = middle
        else:
            hi = middle-1
    return lo
