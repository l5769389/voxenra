from math import isfinite
from typing import Any


def _as_str(value: Any) -> str:
    if value is None:
        return ""

    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if isfinite(number) else None


def _as_float_tuple(
    value: Any,
    *,
    expected_length: int,
) -> tuple[float, ...] | None:
    if value is None or isinstance(value, (str, bytes)):
        return None

    try:
        values = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None

    if len(values) != expected_length:
        return None

    if not all(isfinite(item) for item in values):
        return None

    return values


def _transfer_syntax_name(dataset: Any) -> str:
    file_meta = getattr(dataset, "file_meta", None)
    transfer_syntax_uid = getattr(file_meta, "TransferSyntaxUID", None)

    if transfer_syntax_uid is None:
        return ""

    return getattr(transfer_syntax_uid, "name", str(transfer_syntax_uid))


def _display_text(value: str | None) -> str:
    if value is None:
        return "--"
    text = str(value).strip()
    return text or "--"


def _display_number(value: float | int | None, precision: int = 2) -> str:
    if value is None:
        return "--"
    number = float(value)
    if not isfinite(number):
        return "--"
    if number.is_integer():
        return str(int(number))
    text = f"{number:.{precision}f}"
    return text.rstrip("0").rstrip(".") if precision > 0 else text
