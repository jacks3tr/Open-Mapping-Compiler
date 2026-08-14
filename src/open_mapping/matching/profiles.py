"""Privacy-safe sample profiling."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import field_serializer

from open_mapping.errors import OpenMappingError
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.schema import JsonType, SchemaDocument
from open_mapping.pointers import resolve_pointer
from open_mapping.serialization.canonical_json import canonical_json

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_INTEGER_STRING = re.compile(r"^[+-]?[0-9]+$")
_DECIMAL_STRING = re.compile(r"^[+-]?[0-9]+\.[0-9]+$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URI = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_UPPER = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")
_LOWER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_PATTERN_ORDER = (
    "empty",
    "uuid",
    "integer-string",
    "decimal-string",
    "iso-date",
    "rfc3339-date-time",
    "email-like",
    "uri-like",
    "uppercase-code",
    "lowercase-word",
    "mixed-text",
)


def _pattern_class(value: str) -> str:
    if value == "":
        return "empty"
    if _UUID.fullmatch(value):
        return "uuid"
    if _INTEGER_STRING.fullmatch(value):
        return "integer-string"
    if _DECIMAL_STRING.fullmatch(value):
        return "decimal-string"
    if _ISO_DATE.fullmatch(value):
        return "iso-date"
    if _RFC3339.fullmatch(value):
        return "rfc3339-date-time"
    if _EMAIL.fullmatch(value):
        return "email-like"
    if _URI.match(value):
        return "uri-like"
    if _UPPER.fullmatch(value):
        return "uppercase-code"
    if _LOWER.fullmatch(value):
        return "lowercase-word"
    return "mixed-text"


class FieldProfile(OpenMappingModel):
    pointer: str
    observed_types: frozenset[JsonType]
    sample_count: int
    missing_count: int
    null_count: int
    distinct_count: int
    minimum_string_length: int | None = None
    maximum_string_length: int | None = None
    pattern_classes: tuple[str, ...] = ()

    @field_serializer("observed_types", when_used="json")
    def serialize_observed_types(self, observed_types: frozenset[JsonType]) -> tuple[str, ...]:
        """Serialize unordered observed types in deterministic value order."""
        return tuple(sorted(item.value for item in observed_types))


def profile_samples(
    schema: SchemaDocument, samples: Sequence[JsonValue]
) -> tuple[FieldProfile, ...]:
    result: list[FieldProfile] = []
    for field in schema.fields:
        if field.pointer == "":
            continue
        observed: set[JsonType] = set()
        missing = 0
        null_count = 0
        distinct: set[str] = set()
        min_len: int | None = None
        max_len: int | None = None
        patterns: set[str] = set()
        for sample in samples:
            try:
                value = resolve_pointer(sample, field.pointer)
            except OpenMappingError:
                missing += 1
                continue
            if value is None:
                null_count += 1
                observed.add(JsonType.NULL)
                continue
            if isinstance(value, bool):
                observed.add(JsonType.BOOLEAN)
                distinct.add(canonical_json(value))
            elif isinstance(value, int):
                observed.add(JsonType.INTEGER)
                distinct.add(canonical_json(value))
            elif isinstance(value, float):
                observed.add(JsonType.NUMBER)
                distinct.add(canonical_json(value))
            elif isinstance(value, str):
                observed.add(JsonType.STRING)
                distinct.add(canonical_json(value))
                patterns.add(_pattern_class(value))
                length = len(value)
                min_len = length if min_len is None else min(min_len, length)
                max_len = length if max_len is None else max(max_len, length)
            elif isinstance(value, list):
                observed.add(JsonType.ARRAY)
            elif isinstance(value, dict):
                observed.add(JsonType.OBJECT)
        result.append(
            FieldProfile(
                pointer=field.pointer,
                observed_types=frozenset(observed),
                sample_count=len(samples),
                missing_count=missing,
                null_count=null_count,
                distinct_count=len(distinct),
                minimum_string_length=min_len,
                maximum_string_length=max_len,
                pattern_classes=tuple(sorted(patterns, key=_PATTERN_ORDER.index)),
            )
        )
    return tuple(result)
