"""Release-gate contracts for diagnostic privacy and uncommon type paths."""

from __future__ import annotations

from collections import deque
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.confidence import DEFAULT_CONFIDENCE_THRESHOLDS, classify_confidence
from open_mapping.model.expressions import Expression
from open_mapping.model.issues import IssueCode
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import JsonType, SchemaDocument
from open_mapping.verification.diagnostics import (
    validation_error_message,
    validation_error_pointer,
    validation_error_sort_key,
)
from open_mapping.verification.static import verify_static
from open_mapping.verification.type_inference import infer_expression_type


@pytest.mark.parametrize(
    ("schema", "instance", "expected"),
    [
        ({"required": ["needed"]}, {}, "required-property"),
        ({"type": "integer"}, "secret", "incompatible type"),
        ({"enum": ["allowed"]}, "secret", "allowed enum"),
        ({"pattern": "^[A-Z]+$"}, "secret", "required pattern"),
        ({"format": "date"}, "secret", "required format"),
        ({"additionalProperties": False}, {"secret": 1}, "unsupported property"),
        ({"minLength": 10}, "secret", "length constraint"),
        ({"minItems": 2}, ["secret"], "size constraint"),
        ({"minimum": 10}, 1, "range constraint"),
        ({"not": {}}, "secret", "schema constraint"),
    ],
)
def test_validation_diagnostic_categories_are_stable_and_redacted(
    schema: dict[str, JsonValue], instance: JsonValue, expected: str
) -> None:
    error = next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance))

    message = validation_error_message("sample", error)

    assert expected in message
    assert "secret" not in message
    assert validation_error_sort_key(error)[0] == validation_error_pointer(error)


@pytest.mark.parametrize(
    ("value", "summary"),
    [
        (None, "null"),
        (True, "boolean"),
        ("x" * 1001, "string(length=1000+)"),
        (1, "integer"),
        (1.5, "number"),
        ([0] * 1001, "array(length=1000+)"),
        ({"safe": 1}, "object(property_count=1)"),
    ],
)
def test_opt_in_diagnostic_value_summaries_disclose_only_shape(
    value: JsonValue, summary: str
) -> None:
    error = ValidationError("untrusted", validator="custom", instance=value)
    assert validation_error_message("sample", error, diagnostic_values=True).endswith(
        f"(observed {summary})"
    )


def test_required_pointer_falls_back_safely_for_malformed_errors() -> None:
    non_iterable = ValidationError(
        "malformed", validator="required", validator_value=1, instance={}, path=deque(["a"])
    )
    non_object = ValidationError(
        "malformed", validator="required", validator_value=["a"], instance="value"
    )
    already_present = ValidationError(
        "malformed", validator="required", validator_value=["a"], instance={"a": 1}
    )

    assert validation_error_pointer(non_iterable) == "/a"
    assert validation_error_pointer(non_object) == "/"
    assert validation_error_pointer(already_present) == "/"


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {
                "scalar": {"type": "integer"},
                "choice": {"type": "string", "enum": ["A", "B"]},
                "items": {"type": "array", "items": {"type": "string"}},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "properties": {"choice": {"type": "string", "enum": ["A", "B"]}},
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


def _expression(value: dict[str, JsonValue]) -> Expression:
    return TypeAdapter(Expression).validate_python(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, JsonType.NULL),
        (True, JsonType.BOOLEAN),
        (1, JsonType.INTEGER),
        (1.5, JsonType.NUMBER),
        ("value", JsonType.STRING),
        ([1], JsonType.ARRAY),
        ({"value": 1}, JsonType.OBJECT),
    ],
)
def test_literal_type_inference_covers_every_json_value(
    value: JsonValue, expected: JsonType
) -> None:
    source, target = _schemas()
    assert infer_expression_type(
        _expression({"op": "literal", "value": value}),
        source_schema=source,
        target_schema=target,
        current_types=(),
    ) == frozenset({expected})


@pytest.mark.parametrize(
    "key",
    [
        {"op": "literal", "value": "A"},
        {"op": "get", "document": "output", "path": "/choice"},
        {"op": "get", "document": "current", "path": "/choice"},
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "literal", "value": "A"},
            "otherwise": {"op": "literal", "value": "B"},
        },
    ],
)
def test_lookup_type_inference_handles_bounded_and_unbounded_keys(
    key: dict[str, JsonValue],
) -> None:
    source, target = _schemas()
    result = infer_expression_type(
        _expression(
            cast(dict[str, JsonValue], {"op": "lookup", "key": key, "values": {"A": 1, "B": 2}})
        ),
        source_schema=source,
        target_schema=target,
        current_types=(),
    )
    assert JsonType.INTEGER in result


@pytest.mark.parametrize(
    "collection",
    [
        {"op": "array", "items": [{"op": "literal", "value": "A"}]},
        {"op": "literal", "value": ["A"]},
        {"op": "get", "document": "current", "path": "/"},
    ],
)
def test_map_type_inference_handles_non_schema_collections(
    collection: dict[str, JsonValue],
) -> None:
    source, target = _schemas()
    result = infer_expression_type(
        _expression(
            cast(
                dict[str, JsonValue],
                {
                    "op": "map",
                    "collection": collection,
                    "expression": {"op": "get", "document": "current", "path": "/"},
                },
            )
        ),
        source_schema=source,
        target_schema=target,
        current_types=(frozenset({JsonType.ARRAY}),),
        current_pointer="/scalar",
    )
    assert result in (frozenset(), frozenset({JsonType.ARRAY}))


def _structural_schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "structural-source",
            "type": "object",
            "required": ["choice", "lines", "record", "records"],
            "properties": {
                "choice": {"type": "string"},
                "lines": {"type": "array", "items": {"type": "string"}},
                "record": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "integer"}},
                },
                "records": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["x"],
                        "properties": {"x": {"type": "integer"}},
                    },
                },
            },
        },
        schema_id=None,
        source_uri="structural-source",
    )
    target = parse_json_schema(
        {
            "$id": "structural-target",
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "string"}},
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["A", "B"]},
                },
                "status": {"type": "string", "enum": ["A", "B"]},
                "payloads": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["x"],
                        "properties": {"x": {"type": "string"}},
                    },
                },
            },
        },
        schema_id=None,
        source_uri="structural-target",
    )
    return source, target


def _mapping(target: str, expression: dict[str, JsonValue]) -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="release-coverage",
        source_schema="structural-source",
        source_schema_version="unversioned",
        target_schema="structural-target",
        target_schema_version="unversioned",
        rules=({"target": target, "expression": expression},),
    )


@pytest.mark.parametrize(
    ("target_path", "expression"),
    [
        (
            "/payload",
            {
                "op": "if",
                "condition": {"op": "literal", "value": True},
                "then": {"op": "literal", "value": None},
                "otherwise": {"op": "literal", "value": None},
            },
        ),
        (
            "/status",
            {"op": "get", "document": "current", "path": "/"},
        ),
        (
            "/values",
            {
                "op": "map",
                "collection": {"op": "literal", "value": ["A"]},
                "expression": {"op": "get", "document": "current", "path": "/"},
            },
        ),
        (
            "/values",
            {
                "op": "map",
                "collection": {"op": "get", "document": "input", "path": "/lines"},
                "expression": {"op": "get", "document": "current", "path": "/"},
            },
        ),
        (
            "/status",
            {
                "op": "lookup",
                "key": {"op": "get", "document": "input", "path": "/choice"},
                "values": {"known": "A"},
            },
        ),
        (
            "/payloads",
            {
                "op": "map",
                "collection": {"op": "get", "document": "input", "path": "/records"},
                "expression": {"op": "get", "document": "current", "path": "/"},
            },
        ),
    ],
    ids=(
        "null-object-branches",
        "current-without-collection",
        "literal-collection",
        "unbounded-current-enum",
        "nonexhaustive-lookup",
        "incompatible-direct-object",
    ),
)
def test_static_verification_rejects_unprovable_structural_and_enum_shapes(
    target_path: str, expression: dict[str, JsonValue]
) -> None:
    source, target = _structural_schemas()

    result = verify_static(
        _mapping(target_path, expression), source_schema=source, target_schema=target
    )

    assert any(issue.code == IssueCode.TYPE_MISMATCH for issue in result.issues)


def test_structural_lookup_default_is_checked_and_assignable() -> None:
    source, target = _structural_schemas()
    expression: dict[str, JsonValue] = {
        "op": "lookup",
        "key": {"op": "get", "document": "input", "path": "/choice"},
        "values": {"A": {"x": "first"}, "B": {"x": "second"}},
        "default": {
            "op": "object",
            "fields": {"x": {"op": "literal", "value": "fallback"}},
        },
    }

    result = verify_static(
        _mapping("/payload", expression), source_schema=source, target_schema=target
    )

    assert result.valid
    assert classify_confidence(None, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS).value == "none"
