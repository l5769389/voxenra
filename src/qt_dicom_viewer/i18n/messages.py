"""Value-only messages can cross worker boundaries without fixing the UI language."""
from functools import lru_cache
from importlib.resources import files
import json
from string import Formatter


@lru_cache(maxsize=1)
def bundled_locales():
    directory = files('qt_dicom_viewer').joinpath('qml/assets/languages')
    locales = {entry.name[:-5] for entry in directory.iterdir() if entry.name.endswith('.json')}
    # Keep the original language and English first; additional JSON packs are data.
    return tuple(locale for locale in ('zh-CN', 'en-US') if locale in locales) + tuple(
        sorted(locales - {'zh-CN', 'en-US'}))


@lru_cache(maxsize=16)
def builtin(locale='zh-CN'):
    return json.loads(files('qt_dicom_viewer').joinpath('qml/assets/languages', locale + '.json').read_text(encoding='utf-8'))


def parameters(text):
    result = set()
    for _, field, spec, conversion in Formatter().parse(text):
        if field is not None:
            if not field.isidentifier() and not field.isdecimal() and field != '':
                raise ValueError('Invalid message parameter')
            if '{' in spec or conversion:
                raise ValueError('Invalid message format')
            result.add((field, spec))
    return result


class Message(str):
    """Canonical Chinese value for existing domain logic, plus a durable message ID.

    Qt display properties explicitly localize this value. JSON/domain comparisons
    therefore never change when users switch languages or edit a translation.
    """
    def __new__(cls, key, *args, **values):
        source = builtin()['messages'][key]
        try:
            canonical = source.format(*args, **values) if args or values else source
        except (KeyError, IndexError, ValueError):
            canonical = source
        obj = super().__new__(cls, canonical)
        obj.key, obj.args, obj.values = key, args, values
        return obj

    def format(self, *args, **kwargs):
        return Message(self.key, *args, **kwargs)

    def __add__(self, other): return JoinedMessage((self, other))
    def __radd__(self, other): return JoinedMessage((other, self))
    def join(self, items):
        parts = []
        for index, item in enumerate(items):
            if index: parts.append(self)
            parts.append(item)
        return JoinedMessage(parts)

    def __reduce__(self):
        return (_restore, (self.key, self.args, self.values))


def _restore(key, args, values): return Message(key, *args, **values)


class JoinedMessage(str):
    def __new__(cls, parts):
        obj = super().__new__(cls, ''.join(str(p) for p in parts))
        obj.parts = tuple(parts)
        return obj
    def __add__(self, other): return JoinedMessage((self, other))
    def __radd__(self, other): return JoinedMessage((other, self))
    def __reduce__(self): return (JoinedMessage, (self.parts,))


message = Message
_active = None


def snapshot():
    return dict(_active.messages if _active is not None else builtin()['messages'])


def localize(value, translations=None):
    if translations is None:
        translations = _active.messages if _active is not None else builtin()['messages']
    if isinstance(value, BaseException): value = error_message(value)
    if isinstance(value, Message):
        template = translations.get(value.key, builtin('en-US')['messages'].get(value.key, str(value)))
        if value.args or value.values:
            try:
                return template.format(*(localize(v, translations) for v in value.args),
                                       **{k: localize(v, translations) for k,v in value.values.items()})
            except (KeyError, IndexError, ValueError):
                return str(value)
        return template
    if isinstance(value, JoinedMessage):
        return ''.join(str(localize(v, translations)) for v in value.parts)
    if isinstance(value, dict): return {k: localize(v, translations) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [localize(v, translations) for v in value]
    return value


def error_message(error):
    if not isinstance(error, BaseException): return error
    if isinstance(error, MemoryError):
        return Message('errors.outOfMemory')
    value = error.args[0] if len(error.args) == 1 and isinstance(error.args[0], (Message, JoinedMessage)) else str(error)
    return value or Message('errors.operationFailed')
