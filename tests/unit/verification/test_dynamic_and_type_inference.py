"""Dynamic verification and type inference tests."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.dynamic import VerificationSample, verify_samples
from open_mapping.verification.static import verify_static
from open_mapping.verification.type_inference import infer_expression_type


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "s",
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}, "key": {"type": ["string", "null"]}},
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "integer"}, "s": {"type": "string", "enum": ["A"]}},
        },
        schema_id=None,
        source_uri="t",
    )
    return source, target


def test_dynamic_nonfinite_and_mismatch() -> None:
    source, target = _schemas()
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
        samples=(VerificationSample(id="bad", input={"a": 1}, expected={"a": float("nan")}),),
    )
    assert not report.samples[0].valid


def test_dynamic_distinguishes_explicit_null_expected_from_omitted_expected() -> None:
    source, target = _schemas()
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
        samples=(
            VerificationSample.model_validate(
                {"id": "explicit-null", "input": {"a": 1}, "expected": None}
            ),
            VerificationSample.model_validate({"id": "omitted", "input": {"a": 1}}),
        ),
    )

    assert [issue.code.value for issue in report.samples[0].issues] == ["GOLDEN_OUTPUT_MISMATCH"]
    assert report.samples[1].valid
    report = verify_samples(
        mapping,
        source_schema=source,
        target_schema=target,
        samples=(VerificationSample(id="mis", input={"a": 1}, expected={"a": 2}),),
    )
    assert not report.samples[0].valid


def test_static_expression_validation() -> None:
    source, target = _schemas()
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=(
            {"target": "/s", "expression": {"op": "literal", "value": {"x": 1}}},
            {
                "target": "/s",
                "expression": {
                    "op": "if",
                    "condition": {"op": "literal", "value": True},
                    "then": {"op": "literal", "value": "A"},
                    "otherwise": {"op": "literal", "value": "B"},
                },
            },
            {
                "target": "/s",
                "expression": {"op": "concat", "operands": [{"op": "literal", "value": "A"}]},
            },
            {"target": "/missing", "expression": {"op": "literal", "value": 1}},
            {"target": "/a", "expression": {"op": "get", "path": "/x", "document": "current"}},
        ),
        invariants=(
            Invariant(
                id="i",
                when={"op": "get", "path": "/missing", "document": "input"},
                assertion={
                    "op": "not_null",
                    "value": {"op": "get", "path": "/missing", "document": "output"},
                },
            ),
        ),
    )
    result = verify_static(mapping, source_schema=source, target_schema=target)
    assert not result.valid


def test_type_inference_current_and_null_lookup() -> None:
    source, target = _schemas()
    expr: Expression = TypeAdapter(Expression).validate_python(
        {"op": "get", "path": "/x", "document": "current"}
    )
    assert (
        infer_expression_type(
            expr, source_schema=source, target_schema=target, current_types=(), current_pointer=None
        )
        == frozenset()
    )
    lookup: Expression = TypeAdapter(Expression).validate_python(
        {
            "op": "lookup",
            "key": {"op": "get", "path": "/key", "document": "input"},
            "values": {"A": 1},
        }
    )
    inferred = infer_expression_type(
        lookup, source_schema=source, target_schema=target, current_types=(), current_pointer=None
    )
    assert inferred
