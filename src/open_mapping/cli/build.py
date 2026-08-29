"""One-command mapping build workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from open_mapping.cli.common import ReportFormat, preflight_outputs, render_issues, write_outputs
from open_mapping.compiler import Compiler
from open_mapping.model.builds import BuildStatus
from open_mapping.model.suggestions import ConfidenceBand, SuggestionDisposition, SuggestionOrigin
from open_mapping.reports.json_report import render_suggestions_json, render_verification_json
from open_mapping.reports.markdown_report import render_suggestions_markdown
from open_mapping.reports.text_report import render_suggestions_text
from open_mapping.serialization.bundles import dumps_bundle
from open_mapping.serialization.reviews import dumps_suggestion_review


def build_command(
    source: Path,
    target: Path,
    *,
    source_format: Literal["json-schema", "openapi", "json-data"],
    source_selector: str | None,
    target_format: Literal["json-schema", "openapi"],
    target_selector: str | None,
    samples: Path | None,
    hints: Path | None,
    review: Path | None,
    mapping_id: str | None,
    model: str | None,
    models_config: Path | None,
    instruction: str | None,
    allow_raw_samples: bool,
    require_model: bool,
    work_dir: Path | None,
    out: Path | None,
    require_samples: bool,
    require_complete_review: bool,
    force: bool,
    report_format: ReportFormat,
) -> int:
    resolved_id = mapping_id or f"{source.stem}-to-{target.stem}"
    resolved_out = out or Path(f"{resolved_id}.omc")
    resolved_work_dir = work_dir or Path(".open-mapping") / resolved_id
    suggestions_path = resolved_work_dir / "suggestions.json"
    verification_path = resolved_work_dir / "verification.json"
    review_path = Path(f"{resolved_id}.review.yaml")
    potential_outputs = [resolved_out]
    if review is None:
        potential_outputs.append(review_path)
    preflight_outputs(tuple(potential_outputs), force=force)
    source_format_arg = (
        "" if source_format == "json-schema" else f" --source-format {source_format}"
    )
    source_selector_arg = "" if source_selector is None else f" --source-selector {source_selector}"
    target_format_arg = (
        "" if target_format == "json-schema" else f" --target-format {target_format}"
    )
    target_selector_arg = "" if target_selector is None else f" --target-selector {target_selector}"

    result = Compiler(
        model=model,
        models_config=models_config,
        allow_raw_samples=allow_raw_samples,
        require_model=require_model,
    ).build(
        source=source,
        target=target,
        source_format=source_format,
        source_selector=source_selector,
        target_format=target_format,
        target_selector=target_selector,
        samples=samples,
        hints=hints,
        review=review,
        mapping_id=resolved_id,
        instruction=instruction,
        require_samples=require_samples,
        require_complete_review=require_complete_review,
    )
    renderer = {
        ReportFormat.TEXT: render_suggestions_text,
        ReportFormat.JSON: render_suggestions_json,
        ReportFormat.MARKDOWN: render_suggestions_markdown,
    }[report_format]
    if result.status is BuildStatus.NEEDS_REVIEW:
        assert result.review_document is not None
        write_outputs(
            {suggestions_path: render_suggestions_json(result.suggestion_report)},
            force=True,
        )
        write_outputs(
            {review_path: dumps_suggestion_review(result.review_document, format_name="yaml")},
            force=force,
        )
        summary = result.suggestion_report.summary
        typer.echo(
            "\n".join(
                (
                    "NEEDS_REVIEW",
                    "",
                    f"{summary.suggested + summary.manual} targets mapped",
                    f"{summary.review_required} review required",
                    f"{summary.ambiguous} ambiguous",
                    f"{summary.no_match} no match",
                    "",
                    "Created:",
                    f"  {suggestions_path}",
                    f"  {review_path}",
                    "",
                    "Rerun:",
                    (
                        f"  open-mapping build {source} {target}{source_format_arg}"
                        f"{source_selector_arg}{target_format_arg}{target_selector_arg}"
                        f" --review {review_path} --out {resolved_out}"
                    ),
                )
            )
        )
        return 8

    bundle = result.require_bundle()
    audit_outputs = {suggestions_path: render_suggestions_json(result.suggestion_report)}
    if result.verification_report is not None:
        audit_outputs[verification_path] = render_verification_json(result.verification_report)
    write_outputs(audit_outputs, force=True)
    write_outputs({resolved_out: dumps_bundle(bundle)}, force=force)
    sample_count = bundle.verification.sample_count
    mapped_targets = {rule.target for rule in bundle.mapping.rules}
    deterministic_high = sum(
        1
        for suggestion in result.suggestion_report.suggestions
        if suggestion.target_path in mapped_targets
        and suggestion.origin is SuggestionOrigin.DETERMINISTIC
        and suggestion.confidence_band is ConfidenceBand.HIGH
        and suggestion.disposition is SuggestionDisposition.SUGGESTED
    )
    manual = sum(
        1
        for suggestion in result.suggestion_report.suggestions
        if suggestion.target_path in mapped_targets
        and suggestion.disposition is SuggestionDisposition.MANUAL
    )
    typer.echo("READY" if sample_count else "READY — static verification only")
    typer.echo(
        "\n".join(
            (
                "",
                f"{len(bundle.mapping.rules)} targets",
                f"{deterministic_high} deterministic high-confidence",
                f"{manual} manual business rules",
                "0 unresolved required targets",
                *((f"{sample_count} samples passed",) if sample_count else ()),
                "",
                f"Created: {resolved_out}",
            )
        )
    )
    if result.issues:
        typer.echo(render_issues(result.issues), err=True)
    if report_format is not ReportFormat.TEXT:
        typer.echo(renderer(result.suggestion_report), nl=False)
    return 0


__all__ = ["build_command"]
