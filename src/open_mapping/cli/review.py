"""Noninteractive review command."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import (
    CliInputError,
    SchemaFormat,
    preflight_outputs,
    render_issues,
    require_choice,
    validate_input_files,
    write_outputs,
)
from open_mapping.matching.review import assemble_mapping, create_review_template
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.reports.json_report import render_review_json
from open_mapping.serialization.mappings import dumps_mapping
from open_mapping.serialization.reviews import dumps_suggestion_review, load_suggestion_review
from open_mapping.serialization.suggestions import load_suggestion_report


def review_command(
    suggestions: Path,
    decisions: Path | None,
    source: Path,
    target: Path,
    source_format: SchemaFormat,
    source_selector: str | None,
    target_format: SchemaFormat,
    target_selector: str | None,
    out: Path,
    review_report_out: Path | None,
    require_complete_review: bool,
    force: bool,
    interactive: bool = False,
) -> int:
    source_format = require_choice(source_format, SchemaFormat, "--source-format")
    target_format = require_choice(target_format, SchemaFormat, "--target-format")
    if decisions is None:
        raise CliInputError("--decisions is required")
    if interactive and not sys.stdin.isatty():
        raise CliInputError(
            "--interactive requires an attached TTY; edit the review YAML in automation"
        )
    validate_input_files(
        {
            "suggestions": suggestions,
            "decisions": None if interactive else decisions,
            "source schema": source,
            "target schema": target,
        }
    )
    preflight_outputs(
        tuple(path for path in (out, review_report_out) if path is not None), force=force
    )
    report = load_suggestion_report(suggestions)
    review = (
        _interactive_review(report, mapping_id=out.stem)
        if interactive
        else load_suggestion_review(decisions)
    )
    parsed_source = parse_openapi_selector(source_selector) if source_selector is not None else None
    parsed_target = parse_openapi_selector(target_selector) if target_selector is not None else None
    source_schema = load_schema(
        source,
        format_name=source_format.value,
        selector=parsed_source,
        schema_id=None,
    )
    target_schema = load_schema(
        target,
        format_name=target_format.value,
        selector=parsed_target,
        schema_id=None,
    )
    result = assemble_mapping(
        report,
        mapping_id=review.mapping_id,
        source_schema=source_schema,
        target_schema=target_schema,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=require_complete_review,
    )
    if result.mapping is None:
        if interactive:
            write_outputs(
                {decisions: dumps_suggestion_review(review, format_name="yaml")},
                force=force,
            )
        typer.echo(render_issues(result.issues), err=True)
        if any(
            issue.code.value
            in {
                "STALE_SUGGESTION_REPORT",
                "INVALID_REVIEW_DECISION",
                "REVIEW_CANDIDATE_NOT_FOUND",
                "REVIEW_TARGET_NOT_FOUND",
            }
            for issue in result.issues
        ):
            return 8
        return 3
    outputs = {out: dumps_mapping(result.mapping, format_name="yaml")}
    if interactive:
        outputs[decisions] = dumps_suggestion_review(review, format_name="yaml")
    if review_report_out is not None:
        outputs[review_report_out] = render_review_json(result)
    write_outputs(outputs, force=force)
    return 0


def _interactive_review(
    report: SuggestionReport,
    *,
    mapping_id: str,
) -> SuggestionReviewDocument:
    template = create_review_template(report, mapping_id=mapping_id, include_optional=True)
    decisions: list[SuggestionReviewDecision] = []
    for pending in template.decisions:
        typer.echo(f"Target: {pending.target_path}")
        typer.echo(
            f"Confidence: {pending.confidence_band.value if pending.confidence_band else 'none'}"
        )
        typer.echo(
            f"Disposition: {pending.disposition.value if pending.disposition else 'unknown'}"
        )
        typer.echo(f"Selected candidate: {pending.selected_source_path or '-'}")
        if pending.candidate_paths:
            typer.echo("Alternatives: " + ", ".join(pending.candidate_paths))
        if pending.context:
            typer.echo("Context: " + pending.context)
        suggestion = next(
            item for item in report.suggestions if item.target_path == pending.target_path
        )
        if suggestion.issues:
            typer.echo("Static issues:")
            typer.echo(render_issues(suggestion.issues))
        choice = typer.prompt("Action [a=accept, s=select, r=reject, d=defer]").strip().lower()
        if choice not in {"a", "s", "r", "d"}:
            raise CliInputError("interactive review action must be a, s, r, or d")
        source_path: str | None = None
        action = {
            "a": ReviewAction.ACCEPT_SELECTED,
            "s": ReviewAction.SELECT_CANDIDATE,
            "r": ReviewAction.REJECT,
            "d": ReviewAction.DEFER,
        }[choice]
        if action is ReviewAction.SELECT_CANDIDATE:
            source_path = typer.prompt("Source path").strip()
        reason = "Deferred for later review."
        if action is not ReviewAction.DEFER:
            reason = typer.prompt("Reason").strip()
            if not reason:
                raise CliInputError("accept, select, and reject require a reason")
        decisions.append(
            pending.model_copy(
                update={"action": action, "source_path": source_path, "reason": reason}
            )
        )
    return template.model_copy(update={"decisions": tuple(decisions)})
