"""Cooperative cancellation scoped to one worker request (never shared globally)."""
from contextlib import contextmanager
from contextvars import ContextVar

from voxplane.i18n import message as _msg

_cancel_event = ContextVar("render_cancel_event", default=None)


@contextmanager
def render_cancellation(event):
    token = _cancel_event.set(event)
    try:
        yield
    finally:
        _cancel_event.reset(token)


def check_render_cancelled():
    event = _cancel_event.get()
    if event is not None and event.is_set():
        raise InterruptedError(_msg('text.0150'))
