"""Display rounding only; source measurements and statistics stay unrounded."""
import math
from numbers import Real

DEFAULT_DECIMAL_PLACES = 2


def format_measurement(value, decimal_places=DEFAULT_DECIMAL_PLACES, *, missing="—"):
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(value):
        return missing
    text = f"{value:.{decimal_places}f}"
    # A small negative measurement should display zero, not a misleading -0.00.
    return text[1:] if text.startswith("-") and float(text) == 0 else text
