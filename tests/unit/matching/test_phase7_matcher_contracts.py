"""Synthetic matcher contracts required by the industrial benchmarks."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.ambiguity import detect_ambiguity
from open_mapping.matching.candidates import CandidateWeights, generate_candidates
from open_mapping.matching.confidence import DEFAULT_CONFIDENCE_THRESHOLDS
from open_mapping.matching.proposals import (
    apply_provider_assistance,
    build_deterministic_suggestions,
)
from open_mapping.model.hints import DirectHint, MappingHints
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MatchCandidate,
    SuggestionDisposition,
    TargetCandidateSet,
)
from open_mapping.providers.protocol import ProviderProposal, ProviderResponse


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["alpha", "beta", "manual"],
            "properties": {
                "alpha": {"type": "string"},
                "beta": {"type": "string"},
                "manual": {"type": "string"},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["result", "manual", "count"],
            "properties": {
                "result": {"type": "string"},
                "manual": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


def test_weighted_score_is_bounded_and_equals_its_component_sum() -> None:
    source, target = _schemas()
    weights = CandidateWeights()
    sets = generate_candidates(
        source, target, source_profiles=(), target_profiles=(), weights=weights, top_k=10
    )
    for candidate_set in sets:
        for candidate in candidate_set.candidates:
            signals = candidate.signals
            expected = round(
                signals.exact_name * weights.exact_name
                + signals.name_similarity * weights.name_similarity
                + signals.description_similarity * weights.description_similarity
                + signals.type_compatibility * weights.type_compatibility
                + signals.enum_overlap * weights.enum_overlap
                + signals.structural_context * weights.structural_context
                + signals.sample_profile * weights.sample_profile,
                12,
            )
            assert 0.0 <= candidate.raw_score <= 1.0
            assert candidate.raw_score == expected


def test_sample_profile_weight_cannot_exceed_fifteen_percent() -> None:
    with pytest.raises(ValidationError, match="sample profile"):
        CandidateWeights(exact_name=0.24, sample_profile=0.16)


def test_equal_scores_use_source_path_as_deterministic_tie_break() -> None:
    source = parse_json_schema(
        {
            "$id": "s",
            "type": "object",
            "properties": {"z": {"type": "string"}, "a": {"type": "string"}},
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {"$id": "t", "type": "object", "properties": {"x": {"type": "string"}}},
        schema_id=None,
        source_uri="t",
    )
    candidates = generate_candidates(
        source, target, source_profiles=(), target_profiles=(), top_k=10
    )[0]
    tied = sorted(candidates.candidates, key=lambda item: (item.raw_score, item.source_path))
    assert [
        item.source_path for item in candidates.candidates if item.raw_score == tied[0].raw_score
    ] == sorted(
        item.source_path for item in candidates.candidates if item.raw_score == tied[0].raw_score
    )


def test_manual_no_match_close_top_two_and_static_invalid_margin() -> None:
    source, target = _schemas()
    sets = (
        TargetCandidateSet(
            target_path="/result",
            candidates=(
                MatchCandidate(source_path="/alpha", target_path="/result", raw_score=0.75),
                MatchCandidate(source_path="/beta", target_path="/result", raw_score=0.70),
            ),
        ),
        TargetCandidateSet(
            target_path="/manual",
            candidates=(
                MatchCandidate(source_path="/manual", target_path="/manual", raw_score=1.0),
            ),
        ),
        TargetCandidateSet(
            target_path="/count",
            candidates=(
                MatchCandidate(source_path="/alpha", target_path="/count", raw_score=0.95),
                MatchCandidate(source_path="/beta", target_path="/count", raw_score=0.94),
            ),
        ),
    )
    hints = MappingHints(
        hints_version="0.1",
        id="manual",
        direct=(DirectHint(target="/manual", source="/manual", reason="explicit"),),
    )
    report = build_deterministic_suggestions(source, target, candidate_sets=sets, hints=hints)
    by_target = {item.target_path: item for item in report.suggestions}
    assert by_target["/manual"].confidence_band == ConfidenceBand.NONE
    assert by_target["/manual"].disposition == SuggestionDisposition.MANUAL
    assert by_target["/result"].disposition == SuggestionDisposition.AMBIGUOUS
    assert by_target["/count"].confidence_band == ConfidenceBand.NONE
    assert by_target["/count"].disposition == SuggestionDisposition.NO_MATCH


def test_provider_can_select_only_an_existing_candidate_without_changing_scores() -> None:
    source, target = _schemas()
    sets = (
        TargetCandidateSet(
            target_path="/result",
            candidates=(
                MatchCandidate(source_path="/alpha", target_path="/result", raw_score=0.91),
                MatchCandidate(source_path="/beta", target_path="/result", raw_score=0.75),
            ),
        ),
        TargetCandidateSet(target_path="/manual", candidates=()),
        TargetCandidateSet(target_path="/count", candidates=()),
    )
    baseline = build_deterministic_suggestions(source, target, candidate_sets=sets, hints=None)
    before = tuple(
        (item.source_path, item.raw_score) for item in baseline.suggestions[2].candidates
    )
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/result",
                abstain=False,
                selected_source_paths=("/beta",),
                expression={"op": "get", "path": "/beta"},
                reason="role evidence",
            ),
        ),
    )
    assisted = apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": response}
    )
    selected = next(item for item in assisted.suggestions if item.target_path == "/result")
    assert selected.selected_source_path == "/beta"
    assert selected.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert tuple((item.source_path, item.raw_score) for item in selected.candidates) == before
    outside = response.model_copy(
        update={
            "proposals": (
                ProviderProposal(
                    target_path="/result",
                    abstain=False,
                    selected_source_paths=("/new-path",),
                    expression={"op": "get", "path": "/new-path"},
                ),
            )
        }
    )
    rejected = apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": outside}
    )
    assert rejected.suggestions == baseline.suggestions


def test_identifier_words_do_not_override_a_weak_runner_up() -> None:
    candidate_set = TargetCandidateSet(
        target_path="/line",
        candidates=(
            MatchCandidate(source_path="/productionLine", target_path="/line", raw_score=0.95),
            MatchCandidate(source_path="/workCenter", target_path="/line", raw_score=0.20),
        ),
    )
    assert not detect_ambiguity(candidate_set, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS)


def test_renamed_fields_use_shared_metadata_to_express_ambiguity() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["machineRoute", "cellAssignment"],
            "properties": {
                "machineRoute": {
                    "type": "string",
                    "title": "Execution Resource",
                    "description": "Resource that executes the operation.",
                },
                "cellAssignment": {
                    "type": "string",
                    "title": "Execution Resource",
                    "description": "Resource that executes the operation.",
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "title": "Execution Resource",
                    "description": "Resource that executes the operation.",
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    candidates = generate_candidates(
        source, target, source_profiles=(), target_profiles=(), top_k=10
    )
    report = build_deterministic_suggestions(source, target, candidate_sets=candidates, hints=None)
    suggestion = report.suggestions[0]
    assert suggestion.disposition == SuggestionDisposition.AMBIGUOUS
    assert {candidate.source_path for candidate in suggestion.candidates[:2]} == {
        "/machineRoute",
        "/cellAssignment",
    }


def test_static_invalid_close_runner_up_does_not_create_false_ambiguity() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["good", "invalid"],
            "properties": {
                "good": {"type": "string"},
                "invalid": {"type": "integer"},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target",
    )
    candidate_set = TargetCandidateSet(
        target_path="/result",
        candidates=(
            MatchCandidate(source_path="/good", target_path="/result", raw_score=0.75),
            MatchCandidate(source_path="/invalid", target_path="/result", raw_score=0.74),
        ),
    )
    report = build_deterministic_suggestions(
        source, target, candidate_sets=(candidate_set,), hints=None
    )
    suggestion = report.suggestions[0]
    assert suggestion.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert suggestion.selected_source_path == "/good"


def test_static_valid_close_runner_up_remains_ambiguous() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["first", "second"],
            "properties": {
                "first": {"type": "string"},
                "second": {"type": "string"},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target",
    )
    candidate_set = TargetCandidateSet(
        target_path="/result",
        candidates=(
            MatchCandidate(source_path="/first", target_path="/result", raw_score=0.75),
            MatchCandidate(source_path="/second", target_path="/result", raw_score=0.72),
        ),
    )
    report = build_deterministic_suggestions(
        source, target, candidate_sets=(candidate_set,), hints=None
    )
    assert report.suggestions[0].disposition == SuggestionDisposition.AMBIGUOUS
