"""Refresh translated display properties without emitting domain-change signals."""
from functools import wraps
from weakref import WeakKeyDictionary
from PySide6.QtCore import Property
from . import messages

_objects = WeakKeyDictionary()


def translated_property(type_, *, notify, notify_name, source_notify=None):
    def decorate(getter):
        @wraps(getter)
        def read(obj):
            wired = _objects.setdefault(obj, {}).setdefault(notify_name, set())
            if source_notify and source_notify not in wired:
                getattr(obj, source_notify.rsplit('.', 1)[-1]).connect(getattr(obj, notify_name).emit)
                wired.add(source_notify)
            return messages.localize(getter(obj))
        return Property(type_, read, notify=notify)
    return decorate


def refresh_properties():
    from shiboken6 import isValid
    for obj in list(_objects):
        if isValid(obj):
            for name in tuple(_objects[obj]): getattr(obj, name).emit()


def translated_model_data(getter):
    @wraps(getter)
    def read(obj, *args, **kwargs):
        _models.add(obj)
        return messages.localize(getter(obj, *args, **kwargs))
    return read


from weakref import WeakSet
_models = WeakSet()


def refresh_models():
    from shiboken6 import isValid
    from PySide6.QtCore import QAbstractListModel, QModelIndex
    for obj in list(_models):
        if not isValid(obj):
            continue
        parents = [QModelIndex()]
        while parents:
            parent = parents.pop()
            count = obj.rowCount(parent)
            if not count:
                continue
            obj.dataChanged.emit(obj.index(0, 0, parent), obj.index(count-1, 0, parent), list(obj.roleNames()))
            if not isinstance(obj, QAbstractListModel):
                parents.extend(obj.index(row, 0, parent) for row in range(count))
