"""Human-readable text report contracts."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.model.expressions import Expression
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionOrigin,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.reports.text_report import render_suggestions_text
from open_mapping.serialization.suggestions import suggestion_report_sha256


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


def test_text_report_renders_each_target_once_with_exact_summary() -> None:
    value = report((suggested("/code"), suggested("/name")))
    rendered = render_suggestions_text(value)
    assert rendered.count("Target: /code") == 1
    assert rendered.count("Target: /name") == 1
    assert "Total targets: 2" in rendered
    assert "Confidence score: 0.95" in rendered
    assert f"Suggestion report hash: {suggestion_report_sha256(value)}" in rendered
    assert "probability" not in rendered.lower()


def test_text_report_discloses_model_draft_details() -> None:
    model = suggested("/name").model_copy(
        update={
            "origin": SuggestionOrigin.MODEL,
            "selected_source_path": None,
            "selected_source_paths": ("/first", "/last"),
            "expression": TypeAdapter(Expression).validate_python(
                {
                    "op": "concat",
                    "operands": [
                        {"op": "get", "path": "/first", "document": "input"},
                        {"op": "get", "path": "/last", "document": "input"},
                    ],
                    "separator": " ",
                }
            ),
            "reason": "Combine the names.",
        }
    )
    rendered = render_suggestions_text(report((model,)))
    assert "Origin: model" in rendered
    assert "Selected sources: /first, /last" in rendered
    assert "Proposal reason: Combine the names." in rendered
