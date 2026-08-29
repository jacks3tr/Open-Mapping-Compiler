"""Deterministic, conservative source-schema inference from JSON records."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonValue
from open_mapping.model.schema import SchemaDocument
from open_mapping.pointers import escape_pointer_token
from open_mapping.serialization.canonical_json import canonical_json_bytes

_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_VERSION = "inferred-v0.1"
_MAX_RECORDS = 10_000
_MAX_NODES = 100_000
_MAX_DEPTH = 64
_TYPE_ORDER = ("null", "boolean", "integer", "number", "string", "array", "object")


@dataclass(frozen=True)
class SourceInference:
    """An inferred schema plus the records and diagnostics that produced it."""

    schema: SchemaDocument
    records: tuple[dict[str, object], ...]
    issues: tuple[Issue, ...]


@dataclass
class _Budget:
    nodes: int = 0

    def visit(self, *, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise _error(
                "source data exceeds the maximum nesting depth",
                f"Use JSON records nested no more than {_MAX_DEPTH} levels.",
            )
        self.nodes += 1
        if self.nodes > _MAX_NODES:
            raise _error(
                "source data exceeds the inference size limit",
                f"Use at most {_MAX_NODES} JSON values for one inference operation.",
            )


def _error(message: str, correction: str) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.INVALID_INPUT,
                severity=Severity.ERROR,
                component="source_inference",
                message=message,
                correction=correction,
            ),
        )
    )


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(
                "source data contains a non-finite number",
                "Use finite JSON numbers; NaN and infinity are not valid JSON.",
            )
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise _error(
                "source data contains a non-string object key",
                "Use strings for every JSON object key.",
            )
        return "object"
    raise _error(
        f"source data contains unsupported value type {type(value).__name__!r}",
        "Use JSON null, booleans, numbers, strings, arrays, and objects only.",
    )


def _type_value(types: set[str]) -> str | list[str]:
    if "number" in types:
        types.discard("integer")
    ordered = [item for item in _TYPE_ORDER if item in types]
    return ordered[0] if len(ordered) == 1 else ordered


def _infer_values(
    values: Sequence[object],
    *,
    pointer: str,
    depth: int,
    budget: _Budget,
    unconstrained_arrays: set[str],
) -> dict[str, object]:
    types: set[str] = set()
    objects: list[dict[str, object]] = []
    arrays: list[list[object]] = []
    for value in values:
        budget.visit(depth=depth)
        value_type = _json_type(value)
        types.add(value_type)
        if value_type == "object":
            objects.append(cast(dict[str, object], value))
        elif value_type == "array":
            arrays.append(cast(list[object], value))

    schema: dict[str, object] = {"type": _type_value(types)}
    if objects:
        keys = sorted({key for value in objects for key in value})
        properties: dict[str, object] = {}
        for key in keys:
            child_pointer = pointer + "/" + escape_pointer_token(key)
            properties[key] = _infer_values(
                [value[key] for value in objects if key in value],
                pointer=child_pointer,
                depth=depth + 1,
                budget=budget,
                unconstrained_arrays=unconstrained_arrays,
            )
        if properties:
            schema["properties"] = properties
        required = sorted(set.intersection(*(set(value) for value in objects)))
        if required:
            schema["required"] = required

    if arrays:
        items = [item for value in arrays for item in value]
        if items:
            schema["items"] = _infer_values(
                items,
                pointer=pointer + "/items",
                depth=depth + 1,
                budget=budget,
                unconstrained_arrays=unconstrained_arrays,
            )
        else:
            unconstrained_arrays.add(pointer)
    return schema


def _records(data: JsonValue) -> tuple[dict[str, object], ...]:
    if isinstance(data, dict):
        return (data,)
    if not isinstance(data, list):
        raise _error(
            "source data must be a JSON object or a non-empty array of objects",
            "Pass one record object or an array containing record objects.",
        )
    if not data:
        raise _error(
            "source data record array is empty",
            "Pass at least one source record so a schema can be inferred.",
        )
    if len(data) > _MAX_RECORDS:
        raise _error(
            "source data contains too many records",
            f"Use at most {_MAX_RECORDS} records for one inference operation.",
        )
    if any(not isinstance(item, dict) for item in data):
        raise _error(
            "source data arrays must contain only record objects",
            "Pass an array of JSON objects; map each inferred record independently.",
        )
    return tuple(cast(dict[str, object], item) for item in data)


def infer_source_data(data: JsonValue, *, source_uri: str = "memory") -> SourceInference:
    """Infer one Draft 2020-12 record schema and preserve its source records."""

    records = _records(data)
    unconstrained_arrays: set[str] = set()
    inferred = _infer_values(
        records,
        pointer="",
        depth=0,
        budget=_Budget(),
        unconstrained_arrays=unconstrained_arrays,
    )
    schema_without_id: dict[str, object] = {
        "$schema": _DIALECT,
        "x-schema-version": _SCHEMA_VERSION,
        **inferred,
    }
    digest = hashlib.sha256(canonical_json_bytes(cast(JsonValue, schema_without_id))).hexdigest()
    schema_id = f"urn:open-mapping:inferred-source:{digest}"
    document: dict[str, object] = {"$id": schema_id, **schema_without_id}
    schema = parse_json_schema(
        cast(JsonValue, document),
        schema_id=schema_id,
        source_uri=source_uri,
    )
    issues: list[Issue] = [
        Issue(
            code=IssueCode.SOURCE_SCHEMA_INFERRED,
            severity=Severity.INFO,
            component="source_inference",
            message=(
                f"inferred source schema from {len(records)} JSON "
                f"record{'s' if len(records) != 1 else ''}"
            ),
            correction=(
                "Review the inferred schema in a built bundle or provide an explicit source "
                "schema when stricter guarantees are required."
            ),
            schema_id=schema_id,
        )
    ]
    for pointer in sorted(unconstrained_arrays):
        issues.append(
            Issue(
                code=IssueCode.SOURCE_SCHEMA_INFERRED,
                severity=Severity.WARNING,
                component="source_inference",
                message=f"array {pointer or '<root>'!r} has no observed item shape",
                correction="Provide at least one array item or an explicit source schema.",
                schema_id=schema_id,
                source_path=pointer or "",
            )
        )
    return SourceInference(schema=schema, records=records, issues=sort_issues(issues))


def infer_source_schema(data: JsonValue, *, source_uri: str = "memory") -> SchemaDocument:
    """Return the deterministic schema inferred from one object or object record set."""

    return infer_source_data(data, source_uri=source_uri).schema


def load_source_data(path: Path) -> JsonValue:
    """Load strict JSON source data from a local file."""

    def reject_constant(value: str) -> object:
        raise ValueError(f"invalid JSON constant {value}")

    try:
        return cast(
            JsonValue,
            json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise _error(
            f"invalid JSON in source data file {path.name}",
            "Use one JSON object or a non-empty JSON array of objects.",
        ) from exc


__all__ = ["SourceInference", "infer_source_data", "infer_source_schema", "load_source_data"]
