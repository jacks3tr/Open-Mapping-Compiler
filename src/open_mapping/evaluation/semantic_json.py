"""Semantic equality for runtime JSON values.

This deliberately does not use artifact serialization.  JSON numbers compare by
their mathematical binary64 value, so serializer spelling (``1`` versus ``1.0``)
does not change expression, invariant, golden, or cross-runtime semantics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from open_mapping.evaluation.numbers import MAX_SAFE_INTEGER


def _binary64_number(value: int | float) -> float:
    if isinstance(value, int) and abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("JSON integer exceeds JavaScript safe integer range")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("JSON number exceeds binary64 range") from exc
    if not math.isfinite(result):
        raise ValueError("JSON number must be finite")
    if result.is_integer() and abs(result) > MAX_SAFE_INTEGER:
        raise ValueError("JSON integer exceeds JavaScript safe integer range")
    return result


def semantic_json_equal(left: object, right: object) -> bool:
    """Return whether two finite JSON values are semantically equal."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return False
        return _binary64_number(left) == _binary64_number(right)
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        return set(left) == set(right) and all(
            semantic_json_equal(left[key], right[key]) for key in left
        )
    if (
        isinstance(left, Sequence)
        and not isinstance(left, str)
        or isinstance(right, Sequence)
        and not isinstance(right, str)
    ):
        if (
            not isinstance(left, Sequence)
            or isinstance(left, str)
            or not isinstance(right, Sequence)
            or isinstance(right, str)
        ):
            return False
        return len(left) == len(right) and all(
            semantic_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right
