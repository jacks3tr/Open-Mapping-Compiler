"""Suggestion-report serialization and duplicate-key safety tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from yaml.constructor import ConstructorError

from open_mapping.adapters.openapi import load_openapi_schema, parse_openapi_selector
from open_mapping.benchmark.loader import load_benchmark_manifest
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.reports.json_report import render_suggestions_json
from open_mapping.serialization.hints import loads_mapping_hints
from open_mapping.serialization.mappings import loads_mapping
from open_mapping.serialization.reviews import load_suggestion_review
from open_mapping.serialization.suggestions import (
    dumps_suggestion_report,
    load_suggestion_report,
)


def suggested(target_path: str) -> MappingSuggestion:
    return MappingSuggestion(
        target_path=target_path,
        confidence_band=ConfidenceBand.HIGH,
        disposition=SuggestionDisposition.SUGGESTED,
        confidence_score=0.95,
        confidence_method="heuristic-v0.1",
        selected_source_path=target_path,
        expression={"op": "get", "path": target_path, "document": "input"},
    )


def report(items: tuple[MappingSuggestion, ...]) -> SuggestionReport:
    return SuggestionReport(
        report_version="0.1",
        source_schema_id="source",
        source_schema_version="0.1",
        target_schema_id="target",
        target_schema_version="0.1",
        suggestions=items,
        summary=SuggestionSummary(total_targets=len(items), high=len(items), suggested=len(items)),
    )


def test_suggestion_report_yaml_rejects_duplicate_keys_at_nested_level(tmp_path: Path) -> None:
    path = tmp_path / "suggestions.yaml"
    path.write_text(
        "report_version: '0.1'\n"
        "source_schema_id: source\n"
        "source_schema_version: '0.1'\n"
        "target_schema_id: target\n"
        "target_schema_version: '0.1'\n"
        "suggestions:\n"
        "  - target_path: /name\n"
        "    confidence_band: high\n"
        "    disposition: suggested\n"
        "    confidence_score: 0.95\n"
        "    confidence_method: heuristic-v0.1\n"
        "    selected_source_path: /name\n"
        "    expression: {op: get, path: /name}\n"
        "    reason: first\n"
        "    reason: second\n"
        "summary: {total_targets: 1, high: 1, suggested: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConstructorError, match="duplicate key"):
        load_suggestion_report(path)


def test_all_yaml_artifact_loaders_reject_nested_duplicate_keys(tmp_path: Path) -> None:
    mapping = "mapping_version: '0.1'\nid: m\nsource_schema: s\nsource_schema_version: '1'\ntarget_schema: t\ntarget_schema_version: '1'\nrules:\n  - target: /a\n    expression:\n      op: get\n      path: /a\n      path: /b\n"
    hints = "hints_version: '0.1'\nid: h\ndirect:\n  - target: /a\n    source: /a\n    source: /b\n    reason: duplicate\n"
    review = tmp_path / "review.yaml"
    review.write_text(
        "review_version: '0.1'\nsuggestion_report_sha256: x\nmapping_id: m\ndecisions:\n  - target_path: /a\n    action: defer\n    reason: one\n    reason: two\n",
        encoding="utf-8",
    )
    benchmark = tmp_path / "manifest.yaml"
    benchmark.write_text(
        "release_gates:\n  metric: {minimum: 0.5, minimum: 0.6}\n", encoding="utf-8"
    )
    openapi = tmp_path / "openapi.yaml"
    openapi.write_text(
        "openapi: 3.1.0\ncomponents:\n  schemas:\n    Item:\n      type: object\n      properties:\n        name: {type: string}\n        name: {type: string}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConstructorError, match="duplicate key"):
        loads_mapping(mapping, format_name="yaml")
    with pytest.raises(ConstructorError, match="duplicate key"):
        loads_mapping_hints(hints, format_name="yaml")
    with pytest.raises(ConstructorError, match="duplicate key"):
        load_suggestion_review(review)
    with pytest.raises(ConstructorError, match="duplicate key"):
        load_benchmark_manifest(benchmark)
    with pytest.raises(ConstructorError, match="duplicate key"):
        load_openapi_schema(
            openapi, selector=parse_openapi_selector("component:Item"), schema_id=None
        )


def test_suggestion_report_serialization_is_canonical_and_round_trips(tmp_path: Path) -> None:
    value = report((suggested("/name"),))
    path = tmp_path / "suggestions.yaml"
    path.write_text(dumps_suggestion_report(value, format_name="yaml"), encoding="utf-8")
    assert load_suggestion_report(path) == value
    assert dumps_suggestion_report(value, format_name="json") == dumps_suggestion_report(
        value, format_name="json"
    )


def test_suggestion_report_loader_accepts_and_verifies_rendered_report_hash(tmp_path: Path) -> None:
    value = report((suggested("/name"),))
    path = tmp_path / "suggestions.json"
    path.write_text(render_suggestions_json(value), encoding="utf-8")
    assert load_suggestion_report(path) == value

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["suggestion_report_sha256"] = "forged"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_suggestion_report(path)
