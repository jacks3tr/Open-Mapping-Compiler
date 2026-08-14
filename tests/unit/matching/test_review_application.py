"""Review coverage, decision, and unresolved-target contracts."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.issues import IssueCode
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    ReviewResult,
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
from open_mapping.serialization.suggestions import suggestion_report_sha256


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


def _assemble(
    report_value: SuggestionReport,
    review: SuggestionReviewDocument,
    *,
    complete: bool = False,
) -> ReviewResult:
    source, target = schemas()
    return assemble_mapping(
        report_value,
        mapping_id="phase3",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=complete,
    )


def test_review_rejects_report_that_omits_a_target_mapping_unit() -> None:
    report_value = report((suggested("/name"),))
    result = _assemble(report_value, review_for(report_value, ()))
    assert result.mapping is None
    assert {issue.code for issue in result.issues} == {IssueCode.SUGGESTION_TARGET_MISSING}


def test_review_rejects_report_with_an_extra_target_mapping_unit() -> None:
    report_value = report((suggested("/name"), suggested("/unknown")))
    result = _assemble(report_value, review_for(report_value, ()))
    assert result.mapping is None
    assert {issue.code for issue in result.issues} == {IssueCode.SUGGESTION_TARGET_MISSING}


def test_review_rejects_duplicate_report_targets_before_applying_decisions() -> None:
    valid = report((suggested("/code"), suggested("/name")))
    forged = valid.model_copy(update={"suggestions": (suggested("/name"), suggested("/name"))})
    result = _assemble(forged, review_for(forged, ()))
    assert result.mapping is None
    assert {issue.code for issue in result.issues} == {
        IssueCode.SUGGESTION_TARGET_DUPLICATE,
        IssueCode.SUGGESTION_TARGET_MISSING,
    }


def test_review_rejects_unknown_decision_target_without_mapping() -> None:
    report_value = report((suggested("/code"), suggested("/name")))
    review = review_for(
        report_value,
        (
            SuggestionReviewDecision(
                target_path="/unknown", action=ReviewAction.DEFER, reason="bad"
            ),
        ),
    )
    result = _assemble(report_value, review)
    assert result.mapping is None
    assert result.applied_decisions == ()
    assert {issue.code for issue in result.issues} == {IssueCode.REVIEW_TARGET_NOT_FOUND}


def test_review_keeps_omitted_targets_unresolved_without_synthetic_decision() -> None:
    report_value = report((suggested("/code"), suggested("/name")))
    decision = SuggestionReviewDecision(
        target_path="/name", action=ReviewAction.ACCEPT_SELECTED, reason="approved"
    )
    result = _assemble(report_value, review_for(report_value, (decision,)))
    assert result.mapping is not None
    assert result.unresolved_targets == ("/code",)
    assert result.applied_decisions == (
        result.applied_decisions[0].model_copy(update={"target_path": "/name"}),
    )
    assert result.applied_decisions[0].action == ReviewAction.ACCEPT_SELECTED


def test_complete_review_requires_an_explicit_decision_for_every_nonmanual_target() -> None:
    report_value = report((suggested("/code"), suggested("/name")))
    decision = SuggestionReviewDecision(
        target_path="/name", action=ReviewAction.ACCEPT_SELECTED, reason="approved"
    )
    result = _assemble(report_value, review_for(report_value, (decision,)), complete=True)
    assert result.mapping is None
    assert result.unresolved_targets == ("/code",)
    assert {issue.code for issue in result.issues} == {IssueCode.INVALID_REVIEW_DECISION}


def test_stale_hash_prevents_any_review_application() -> None:
    report_value = report((suggested("/code"), suggested("/name")))
    review = review_for(report_value, ()).model_copy(update={"suggestion_report_sha256": "stale"})
    result = _assemble(report_value, review)
    assert result.mapping is None
    assert result.applied_decisions == ()
    assert {issue.code for issue in result.issues} == {IssueCode.STALE_SUGGESTION_REPORT}
