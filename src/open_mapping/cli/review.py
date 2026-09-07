"""Noninteractive review command."""

from __future__ import annotations

import json
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
from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.matching.review import assemble_mapping, create_review_template
from open_mapping.model.drafts import BuildDraft
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
from open_mapping.verification.dynamic import VerificationSample


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
    template: SuggestionReviewDocument | None = None,
    draft: BuildDraft | None = None,
    show_sample_values: bool = False,
) -> SuggestionReviewDocument:
    template = template or create_review_template(
        report,
        mapping_id=mapping_id,
        include_optional=True,
        include_auto_accepted=True,
    )
    by_target = {suggestion.target_path: suggestion for suggestion in report.suggestions}
    typer.echo(
        "Review business meaning, not just structural validity. Nothing is approved automatically here."
    )
    decisions: list[SuggestionReviewDecision] = []
    for pending in template.decisions:
        typer.echo(f"Target: {_display(pending.target_path)}")
        typer.echo(
            f"Confidence: {pending.confidence_band.value if pending.confidence_band else 'none'}"
        )
        typer.echo(
            f"Disposition: {pending.disposition.value if pending.disposition else 'unknown'}"
        )
        typer.echo(f"Selected candidate: {_display(pending.selected_source_path or '-')}")
        if pending.candidate_paths:
            typer.echo(
                "Alternatives: " + ", ".join(_display(path) for path in pending.candidate_paths)
            )
        if pending.context:
            typer.echo("Context: " + _display(pending.context))
        suggestion = by_target[pending.target_path]
        if suggestion.expression is not None:
            typer.echo("Expression: " + suggestion.expression.model_dump_json())
            if draft is not None and draft.content.samples:
                if show_sample_values:
                    sample = VerificationSample.model_validate(draft.content.samples[0])
                    try:
                        preview = evaluate_expression(
                            suggestion.expression,
                            EvaluationContext(input_document=sample.input, output_document={}),
                            draft.content.limits,
                        )
                    except OpenMappingError as error:
                        typer.echo("Sample preview failed: " + render_issues(error.issues))
                    else:
                        rendered = json.dumps(preview, ensure_ascii=False)
                        typer.echo(
                            "Sample preview: "
                            + rendered[:500]
                            + ("..." if len(rendered) > 500 else "")
                        )
                else:
                    typer.echo(
                        "Sample preview withheld; use --show-sample-values to display saved sample data."
                    )
        if suggestion.issues:
            typer.echo("Static issues:")
            typer.echo(render_issues(suggestion.issues))
        while True:
            choice = typer.prompt("Action [a=accept, s=select, r=reject, d=defer]").strip().lower()
            if choice not in {"a", "s", "r", "d"}:
                typer.echo("Choose a, s, r, or d.")
            elif choice == "a" and suggestion.expression is None:
                typer.echo("No selected expression exists; select a candidate or defer.")
            elif choice == "s" and not pending.candidate_paths:
                typer.echo("No candidates exist; defer and add a business hint before rebuilding.")
            else:
                break
        source_path: str | None = None
        action = {
            "a": ReviewAction.ACCEPT_SELECTED,
            "s": ReviewAction.SELECT_CANDIDATE,
            "r": ReviewAction.REJECT,
            "d": ReviewAction.DEFER,
        }[choice]
        if action is ReviewAction.SELECT_CANDIDATE:
            while source_path not in pending.candidate_paths:
                source_path = typer.prompt("Source path from the alternatives above").strip()
                if source_path not in pending.candidate_paths:
                    typer.echo("Choose an existing candidate path.")
        reason = "Deferred for later review."
        if action is not ReviewAction.DEFER:
            reason = ""
            while not reason:
                reason = typer.prompt("Reason").strip()
                if not reason:
                    typer.echo("A decision requires a business reason.")
        decisions.append(
            pending.model_copy(
                update={"action": action, "source_path": source_path, "reason": reason}
            )
        )
    return template.model_copy(update={"decisions": tuple(decisions)})


def _display(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def review_draft_command(
    draft_path: Path,
    *,
    out: Path | None,
    interactive: bool,
    all_targets: bool,
    show_sample_values: bool,
    force: bool,
) -> int:
    draft = BuildDraft.load(draft_path)
    output = out or draft_path.parent / "review.yaml"
    if output.resolve() == draft_path.resolve():
        raise CliInputError("review output must not overwrite the draft")
    preflight_outputs((output,), force=force)
    content = draft.content
    complete = all_targets or content.require_complete_review
    template = create_review_template(
        content.suggestion_report,
        mapping_id=content.mapping_id,
        include_optional=complete,
        include_auto_accepted=complete,
        target_schema=content.target_schema,
    )
    review = (
        _interactive_review(
            content.suggestion_report,
            mapping_id=content.mapping_id,
            template=template,
            draft=draft,
            show_sample_values=show_sample_values,
        )
        if interactive
        else template
    )
    write_outputs({output: dumps_suggestion_review(review, format_name="yaml")}, force=force)
    typer.echo(f"Saved review: {output}")
    return 0
