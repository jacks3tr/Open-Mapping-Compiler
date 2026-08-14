"""RFC 3339 date helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_TOKENS = ("YYYY", "SSS", "MM", "DD", "hh", "mm", "ss", "Z")
_RFC3339 = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def parse_rfc3339(value: str) -> datetime:
    match = _RFC3339.fullmatch(value)
    if match is None:
        raise ValueError("invalid RFC 3339 date-time")
    year, month, day, hour, minute, second = (
        int(match[name]) for name in ("year", "month", "day", "hour", "minute", "second")
    )
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("invalid RFC 3339 time component")
    fraction = match["fraction"] or ""
    microsecond = int((fraction[:6]).ljust(6, "0"))
    local = datetime(year, month, day, hour, minute, second, microsecond)
    zone = match["zone"]
    if zone == "Z":
        return local.replace(tzinfo=UTC)
    offset_hours = int(zone[1:3])
    offset_minutes = int(zone[4:6])
    if offset_hours > 23 or offset_minutes > 59:
        raise ValueError("invalid RFC 3339 timezone offset")
    offset = timedelta(hours=offset_hours, minutes=offset_minutes)
    try:
        if zone[0] == "+":
            return (local - offset).replace(tzinfo=UTC)
        return (local + offset).replace(tzinfo=UTC)
    except OverflowError as exc:
        raise ValueError("RFC 3339 timezone normalization is out of range") from exc


def canonical_rfc3339(value: datetime) -> str:
    truncated = value.replace(microsecond=(value.microsecond // 1000) * 1000)
    return truncated.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def format_date_pattern(value: str, pattern: str) -> str:
    parsed = parse_rfc3339(value)
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        for token in _TOKENS:
            if pattern.startswith(token, index):
                values = {
                    "YYYY": f"{parsed.year:04d}",
                    "MM": f"{parsed.month:02d}",
                    "DD": f"{parsed.day:02d}",
                    "hh": f"{parsed.hour:02d}",
                    "mm": f"{parsed.minute:02d}",
                    "ss": f"{parsed.second:02d}",
                    "SSS": f"{parsed.microsecond // 1000:03d}",
                    "Z": "Z",
                }
                parts.append(values[token])
                index += len(token)
                break
        else:
            character = pattern[index]
            if character != "T" and character.isascii() and character.isalpha():
                raise ValueError(f"unsupported date format token at index {index}")
            parts.append(character)
            index += 1
    return "".join(parts)
