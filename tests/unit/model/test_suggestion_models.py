"""Model-boundary contract tests for complete suggestion reports."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
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


def test_suggestion_report_rejects_total_that_differs_from_suggestions() -> None:
    valid = report((suggested("/a"),))
    payload = valid.model_dump()
    payload["summary"] = SuggestionSummary(total_targets=2, high=2, suggested=2)
    with pytest.raises(ValidationError, match="total_targets"):
        valid.__class__(**payload)


@pytest.mark.parametrize(
    ("summary", "message"),
    [
        (SuggestionSummary(total_targets=1, high=0, suggested=1), "confidence"),
        (SuggestionSummary(total_targets=1, high=1, suggested=0), "disposition"),
    ],
)
def test_suggestion_report_rejects_forged_summary_counts(
    summary: SuggestionSummary, message: str
) -> None:
    valid = report((suggested("/a"),))
    with pytest.raises(ValidationError, match=message):
        valid.__class__(**valid.model_dump(exclude={"summary"}), summary=summary)


def test_suggestion_report_rejects_duplicate_target_paths() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        report((suggested("/a"), suggested("/a")))


def test_suggestion_report_rejects_noncanonical_target_order() -> None:
    with pytest.raises(ValidationError, match="ordered"):
        report((suggested("/b"), suggested("/a")))


def test_suggestion_report_accepts_exact_reconciled_summary() -> None:
    result = report((suggested("/a"), suggested("/b")))
    assert result.summary == SuggestionSummary(total_targets=2, high=2, suggested=2)
