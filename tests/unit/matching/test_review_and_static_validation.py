"""Review policy and static validation tests."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.serialization.suggestions import suggestion_report_sha256
from open_mapping.verification.static import verify_static


def _fixture() -> tuple[SchemaDocument, SchemaDocument, SuggestionReport]:
    source = parse_json_schema(
        {"$id": "s", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {"$id": "t", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="t",
    )
    sets = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=5,
    )
    report = build_deterministic_suggestions(source, target, candidate_sets=sets, hints=None)
    return source, target, report


def test_review_policies_and_invalid_decision() -> None:
    source, target, report = _fixture()
    review = SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report),
        mapping_id="m",
        decisions=(
            SuggestionReviewDecision(
                target_path="/a",
                action=ReviewAction.SELECT_CANDIDATE,
                source_path="/missing",
                reason="x",
            ),
        ),
    )
    invalid = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=False,
    )
    assert invalid.mapping is None
    manual_only = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.MANUAL_ONLY,
        review=None,
        require_complete_review=False,
    )
    assert manual_only.mapping is not None or manual_only.issues


def test_static_root_version_and_required() -> None:
    source = parse_json_schema(
        {"$id": "s", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "required": ["a", "b"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        },
        schema_id=None,
        source_uri="t",
    )
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="wrong",
        target_schema="t",
        target_schema_version="wrong",
        rules=({"target": "/b", "expression": {"op": "get", "path": "/a"}},),
    )
    result = verify_static(mapping, source_schema=source, target_schema=target)
    assert not result.valid
    assert any(i.code.value == "REQUIRED_TARGET_UNMAPPED" for i in result.issues)
