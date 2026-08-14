"""End-to-end report-to-review mapping assembly contract."""

from __future__ import annotations

import json
from pathlib import Path

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.cli.common import SchemaFormat
from open_mapping.cli.review import review_command
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.serialization.reviews import dump_suggestion_review
from open_mapping.serialization.suggestions import dump_suggestion_report, suggestion_report_sha256


def schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "code": {"type": "string"}},
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "code": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


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
        source_schema_version="unversioned",
        target_schema_id="target",
        target_schema_version="unversioned",
        suggestions=items,
        summary=SuggestionSummary(total_targets=len(items), high=len(items), suggested=len(items)),
    )


def review_for(
    report_value: SuggestionReport, decisions: tuple[SuggestionReviewDecision, ...]
) -> SuggestionReviewDocument:
    return SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report_value),
        mapping_id="phase3",
        decisions=decisions,
    )


def test_review_document_only_assembles_only_explicitly_accepted_rules() -> None:
    source, target = schemas()
    report_value = report((suggested("/code"), suggested("/name")))
    decision = SuggestionReviewDecision(
        target_path="/name", action=ReviewAction.ACCEPT_SELECTED, reason="approved"
    )
    result = assemble_mapping(
        report_value,
        mapping_id="phase3",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review_for(report_value, (decision,)),
        require_complete_review=False,
    )
    assert result.mapping is not None
    assert tuple(rule.target for rule in result.mapping.rules) == ("/name",)
    assert result.unresolved_targets == ("/code",)


def test_review_command_returns_exit_code_8_for_an_unknown_review_target(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "target.json"
    source_schema = {
        "$id": "source",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    target_schema = {
        "$id": "target",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    source_path.write_text(json.dumps(source_schema), encoding="utf-8")
    target_path.write_text(json.dumps(target_schema), encoding="utf-8")
    report_value = report((suggested("/name"),))
    suggestions_path = tmp_path / "suggestions.json"
    decisions_path = tmp_path / "review.yaml"
    mapping_path = tmp_path / "mapping.yaml"
    dump_suggestion_report(report_value, suggestions_path)
    dump_suggestion_review(
        review_for(
            report_value,
            (
                SuggestionReviewDecision(
                    target_path="/unknown", action=ReviewAction.DEFER, reason="invalid target"
                ),
            ),
        ),
        decisions_path,
    )

    result = review_command(
        suggestions=suggestions_path,
        decisions=decisions_path,
        source=source_path,
        target=target_path,
        source_format=SchemaFormat.JSON_SCHEMA,
        source_selector=None,
        target_format=SchemaFormat.JSON_SCHEMA,
        target_selector=None,
        out=mapping_path,
        review_report_out=None,
        require_complete_review=False,
        force=False,
    )

    assert result == 8
    assert not mapping_path.exists()
