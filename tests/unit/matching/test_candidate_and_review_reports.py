"""Candidate, review, and report tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.candidates import (
    DEFAULT_CANDIDATE_WEIGHTS,
    CandidateWeights,
    generate_candidates,
    iter_target_mapping_units,
    validate_suggestion_coverage,
)
from open_mapping.matching.compatibility import type_compatibility
from open_mapping.matching.confidence import DEFAULT_CONFIDENCE_THRESHOLDS, classify_confidence
from open_mapping.matching.hints import hint_to_rule
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.hints import ConstantHint, DateHint, LookupHint, UnitConversionHint
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.reports.markdown_report import render_review_markdown
from open_mapping.reports.text_report import render_review_text
from open_mapping.serialization.suggestions import suggestion_report_sha256


def test_compatibility_and_weights() -> None:
    scalar = SchemaField(pointer="/a", types=frozenset({JsonType.STRING}), required=True)
    array = SchemaField(pointer="/a", types=frozenset({JsonType.ARRAY}), required=True)
    assert type_compatibility(scalar, array) is None
    assert type_compatibility(array, scalar) is None
    with pytest.raises(ValidationError):
        CandidateWeights(exact_name=2.0)


def test_confidence_low_none() -> None:
    assert classify_confidence(0.2, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS) == ConfidenceBand.NONE


def test_hint_conversions() -> None:
    assert (
        hint_to_rule(
            LookupHint(target="/x", source="/a", values={"A": "b"}, reason="r"), "t", "1"
        ).target
        == "/x"
    )
    assert (
        hint_to_rule(
            UnitConversionHint(
                target="/x", value_source="/v", unit_source="/u", factors={"A": 2}, reason="r"
            ),
            "t",
            "1",
        ).target
        == "/x"
    )
    assert (
        hint_to_rule(
            DateHint(target="/x", source="/d", pattern="YYYY", reason="r"), "t", "1"
        ).target
        == "/x"
    )
    assert hint_to_rule(ConstantHint(target="/x", value=1, reason="r"), "t", "1").target == "/x"
    with pytest.raises(ValueError):
        hint_to_rule(object(), "t", "1")


def test_candidate_coverage_errors() -> None:
    target = parse_json_schema(
        {"$id": "t", "type": "object", "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="t",
    )
    report = SuggestionReport(
        report_version="0.1",
        source_schema_id="s",
        source_schema_version="unversioned",
        target_schema_id="t",
        target_schema_version="unversioned",
        suggestions=(),
        summary=SuggestionSummary(),
    )
    assert validate_suggestion_coverage(report, target)
    assert iter_target_mapping_units(target)


def test_review_select_and_incomplete() -> None:
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
    suggestion = report.suggestions[0]
    source_path = suggestion.candidates[0].source_path
    review = SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report),
        mapping_id="m",
        decisions=(
            SuggestionReviewDecision(
                target_path="/a",
                action=ReviewAction.SELECT_CANDIDATE,
                source_path=source_path,
                reason="x",
            ),
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
    assert result.mapping is not None
    incomplete = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=SuggestionReviewDocument(
            review_version="0.1",
            suggestion_report_sha256=suggestion_report_sha256(report),
            mapping_id="m",
            decisions=(),
        ),
        require_complete_review=True,
    )
    assert incomplete.mapping is None
    no_review = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=None,
        require_complete_review=False,
    )
    assert no_review.mapping is None


def test_report_summary_reconciliation() -> None:
    with pytest.raises(ValidationError, match="total_targets"):
        SuggestionReport(
            report_version="0.1",
            source_schema_id="s",
            source_schema_version="1",
            target_schema_id="t",
            target_schema_version="1",
            suggestions=(
                MappingSuggestion(
                    target_path="/a",
                    confidence_band=ConfidenceBand.HIGH,
                    disposition=SuggestionDisposition.SUGGESTED,
                    confidence_score=0.9,
                    confidence_method="heuristic-v0.1",
                    selected_source_path="/x",
                    expression={"op": "get", "path": "/x"},
                ),
            ),
            summary=SuggestionSummary(total_targets=2),
        )
    result = __import__("open_mapping.model.reviews", fromlist=["ReviewResult"]).ReviewResult(
        suggestion_report_sha256="x",
        mapping_id="m",
        unresolved_targets=("/a",),
        issues=(),
    )
    assert "/a" in render_review_text(result)
    assert "/a" in render_review_markdown(result)
