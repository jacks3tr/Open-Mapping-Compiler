"""Noninteractive review command."""

from __future__ import annotations

from pathlib import Path

import typer

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import (
    SchemaFormat,
    preflight_outputs,
    render_issues,
    require_choice,
    validate_input_files,
    write_outputs,
)
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.reviews import AssemblyPolicy
from open_mapping.reports.json_report import render_review_json
from open_mapping.serialization.mappings import dumps_mapping
from open_mapping.serialization.reviews import load_suggestion_review
from open_mapping.serialization.suggestions import load_suggestion_report


def review_command(
    suggestions: Path,
    decisions: Path,
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
) -> int:
    source_format = require_choice(source_format, SchemaFormat, "--source-format")
    target_format = require_choice(target_format, SchemaFormat, "--target-format")
    validate_input_files(
        {
            "suggestions": suggestions,
            "decisions": decisions,
            "source schema": source,
            "target schema": target,
        }
    )
    preflight_outputs(
        tuple(path for path in (out, review_report_out) if path is not None), force=force
    )
    report = load_suggestion_report(suggestions)
    review = load_suggestion_review(decisions)
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
    if review_report_out is not None:
        outputs[review_report_out] = render_review_json(result)
    write_outputs(outputs, force=force)
    return 0
