"""Text report rendering."""

from __future__ import annotations

from open_mapping.model.reviews import ReviewResult
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import VerificationReport
from open_mapping.serialization.suggestions import suggestion_report_sha256


def _reconcile(report: SuggestionReport) -> None:
    summary = report.summary
    if (
        summary.total_targets != len(report.suggestions)
        or summary.high + summary.medium + summary.low + summary.none != summary.total_targets
        or summary.suggested
        + summary.review_required
        + summary.ambiguous
        + summary.no_match
        + summary.manual
        != summary.total_targets
    ):
        raise ValueError("suggestion summary counts do not reconcile")


def render_verification_text(report: VerificationReport) -> str:
    lines = [f"Mapping: {report.mapping_id}", f"Static valid: {report.static.valid}"]
    for issue in report.static.issues:
        lines.append(f"{issue.severity.value}: {issue.code.value}: {issue.message}")
    lines.append(f"Samples verified: {len(report.samples)}")
    for sample in report.samples:
        lines.append(f"{sample.sample_id}: valid={sample.valid}, issues={len(sample.issues)}")
    return "\n".join(lines) + "\n"


def render_suggestions_text(report: SuggestionReport) -> str:
    _reconcile(report)
    model_assisted = report.model_run_disclosure is not None or any(
        suggestion.origin.value == "model" for suggestion in report.suggestions
    )
    lines = [
        f"Source: {report.source_schema_id} ({report.source_schema_version})",
        f"Target: {report.target_schema_id} ({report.target_schema_version})",
        f"Suggestion report hash: {suggestion_report_sha256(report)}",
        "Summary",
        f"Total targets: {report.summary.total_targets}",
        f"High: {report.summary.high}",
        f"Medium: {report.summary.medium}",
        f"Low: {report.summary.low}",
        f"None: {report.summary.none}",
        f"Suggested: {report.summary.suggested}",
        f"Review required: {report.summary.review_required}",
        f"Ambiguous: {report.summary.ambiguous}",
        f"No match: {report.summary.no_match}",
        f"Manual: {report.summary.manual}",
        "",
    ]
    for suggestion in report.suggestions:
        lines.append(f"Target: {suggestion.target_path}")
        lines.append(f"Confidence band: {suggestion.confidence_band.value}")
        lines.append(f"Disposition: {suggestion.disposition.value}")
        if model_assisted:
            lines.append(f"Origin: {suggestion.origin.value}")
        if suggestion.confidence_score is not None:
            lines.append(f"Confidence score: {suggestion.confidence_score}")
        if suggestion.confidence_method:
            lines.append(f"Confidence method: {suggestion.confidence_method}")
        if suggestion.selected_source_path is not None:
            lines.append(f"Selected source: {suggestion.selected_source_path}")
        if model_assisted and suggestion.selected_source_paths:
            lines.append("Selected sources: " + ", ".join(suggestion.selected_source_paths))
        if suggestion.reason:
            has_model_proposal = any(
                evidence.kind.value == "model_rerank"
                and "model proposal" in evidence.detail.lower()
                for evidence in suggestion.evidence
            )
            label = (
                "Proposal reason"
                if model_assisted and (suggestion.origin.value == "model" or has_model_proposal)
                else "Reason"
            )
            lines.append(f"{label}: {suggestion.reason}")
        if model_assisted:
            for issue in suggestion.issues:
                lines.append(
                    f"Static issue: {issue.severity.value}: {issue.code.value}: {issue.message}"
                )
        lines.append("")
    if report.model_run_disclosure is not None:
        lines.extend(
            (
                "Model run",
                f"Model alias: {report.model_run_disclosure.model_alias}",
                f"Prompt version: {report.model_run_disclosure.prompt_version}",
            )
        )
    if model_assisted and report.issues:
        lines.append("Model issues")
        for issue in report.issues:
            lines.append(f"{issue.severity.value}: {issue.code.value}: {issue.message}")
    return "\n".join(lines)


def render_review_text(result: ReviewResult) -> str:
    lines = [
        f"Suggestion report hash: {result.suggestion_report_sha256}",
        f"Mapping ID: {result.mapping_id}",
        f"Mapping assembled: {result.mapping is not None}",
    ]
    for decision in result.applied_decisions:
        lines.append(
            f"{decision.target_path}: {decision.action.value} accepted={decision.accepted} source={decision.source_path or '-'}"
        )
    if result.unresolved_targets:
        lines.append("Unresolved targets: " + ", ".join(result.unresolved_targets))
    for issue in result.issues:
        lines.append(f"{issue.severity.value}: {issue.code.value}: {issue.message}")
    return "\n".join(lines) + "\n"
