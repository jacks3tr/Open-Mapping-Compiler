"""Adapter, evaluator, invariant, and profile error tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import EvaluationLimits
from open_mapping.matching.profiles import profile_samples
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant
from open_mapping.model.json_types import JsonValue


def _expr(value: dict[str, object]) -> Expression:
    return TypeAdapter(Expression).validate_python(value)


def test_schema_adapter_error_paths(tmp_path: Path) -> None:
    with pytest.raises(OpenMappingError):
        parse_json_schema({"type": "object"}, schema_id=None, source_uri="x")
    with pytest.raises(OpenMappingError):
        parse_json_schema(
            {
                "$id": "x",
                "$schema": "https://json-schema.org/draft/2019-09/schema",
                "type": "object",
            },
            schema_id=None,
            source_uri="x",
        )
    with pytest.raises(OpenMappingError):
        parse_json_schema(
            {
                "$id": "x",
                "type": "object",
                "properties": {"a": {"oneOf": [{"type": "object"}, {"type": "string"}]}},
            },
            schema_id=None,
            source_uri="x",
        )
    path = tmp_path / "bool.json"
    path.write_text('{"$id":"b","type":"object","properties":{"x":true}}', encoding="utf-8")
    doc = parse_json_schema(
        {"$id": "b", "type": "object", "properties": {"x": True}}, schema_id=None, source_uri="b"
    )
    assert doc.schema_id == "b"


def test_evaluator_error_paths() -> None:
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "get", "path": "/x", "document": "current"}),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "map",
                    "collection": {"op": "literal", "value": 1},
                    "expression": {"op": "literal", "value": 1},
                }
            ),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": "x"}, "target_type": "integer"}
            ),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "cast", "value": {"op": "literal", "value": 1}, "target_type": "boolean"}),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "concat", "operands": [{"op": "literal", "value": 1}]}),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "not", "value": {"op": "literal", "value": 1}}),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "or",
                    "operands": [{"op": "literal", "value": True}, {"op": "literal", "value": 1}],
                }
            ),
            EvaluationContext(input_document={}),
        )
    assert (
        evaluate_expression(
            _expr({"op": "lookup", "key": {"op": "literal", "value": "x"}, "values": {}}),
            EvaluationContext(input_document={}),
        )
        is None
    )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "parse_date", "value": {"op": "literal", "value": 1}}),
            EvaluationContext(input_document={}),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "array",
                    "items": [{"op": "literal", "value": 1}, {"op": "literal", "value": 2}],
                }
            ),
            EvaluationContext(input_document={}),
            EvaluationLimits(max_array_items=1),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "literal", "value": "abc"}),
            EvaluationContext(input_document={}),
            EvaluationLimits(max_string_length=2),
        )


def test_invariant_error_variants() -> None:
    cases = [
        {"op": "not_null", "value": {"op": "literal", "value": None}},
        {"op": "in", "value": {"op": "literal", "value": 1}, "allowed": [2]},
        {"op": "matches", "value": {"op": "literal", "value": "x"}, "pattern": "y"},
        {
            "op": "greater_than",
            "left": {"op": "literal", "value": True},
            "right": {"op": "literal", "value": 1},
        },
        {"op": "unique", "value": {"op": "literal", "value": [1, 1]}},
        {"op": "length_equals", "value": {"op": "literal", "value": "ab"}, "expected": 3},
    ]
    for assertion in cases:
        assert evaluate_invariant(
            Invariant(id="i", assertion=assertion), input_document={}, output_document={}
        )


def test_profile_value_classes() -> None:
    schema = parse_json_schema(
        {
            "$id": "p",
            "type": "object",
            "properties": {
                "uuid": {"type": "string"},
                "num": {"type": "string"},
                "dec": {"type": "string"},
                "email": {"type": "string"},
                "uri": {"type": "string"},
                "code": {"type": "string"},
                "low": {"type": "string"},
                "arr": {"type": "array"},
                "obj": {"type": "object"},
            },
        },
        schema_id=None,
        source_uri="p",
    )
    samples: list[JsonValue] = [
        {
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "num": "123",
            "dec": "1.2",
            "email": "a@b.com",
            "uri": "https://x",
            "code": "ABC-1",
            "low": "hello",
            "arr": [1],
            "obj": {},
        },
        {"uuid": None},
    ]
    profiles = profile_samples(schema, samples)
    by = {p.pointer: p for p in profiles}
    assert by["/uuid"].null_count == 1
    assert by["/num"].pattern_classes == ("integer-string",)
    assert by["/arr"].observed_types
