"""Normalize model confidence values before diagnosis and review decisions."""

import math


def normalize_confidence(value, fallback: float = 0.0) -> float:
    """Return a finite probability in [0, 1]; invalid model output stays low-confidence."""
    if isinstance(value, bool):
        return fallback
    try:
        confidence = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return fallback
    return confidence
