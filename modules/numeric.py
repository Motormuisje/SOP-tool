"""Shared numeric parsing."""

import math
from typing import Optional


def finite_float(value) -> Optional[float]:
    """``float(value)`` when that is a finite number, else None.

    Catches OverflowError too: a JSON integer with hundreds of digits parses
    as a Python int and ``float()`` then raises OverflowError, not
    ValueError. What None means is up to the caller: a request handler
    rejects it, a report shows it as unknown.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None
