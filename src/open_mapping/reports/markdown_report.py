"""Markdown report rendering."""

from __future__ import annotations

from open_mapping.model.reviews import ReviewResult
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import VerificationReport
from open_mapping.reports.text_report import _reconcile
from open_mapping.serialization.suggestions import suggestion_report_sha256


def _md(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("\n", " ")


def render_verification_markdown(report: VerificationReport) -> str:
    lines = [
        "# Verification Report",
        f"Mapping: `{_md(report.mapping_id)}`",
        f"Static valid: {report.static.valid}",
    ]
    if report.static.issues:
        lines.append("## Issues")
        for issue in report.static.issues:
            lines.append(f"- `{issue.code.value}`: {_md(issue.message)}")
    lines.append(f"## Samples ({len(report.samples)})")
    lines.append("| Sample | Valid | Issues |")
    lines.append("| --- | --- | --- |")
    for sample in report.samples:
        lines.append(f"| {_md(sample.sample_id)} | {sample.valid} | {len(sample.issues)} |")
    return "\n".join(lines) + "\n"


def render_suggestions_markdown(report: SuggestionReport) -> str:
    _reconcile(report)
    model_assisted = report.model_run_disclosure is not None or any(
        suggestion.origin.value == "model" for suggestion in report.suggestions
    )
    lines = [
        "# Suggestion Report",
        f"Source: `{_md(report.source_schema_id)}` version `{_md(report.source_schema_version)}`",
        f"Target: `{_md(report.target_schema_id)}` version `{_md(report.target_schema_version)}`",
        f"Suggestion report hash: `{suggestion_report_sha256(report)}`",
        "## Summary",
        "| Count | Value |",
        "| --- | --- |",
        f"| Total targets | {report.summary.total_targets} |",
        f"| High | {report.summary.high} |",
        f"| Medium | {report.summary.medium} |",
        f"| Low | {report.summary.low} |",
        f"| None | {report.summary.none} |",
        f"| Suggested | {report.summary.suggested} |",
        f"| Review required | {report.summary.review_required} |",
        f"| Ambiguous | {report.summary.ambiguous} |",
        f"| No match | {report.summary.no_match} |",
        f"| Manual | {report.summary.manual} |",
        "## Outcomes",
    ]
    if not model_assisted:
        lines.extend(
            (
                "| Target | Band | Disposition | Confidence score | Selected source |",
                "| --- | --- | --- | --- | --- |",
            )
        )
    else:
        lines.extend(
            (
                "| Target | Origin | Band | Disposition | Confidence score | Selected sources | Proposal reason | Static issues |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            )
        )
    for suggestion in report.suggestions:
        score = "" if suggestion.confidence_score is None else str(suggestion.confidence_score)
        if not model_assisted:
            selected = _md(suggestion.selected_source_path or "")
            lines.append(
                f"| `{_md(suggestion.target_path)}` | {suggestion.confidence_band.value} | {suggestion.disposition.value} | {score} | {selected} |"
            )
        else:
            selected_paths = suggestion.selected_source_paths or (
                (suggestion.selected_source_path,) if suggestion.selected_source_path else ()
            )
            selected = _md(", ".join(selected_paths))
            static_issues = _md(
                "; ".join(
                    f"{issue.severity.value}: {issue.code.value}: {issue.message}"
                    for issue in suggestion.issues
                )
            )
            has_model_proposal = suggestion.origin.value == "model" or any(
                evidence.kind.value == "model_rerank"
                and "model proposal" in evidence.detail.lower()
                for evidence in suggestion.evidence
            )
            proposal_reason = suggestion.reason if has_model_proposal else ""
            lines.append(
                f"| `{_md(suggestion.target_path)}` | {suggestion.origin.value} | {suggestion.confidence_band.value} | {suggestion.disposition.value} | {score} | {selected} | {_md(proposal_reason)} | {static_issues} |"
            )
    if report.model_run_disclosure is not None:
        lines.extend(
            (
                "## Model Run",
                f"Model alias: `{_md(report.model_run_disclosure.model_alias)}`",
                f"Prompt version: `{_md(report.model_run_disclosure.prompt_version)}`",
            )
        )
    if model_assisted and report.issues:
        lines.append("## Model Issues")
        for issue in report.issues:
            lines.append(f"- `{issue.severity.value}` `{issue.code.value}`: {_md(issue.message)}")
    return "\n".join(lines) + "\n"


def render_review_markdown(result: ReviewResult) -> str:
    lines = [
        "# Review Result",
        f"Suggestion report hash: `{result.suggestion_report_sha256}`",
        f"Mapping ID: `{_md(result.mapping_id)}`",
        f"Mapping assembled: {result.mapping is not None}",
        "## Decisions",
        "| Target | Action | Accepted | Source |",
        "| --- | --- | --- | --- |",
    ]
    for decision in result.applied_decisions:
        lines.append(
            f"| `{_md(decision.target_path)}` | {decision.action.value} | {decision.accepted} | {_md(decision.source_path or '')} |"
        )
    if result.unresolved_targets:
        lines.append("## Unresolved")
        for target in result.unresolved_targets:
            lines.append(f"- `{_md(target)}`")
    if result.issues:
        lines.append("## Issues")
        for issue in result.issues:
            lines.append(f"- `{issue.code.value}`: {_md(issue.message)}")
    return "\n".join(lines) + "\n"
