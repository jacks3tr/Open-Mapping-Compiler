"""Matching and review serialization tests."""

from __future__ import annotations

from pathlib import Path

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.ambiguity import detect_ambiguity
from open_mapping.matching.candidates import (
    validate_suggestion_coverage,
)
from open_mapping.matching.compatibility import type_compatibility
from open_mapping.matching.confidence import DEFAULT_CONFIDENCE_THRESHOLDS
from open_mapping.matching.profiles import profile_samples
from open_mapping.model.json_types import JsonValue
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.model.suggestions import SuggestionReport, SuggestionSummary
from open_mapping.serialization.reviews import dumps_suggestion_review, load_suggestion_review


def test_ambiguity_parent_role() -> None:
    candidate_set = {
        "target_path": "/line",
        "candidates": (
            {"target_path": "/line", "source_path": "/workCenter", "raw_score": 0.9},
            {"target_path": "/line", "source_path": "/productionLine", "raw_score": 0.84},
        ),
    }
    from open_mapping.model.suggestions import TargetCandidateSet

    assert detect_ambiguity(
        TargetCandidateSet.model_validate(candidate_set), thresholds=DEFAULT_CONFIDENCE_THRESHOLDS
    )


def test_compatibility_null_only() -> None:
    null_field = SchemaField(pointer="/a", types=frozenset({JsonType.NULL}), required=False)
    required = SchemaField(pointer="/b", types=frozenset({JsonType.STRING}), required=True)
    assert type_compatibility(null_field, required) is None


def test_profile_pattern_classes() -> None:
    schema = parse_json_schema(
        {
            "$id": "p",
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "n": {"type": "integer"},
                "arr": {"type": "array"},
                "obj": {"type": "object"},
            },
        },
        schema_id=None,
        source_uri="p",
    )
    samples: list[JsonValue] = [
        {"s": "https://example.com/a", "n": 1, "arr": [], "obj": {}},
        {"s": "ABC-1", "n": 2, "arr": [], "obj": {}},
    ]
    profiles = profile_samples(schema, samples)
    by = {p.pointer: p for p in profiles}
    assert by["/n"].distinct_count == 2
    assert by["/arr"].observed_types
    assert by["/obj"].observed_types


def test_suggestion_coverage_duplicate_and_unexpected() -> None:
    target = parse_json_schema(
        {"$id": "t", "type": "object", "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="t",
    )
    report = SuggestionReport(
        report_version="0.1",
        source_schema_id="s",
        source_schema_version="1",
        target_schema_id="t",
        target_schema_version="1",
        suggestions=(),
        summary=SuggestionSummary(),
    )
    assert validate_suggestion_coverage(report, target)
    from open_mapping.model.suggestions import MappingSuggestion

    report = report.model_copy(
        update={
            "suggestions": (
                MappingSuggestion(
                    target_path="/a",
                    confidence_band=__import__(
                        "open_mapping.model.suggestions", fromlist=["ConfidenceBand"]
                    ).ConfidenceBand.HIGH,
                    disposition=__import__(
                        "open_mapping.model.suggestions", fromlist=["SuggestionDisposition"]
                    ).SuggestionDisposition.SUGGESTED,
                    confidence_score=0.9,
                    confidence_method="heuristic-v0.1",
                    selected_source_path="/x",
                    expression={"op": "get", "path": "/x"},
                ),
                MappingSuggestion(
                    target_path="/a",
                    confidence_band=__import__(
                        "open_mapping.model.suggestions", fromlist=["ConfidenceBand"]
                    ).ConfidenceBand.HIGH,
                    disposition=__import__(
                        "open_mapping.model.suggestions", fromlist=["SuggestionDisposition"]
                    ).SuggestionDisposition.SUGGESTED,
                    confidence_score=0.9,
                    confidence_method="heuristic-v0.1",
                    selected_source_path="/x",
                    expression={"op": "get", "path": "/x"},
                ),
            )
        }
    )
    assert validate_suggestion_coverage(report, target)


def test_review_yaml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "review.yaml"
    review = SuggestionReviewDocument(
        review_version="0.1", suggestion_report_sha256="x", mapping_id="m", decisions=()
    )
    path.write_text(dumps_suggestion_review(review, format_name="yaml"), encoding="utf-8")
    assert load_suggestion_review(path) == review
