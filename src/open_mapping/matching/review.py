"""Suggestion review application and mapping assembly."""

from __future__ import annotations

from collections import Counter

from open_mapping.errors import OpenMappingError
from open_mapping.matching.candidates import validate_suggestion_coverage
from open_mapping.model.expressions import GetExpression
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.mappings import MappingDocument, MappingRule
from open_mapping.model.reviews import (
    AppliedReviewDecision,
    AssemblyPolicy,
    ReviewAction,
    ReviewResult,
    SuggestionReviewDocument,
)
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import ConfidenceBand, SuggestionDisposition, SuggestionReport
from open_mapping.pointers import split_pointer
from open_mapping.serialization.suggestions import suggestion_report_sha256
from open_mapping.verification.static import require_static_valid, verify_proposed_rule


def _issue(
    code: IssueCode, message: str, correction: str, *, target_path: str | None = None
) -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component="matching.review",
        message=message,
        correction=correction,
        target_path=target_path,
    )


def assemble_mapping(
    report: SuggestionReport,
    *,
    mapping_id: str,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    policy: AssemblyPolicy,
    review: SuggestionReviewDocument | None,
    require_complete_review: bool,
) -> ReviewResult:
    report_hash = suggestion_report_sha256(report)
    coverage_issues = validate_suggestion_coverage(report, target_schema)
    if coverage_issues:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=(),
            issues=coverage_issues,
        )
    if review is not None and review.suggestion_report_sha256 != report_hash:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=(),
            issues=(
                _issue(
                    IssueCode.STALE_SUGGESTION_REPORT,
                    "review is bound to a different suggestion report",
                    "Regenerate the review against the current suggestion report.",
                ),
            ),
        )
    if policy == AssemblyPolicy.REVIEW_DOCUMENT_ONLY and review is None:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=(),
            issues=(
                _issue(
                    IssueCode.INVALID_REVIEW_DECISION,
                    "REVIEW_DOCUMENT_ONLY requires a review document",
                    "Pass --decisions FILE.",
                ),
            ),
        )
    decision_list = tuple(review.decisions) if review is not None else ()
    target_counts = Counter(decision.target_path for decision in decision_list)
    duplicate_issues: list[Issue] = []
    for target, count in target_counts.items():
        if count > 1:
            duplicate_issues.append(
                _issue(
                    IssueCode.INVALID_REVIEW_DECISION,
                    f"duplicate review decision for {target!r}",
                    "Provide one decision per target.",
                    target_path=target,
                )
            )
    if duplicate_issues:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=(),
            issues=sort_issues(duplicate_issues),
        )
    decisions_by_target = {decision.target_path: decision for decision in decision_list}
    known_targets = {suggestion.target_path for suggestion in report.suggestions}
    unknown_targets = sorted(set(decisions_by_target).difference(known_targets), key=split_pointer)
    if unknown_targets:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=(),
            issues=tuple(
                _issue(
                    IssueCode.REVIEW_TARGET_NOT_FOUND,
                    f"review decision target {target!r} is not present in the suggestion report",
                    "Use a target path present in the suggestion report.",
                    target_path=target,
                )
                for target in unknown_targets
            ),
        )
    manual_targets = {
        suggestion.target_path
        for suggestion in report.suggestions
        if suggestion.disposition == SuggestionDisposition.MANUAL
    }
    manual_decisions = sorted(manual_targets.intersection(decisions_by_target), key=split_pointer)
    if manual_decisions:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=(),
            issues=tuple(
                _issue(
                    IssueCode.INVALID_REVIEW_DECISION,
                    f"manual hint target {target!r} cannot be overridden by review",
                    "Regenerate suggestions with a revised mapping hint.",
                    target_path=target,
                )
                for target in manual_decisions
            ),
        )
    unresolved = tuple(
        sorted(
            (
                suggestion.target_path
                for suggestion in report.suggestions
                if suggestion.disposition != SuggestionDisposition.MANUAL
                and suggestion.target_path not in decisions_by_target
            ),
            key=split_pointer,
        )
    )
    if require_complete_review and unresolved:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=(),
            unresolved_targets=unresolved,
            issues=(
                _issue(
                    IssueCode.INVALID_REVIEW_DECISION,
                    "review is incomplete",
                    "Add an explicit decision for every non-manual target.",
                    target_path=unresolved[0],
                ),
            ),
        )

    issues: list[Issue] = []
    applied: list[AppliedReviewDecision] = []
    rules: list[MappingRule] = []
    for suggestion in report.suggestions:
        if (
            suggestion.disposition == SuggestionDisposition.MANUAL
            and suggestion.expression is not None
        ):
            rules.append(
                MappingRule(
                    target=suggestion.target_path,
                    expression=suggestion.expression,
                    confidence=0.0,
                    confidence_method="business-instruction-v0.1",
                    evidence=suggestion.evidence,
                )
            )
            continue
        decision = decisions_by_target.get(suggestion.target_path)
        included = False
        rule: MappingRule | None = None
        applied_action: ReviewAction | None = None
        applied_source: str | None = None
        decision_issues: tuple[Issue, ...] = ()
        if decision is None:
            if (
                policy == AssemblyPolicy.HIGH_AND_MANUAL
                and suggestion.disposition == SuggestionDisposition.SUGGESTED
                and suggestion.confidence_band == ConfidenceBand.HIGH
                and suggestion.expression is not None
            ):
                included = True
        else:
            applied_action = decision.action
            if decision.action in {ReviewAction.REJECT, ReviewAction.DEFER}:
                included = False
            elif decision.action == ReviewAction.ACCEPT_SELECTED:
                if (
                    suggestion.disposition
                    not in {SuggestionDisposition.SUGGESTED, SuggestionDisposition.REVIEW_REQUIRED}
                    or suggestion.expression is None
                ):
                    decision_issues = (
                        _issue(
                            IssueCode.INVALID_REVIEW_DECISION,
                            f"cannot accept selected outcome for {suggestion.target_path!r}",
                            "Only suggested or review-required outcomes can be accepted.",
                            target_path=suggestion.target_path,
                        ),
                    )
                    issues.extend(decision_issues)
                else:
                    included = True
                    applied_source = suggestion.selected_source_path
            elif decision.action == ReviewAction.SELECT_CANDIDATE:
                selected = decision.source_path
                candidate_paths = {candidate.source_path for candidate in suggestion.candidates}
                if selected is None or selected not in candidate_paths:
                    decision_issues = (
                        _issue(
                            IssueCode.REVIEW_CANDIDATE_NOT_FOUND,
                            f"candidate {selected!r} is not present for {suggestion.target_path!r}",
                            "Select a candidate from the suggestion report.",
                            target_path=suggestion.target_path,
                        ),
                    )
                    issues.extend(decision_issues)
                else:
                    rule = MappingRule(
                        target=suggestion.target_path,
                        expression=GetExpression(op="get", path=selected, document="input"),
                        confidence=0.0,
                        confidence_method="review-v0.1",
                    )
                    rule_issues = verify_proposed_rule(
                        rule, source_schema=source_schema, target_schema=target_schema
                    )
                    if any(issue.severity == Severity.ERROR for issue in rule_issues):
                        decision_issues = rule_issues
                        issues.extend(rule_issues)
                    else:
                        included = True
                        applied_source = selected
            else:
                decision_issues = (
                    _issue(
                        IssueCode.INVALID_REVIEW_DECISION,
                        f"unsupported review action {decision.action.value!r}",
                        "Use accept_selected, select_candidate, reject, or defer.",
                        target_path=suggestion.target_path,
                    ),
                )
                issues.extend(decision_issues)
        if included and rule is not None:
            rules.append(rule)
        elif included and suggestion.expression is not None:
            rules.append(
                MappingRule(
                    target=suggestion.target_path,
                    expression=suggestion.expression,
                    confidence=suggestion.confidence_score
                    if suggestion.confidence_score is not None
                    else 0.0,
                    confidence_method=suggestion.confidence_method,
                    evidence=suggestion.evidence,
                )
            )
        if decision is not None and applied_action is not None:
            applied.append(
                AppliedReviewDecision(
                    target_path=suggestion.target_path,
                    action=applied_action,
                    accepted=included,
                    source_path=applied_source,
                    issues=decision_issues,
                )
            )
    if issues:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=tuple(applied),
            unresolved_targets=unresolved,
            issues=sort_issues(issues),
        )
    mapping = MappingDocument(
        mapping_version="0.1",
        id=mapping_id,
        source_schema=source_schema.schema_id,
        source_schema_version=source_schema.schema_version,
        target_schema=target_schema.schema_id,
        target_schema_version=target_schema.schema_version,
        rules=tuple(rules),
        invariants=(),
    )
    try:
        require_static_valid(mapping, source_schema=source_schema, target_schema=target_schema)
    except OpenMappingError as exc:
        return ReviewResult(
            suggestion_report_sha256=report_hash,
            mapping_id=mapping_id,
            mapping=None,
            applied_decisions=tuple(applied),
            unresolved_targets=unresolved,
            issues=exc.issues,
        )
    return ReviewResult(
        suggestion_report_sha256=report_hash,
        mapping_id=mapping_id,
        mapping=mapping,
        applied_decisions=tuple(applied),
        unresolved_targets=unresolved,
        issues=(),
    )
