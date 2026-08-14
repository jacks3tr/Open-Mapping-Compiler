"""Cross-module validation tests."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant
from open_mapping.model.mappings import MappingDocument, MappingRule
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.schema import JsonType, SchemaDocument, SchemaField
from open_mapping.providers.protocol import ProviderProposal, ProviderRequest, ProviderResponse
from open_mapping.serialization.suggestions import suggestion_report_sha256
from open_mapping.verification.static import verify_static
from open_mapping.verification.type_inference import infer_expression_type


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "s",
            "type": "object",
            "required": ["name", "status"],
            "properties": {
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["A", "B"]},
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
                },
            },
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "required": ["name", "status"],
            "properties": {
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["A"]},
                "count": {"type": "integer"},
            },
        },
        schema_id=None,
        source_uri="t",
    )
    return source, target


def _mapping(rules: tuple[MappingRule | dict[str, object], ...] = ()) -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=rules,
    )


def test_infer_expression_types() -> None:
    source, target = _schemas()
    cases = {
        "literal": {"op": "literal", "value": 1},
        "object": {"op": "object", "fields": {"x": {"op": "literal", "value": 1}}},
        "array": {"op": "array", "items": []},
        "map": {
            "op": "map",
            "collection": {"op": "get", "path": "/items"},
            "expression": {"op": "get", "path": "/id", "document": "current"},
        },
        "coalesce": {"op": "coalesce", "operands": [{"op": "literal", "value": "x"}]},
        "concat": {"op": "concat", "operands": [{"op": "literal", "value": "x"}]},
        "cast": {"op": "cast", "value": {"op": "literal", "value": 1}, "target_type": "string"},
        "if": {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "literal", "value": 1},
            "otherwise": {"op": "literal", "value": 2},
        },
        "equals": {
            "op": "equals",
            "left": {"op": "literal", "value": 1},
            "right": {"op": "literal", "value": 1},
        },
        "not": {"op": "not", "value": {"op": "literal", "value": True}},
        "and": {
            "op": "and",
            "operands": [{"op": "literal", "value": True}, {"op": "literal", "value": True}],
        },
        "lookup": {"op": "lookup", "key": {"op": "get", "path": "/status"}, "values": {"A": "a"}},
        "add": {
            "op": "add",
            "left": {"op": "literal", "value": 1},
            "right": {"op": "literal", "value": 2},
        },
        "round": {"op": "round", "value": {"op": "literal", "value": 1.2}},
        "parse_date": {
            "op": "parse_date",
            "value": {"op": "literal", "value": "2026-01-01T00:00:00Z"},
        },
        "format_date": {
            "op": "format_date",
            "value": {"op": "literal", "value": "2026-01-01T00:00:00.000Z"},
            "pattern": "YYYY",
        },
    }
    for expr in cases.values():
        parsed: Expression = TypeAdapter(Expression).validate_python(expr)
        infer_expression_type(
            parsed,
            source_schema=source,
            target_schema=target,
            current_types=(),
            current_pointer=None,
        )
    assert JsonType.ARRAY in infer_expression_type(
        TypeAdapter(Expression).validate_python(cases["map"]),
        source_schema=source,
        target_schema=target,
        current_types=(),
        current_pointer=None,
    )


def test_static_error_paths() -> None:
    source, target = _schemas()
    mapping = _mapping(
        (
            {"target": "/name", "expression": {"op": "get", "path": "/missing"}},
            {"target": "/name", "expression": {"op": "get", "path": "/name"}},
            {"target": "/status", "expression": {"op": "get", "path": "/status"}},
            {"target": "/status/x", "expression": {"op": "literal", "value": 1}},
        )
    )
    result = verify_static(mapping, source_schema=source, target_schema=target)
    codes = {issue.code.value for issue in result.issues}
    assert "SOURCE_PATH_NOT_FOUND" in codes
    assert "DUPLICATE_TARGET_ASSIGNMENT" in codes
    assert "TARGET_PATH_NOT_FOUND" in codes


def test_enum_mismatch() -> None:
    source, target = _schemas()
    mapping = _mapping(
        (
            {"target": "/name", "expression": {"op": "get", "path": "/name"}},
            {"target": "/status", "expression": {"op": "literal", "value": "B"}},
        )
    )
    assert not verify_static(mapping, source_schema=source, target_schema=target).valid


def test_evaluation_context_operations() -> None:
    source, target = _schemas()
    context = EvaluationContext(
        input_document={"a": 1},
        output_document={"b": 2},
        current_stack=({"c": 3},),
    )
    assert (
        evaluate_expression(
            TypeAdapter(Expression).validate_python(
                {"op": "get", "path": "/c", "document": "current"}
            ),
            context,
        )
        == 3
    )
    assert (
        evaluate_expression(
            TypeAdapter(Expression).validate_python(
                {"op": "get", "path": "/b", "document": "output"}
            ),
            context,
        )
        == 2
    )
    assert evaluate_expression(
        TypeAdapter(Expression).validate_python(
            {"op": "object", "fields": {"z": {"op": "literal", "value": 1}}}
        ),
        context,
    ) == {"z": 1}


def test_invariant_error_paths() -> None:
    invariant = Invariant(
        id="i",
        assertion={"op": "matches", "value": {"op": "literal", "value": 1}, "pattern": "x"},
    )
    assert evaluate_invariant(invariant, input_document={}, output_document={})
    invariant = Invariant(
        id="i",
        when={"op": "literal", "value": False},
        assertion={"op": "not_null", "value": {"op": "literal", "value": None}},
    )
    assert not evaluate_invariant(invariant, input_document={}, output_document={})


def test_review_error_paths() -> None:
    source, target = _schemas()
    sets = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=5,
    )
    report = build_deterministic_suggestions(source, target, candidate_sets=sets, hints=None)
    review = SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report),
        mapping_id="m",
        decisions=(
            SuggestionReviewDecision(
                target_path="/name", action=ReviewAction.ACCEPT_SELECTED, reason="x"
            ),
            SuggestionReviewDecision(target_path="/name", action=ReviewAction.DEFER, reason="x"),
        ),
    )
    result = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=True,
    )
    assert result.mapping is None


def test_provider_response_validation() -> None:
    from open_mapping.providers.http import _validate_response

    field = SchemaField(pointer="/a", types=frozenset({JsonType.STRING}), required=True)
    request = ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="s",
        target_schema_id="t",
        target_path="/a",
        candidates=(),
        source_field_metadata=(),
        target_field_metadata=field,
        sample_profiles=(),
    )
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(ProviderProposal(target_path="/wrong", abstain=True),),
    )
    with pytest.raises(OpenMappingError):
        _validate_response(response, request)
