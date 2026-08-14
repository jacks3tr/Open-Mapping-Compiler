"""Golden deterministic rendering checks for Phase 3 report artifacts."""

from __future__ import annotations

from pathlib import Path

from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.reports.markdown_report import render_suggestions_markdown
from open_mapping.reports.text_report import render_suggestions_text

_FIXTURES = Path(__file__).parent


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


def test_suggestion_text_report_matches_golden_fixture() -> None:
    value = report((suggested("/name"),))
    assert render_suggestions_text(value) == (_FIXTURES / "suggestions.txt").read_text(
        encoding="utf-8"
    )


def test_suggestion_markdown_report_matches_golden_fixture() -> None:
    value = report((suggested("/name"),))
    assert render_suggestions_markdown(value) == (_FIXTURES / "suggestions.md").read_text(
        encoding="utf-8"
    )
