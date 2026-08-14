"""Report rendering tests."""

from __future__ import annotations

from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.model.verification import (
    SampleVerificationResult,
    StaticVerificationResult,
    VerificationReport,
)
from open_mapping.reports.json_report import render_suggestions_json, render_verification_json
from open_mapping.reports.markdown_report import render_suggestions_markdown
from open_mapping.reports.text_report import render_suggestions_text


def _suggestion() -> MappingSuggestion:
    return MappingSuggestion(
        target_path="/x",
        confidence_band=ConfidenceBand.HIGH,
        disposition=SuggestionDisposition.SUGGESTED,
        confidence_score=0.95,
        confidence_method="heuristic-v0.1",
        selected_source_path="/a",
        expression={"op": "get", "path": "/a"},
        reason="test",
    )


def test_suggestion_reports() -> None:
    report = SuggestionReport(
        report_version="0.1",
        source_schema_id="s",
        source_schema_version="1",
        target_schema_id="t",
        target_schema_version="1",
        suggestions=(_suggestion(),),
        summary=SuggestionSummary(total_targets=1, high=1, suggested=1),
    )
    assert "/x" in render_suggestions_text(report)
    assert "/x" in render_suggestions_markdown(report)
    assert render_suggestions_json(report).endswith("\n")


def test_verification_report_render() -> None:
    report = VerificationReport(
        mapping_id="m",
        static=StaticVerificationResult(issues=(), mapped_target_paths=(), mapping_sha256="x"),
        samples=(SampleVerificationResult(sample_id="a", output=None, issues=()),),
    )
    assert "m" in render_verification_json(report)
