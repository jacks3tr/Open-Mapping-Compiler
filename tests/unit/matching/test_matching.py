"""Matching and review tests."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.ambiguity import detect_ambiguity
from open_mapping.matching.candidates import (
    DEFAULT_CANDIDATE_WEIGHTS,
    generate_candidates,
    iter_target_mapping_units,
    validate_suggestion_coverage,
)
from open_mapping.matching.confidence import DEFAULT_CONFIDENCE_THRESHOLDS, classify_confidence
from open_mapping.matching.hints import hint_to_rule
from open_mapping.matching.names import name_tokens
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.hints import DirectHint
from open_mapping.model.reviews import AssemblyPolicy, SuggestionReviewDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import ConfidenceBand, TargetCandidateSet
from open_mapping.serialization.suggestions import suggestion_report_sha256


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "s",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "qty": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "quantity": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="t",
    )
    return source, target


def test_names_and_confidence() -> None:
    assert name_tokens("orderId") == ("order", "identifier")
    assert (
        classify_confidence(0.95, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS) == ConfidenceBand.HIGH
    )
    assert classify_confidence(0.5, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS) == ConfidenceBand.LOW


def test_candidate_generation_and_suggestions() -> None:
    source, target = _schemas()
    sets = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=5,
    )
    assert len(sets) == len(iter_target_mapping_units(target))
    report = build_deterministic_suggestions(source, target, candidate_sets=sets, hints=None)
    assert not validate_suggestion_coverage(report, target)
    assert report.summary.total_targets == 2


def test_ambiguity_detection() -> None:
    ambiguous = TargetCandidateSet(
        target_path="/address",
        candidates=(
            {"target_path": "/address", "source_path": "/shipToAddress", "raw_score": 0.9},
            {"target_path": "/address", "source_path": "/billToAddress", "raw_score": 0.88},
        ),
    )
    assert detect_ambiguity(ambiguous, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS)


def test_hint_to_rule() -> None:
    hint = DirectHint(target="/name", source="/name", reason="direct")
    rule = hint_to_rule(hint, "t", "1")
    assert rule.target == "/name"


def test_review_assembly() -> None:
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
        decisions=(),
    )
    result = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.HIGH_AND_MANUAL,
        review=review,
        require_complete_review=False,
    )
    assert result.mapping is not None or result.issues
