"""Mapping verification command."""

from __future__ import annotations

from pathlib import Path

import typer

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import (
    ReportFormat,
    SchemaFormat,
    require_choice,
    validate_input_files,
)
from open_mapping.reports.json_report import render_verification_json
from open_mapping.reports.markdown_report import render_verification_markdown
from open_mapping.reports.text_report import render_verification_text
from open_mapping.serialization.mappings import load_mapping
from open_mapping.verification.dynamic import load_verification_samples, verify_samples


def verify_command(
    mapping: Path,
    source: Path,
    target: Path,
    source_format: SchemaFormat,
    source_selector: str | None,
    target_format: SchemaFormat,
    target_selector: str | None,
    samples: Path,
    report_format: ReportFormat,
    diagnostic_values: bool,
) -> int:
    source_format = require_choice(source_format, SchemaFormat, "--source-format")
    target_format = require_choice(target_format, SchemaFormat, "--target-format")
    report_format = require_choice(report_format, ReportFormat, "--report-format")
    validate_input_files(
        {"mapping": mapping, "source schema": source, "target schema": target, "samples": samples}
    )
    document = load_mapping(mapping)
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
    samples_doc = load_verification_samples(samples)
    report = verify_samples(
        document,
        source_schema=source_schema,
        target_schema=target_schema,
        samples=samples_doc,
        diagnostic_values=diagnostic_values,
    )
    renderer = {
        ReportFormat.JSON: render_verification_json,
        ReportFormat.MARKDOWN: render_verification_markdown,
        ReportFormat.TEXT: render_verification_text,
    }[report_format]
    rendered = renderer(report)
    typer.echo(rendered, nl=False)
    if not report.static.valid:
        return 3
    return 0 if report.valid else 4
