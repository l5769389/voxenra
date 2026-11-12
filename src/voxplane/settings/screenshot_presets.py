"""Validated, identity-free screenshot preferences."""
DEFAULTS = dict(scope='viewport', format='png', size='current', longEdge=2048,
                jpegQuality=90, measurements=True, directions=True, scale=True,
                parameters=True, anonymous=True, filenamePrefix='screenshot', revealAfter=False)


def validate_options(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError('Invalid screenshot options')
    values = {**DEFAULTS, **raw}
    for key, allowed in [('scope', ('viewport','tab')), ('format',('png','jpeg')), ('size',('current','longEdge'))]:
        if values[key] not in allowed: raise ValueError(key)
    for key, lower, upper in [('longEdge',512,8192), ('jpegQuality',1,100)]:
        # QML Number(text) crosses QVariantMap as a double even for whole values.
        if type(values[key]) is float and values[key].is_integer():
            values[key] = int(values[key])
        if type(values[key]) is not int or not lower <= values[key] <= upper: raise ValueError(key)
    for key in ('measurements','directions','scale','parameters','anonymous','revealAfter'):
        if type(values[key]) is not bool: raise ValueError(key)
    prefix = values['filenamePrefix']
    if not isinstance(prefix,str) or not prefix.strip() or len(prefix)>80 or any(c in prefix for c in '/\\:*?"<>|') or any(ord(c)<32 for c in prefix):
        raise ValueError('filenamePrefix')
    values['filenamePrefix'] = prefix.strip()
    return values
