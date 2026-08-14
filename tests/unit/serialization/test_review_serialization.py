"""Review document model and deterministic serialization tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from open_mapping.model.reviews import (
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.serialization.reviews import dumps_suggestion_review, load_suggestion_review
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


def review_for(
    report_value: SuggestionReport, decisions: tuple[SuggestionReviewDecision, ...]
) -> SuggestionReviewDocument:
    return SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report_value),
        mapping_id="phase3",
        decisions=decisions,
    )


def test_select_candidate_requires_a_source_path() -> None:
    with pytest.raises(ValidationError, match="source_path"):
        SuggestionReviewDecision(
            target_path="/name", action=ReviewAction.SELECT_CANDIDATE, reason="choose evidence"
        )


@pytest.mark.parametrize(
    "action", [ReviewAction.ACCEPT_SELECTED, ReviewAction.REJECT, ReviewAction.DEFER]
)
def test_non_selection_decisions_reject_source_path(action: ReviewAction) -> None:
    with pytest.raises(ValidationError, match="source_path"):
        SuggestionReviewDecision(
            target_path="/name", action=action, source_path="/name", reason="not applicable"
        )


def test_review_serialization_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    value = report((suggested("/name"),))
    review = review_for(
        value,
        (
            SuggestionReviewDecision(
                target_path="/z", action=ReviewAction.DEFER, reason="defer later"
            ),
            SuggestionReviewDecision(
                target_path="/a", action=ReviewAction.DEFER, reason="defer first"
            ),
        ),
    )
    path = tmp_path / "review.yaml"
    rendered = dumps_suggestion_review(review, format_name="yaml")
    path.write_text(rendered, encoding="utf-8")
    assert tuple(decision.target_path for decision in load_suggestion_review(path).decisions) == (
        "/a",
        "/z",
    )
    assert dumps_suggestion_review(review, format_name="yaml") == rendered
