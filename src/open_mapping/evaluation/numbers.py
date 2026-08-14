"""Numeric helpers shared by interpreter and code generation."""

import math
import re

MAX_SAFE_INTEGER = 9_007_199_254_740_991
STRICT_DECIMAL_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
STRICT_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


def parse_decimal_string(value: str) -> float:
    if STRICT_DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid decimal string")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite decimal string")
    return parsed


def parse_integer_string(value: str) -> int:
    if STRICT_INTEGER_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid integer string")
    return int(value, 10)


def normalize_number(value: float) -> int | float:
    if not math.isfinite(value):
        raise ValueError("non-finite numeric result")
    if value.is_integer() and abs(value) <= MAX_SAFE_INTEGER:
        return int(value)
    if abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("numeric result exceeds JavaScript safe integer range")
    return value


def round_half_away_from_zero(value: float, digits: int) -> int | float:
    if not math.isfinite(value):
        raise ValueError("non-finite numeric input")
    factor = 10**digits
    scaled = math.floor(abs(value) * factor + 0.5) / factor
    result = math.copysign(scaled, value) if value != 0 else 0.0
    return normalize_number(result)
