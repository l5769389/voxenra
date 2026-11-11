from __future__ import annotations

import logging
import sys
import threading
from types import TracebackType

logger = logging.getLogger("uncaught")


def install_exception_hooks() -> None:
    original_hook = sys.excepthook

    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(
            exception_type,
            KeyboardInterrupt,
        ):
            original_hook(
                exception_type,
                exception,
                traceback,
            )
            return

        logger.critical(
            "Unhandled exception",
            exc_info=(
                exception_type,
                exception,
                traceback,
            ),
        )

    def handle_thread_exception(
        args: threading.ExceptHookArgs,
    ) -> None:
        logger.critical(
            "Unhandled thread exception: thread=%s",
            args.thread.name if args.thread else "unknown",
            exc_info=(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            ),
        )

    sys.excepthook = handle_exception
    threading.excepthook = (
        handle_thread_exception
    )