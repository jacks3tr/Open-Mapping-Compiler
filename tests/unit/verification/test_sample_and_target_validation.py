"""Sample and target validation tests."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.model.expressions import Expression
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import JsonType, SchemaDocument
from open_mapping.verification.dynamic import (
    VerificationSample,
    verify_samples,
)
from open_mapping.verification.target_schema import validate_target_document
from open_mapping.verification.type_inference import infer_expression_type


def _source() -> SchemaDocument:
    return parse_json_schema(
        {"$id": "s", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="s",
    )


def _target() -> SchemaDocument:
    return parse_json_schema(
        {"$id": "t", "type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        schema_id=None,
        source_uri="t",
    )


def _bad_mapping() -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=({"target": "/a", "expression": {"op": "get", "path": "/a"}},),
    )


def test_verify_samples_static_invalid() -> None:
    source = _source()
    target = _target()
    report = verify_samples(_bad_mapping(), source_schema=source, target_schema=target, samples=())
    assert report.samples == ()


def test_verify_samples_runtime_error_and_mismatch() -> None:
    source = parse_json_schema(
        {
            "$id": "s",
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {"$id": "t", "type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        schema_id=None,
        source_uri="t",
    )
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=({"target": "/a", "expression": {"op": "get", "path": "/a"}},),
    )
    report = verify_samples(
        mapping,
        source_schema=source,
        target_schema=target,
        samples=(VerificationSample(id="x", input={}, expected={"a": 2}),),
    )
    assert not report.samples[0].valid


def test_target_schema_error() -> None:
    target = _target()
    issues = validate_target_document(target, {"a": "not-int"})
    assert issues


def test_infer_expression_variants() -> None:
    source = _source()
    target = _target()
    values: list[object] = [None, True, 1, 1.5, "x", [], {}]
    for value in values:
        inferred = infer_expression_type(
            TypeAdapter(Expression).validate_python({"op": "literal", "value": value}),
            source_schema=source,
            target_schema=target,
            current_types=(),
            current_pointer=None,
        )
        assert inferred
    context = EvaluationContext(
        input_document={"a": "x"}, output_document={"a": 1}, current_stack=({"a": 1},)
    )
    evaluate_expression(
        TypeAdapter(Expression).validate_python({"op": "get", "path": "/a", "document": "output"}),
        context,
    )
    assert JsonType.NUMBER in infer_expression_type(
        TypeAdapter(Expression).validate_python(
            {
                "op": "divide",
                "left": {"op": "literal", "value": 1},
                "right": {"op": "literal", "value": 2},
            }
        ),
        source_schema=source,
        target_schema=target,
        current_types=(),
        current_pointer=None,
    )
