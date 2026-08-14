"""Mapping run command."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import (
    SchemaFormat,
    preflight_outputs,
    render_issues,
    require_choice,
    validate_input_files,
    write_output,
)
from open_mapping.errors import OpenMappingError
from open_mapping.model.json_types import JsonValue
from open_mapping.runtime import run_mapping
from open_mapping.serialization.mappings import load_mapping


def run_command(
    mapping: Path,
    source_schema: Path,
    target_schema: Path,
    source_format: SchemaFormat,
    source_selector: str | None,
    target_format: SchemaFormat,
    target_selector: str | None,
    input_file: Path,
    out: Path,
    force: bool,
    diagnostic_values: bool,
) -> int:
    source_format = require_choice(source_format, SchemaFormat, "--source-format")
    target_format = require_choice(target_format, SchemaFormat, "--target-format")
    validate_input_files(
        {
            "mapping": mapping,
            "source schema": source_schema,
            "target schema": target_schema,
            "input": input_file,
        }
    )
    preflight_outputs((out,), force=force)
    document = load_mapping(mapping)
    parsed_source = parse_openapi_selector(source_selector) if source_selector is not None else None
    parsed_target = parse_openapi_selector(target_selector) if target_selector is not None else None
    source_doc = load_schema(
        source_schema,
        format_name=source_format.value,
        selector=parsed_source,
        schema_id=None,
    )
    target_doc = load_schema(
        target_schema,
        format_name=target_format.value,
        selector=parsed_target,
        schema_id=None,
    )
    source_value: JsonValue = json.loads(input_file.read_text(encoding="utf-8"))
    try:
        output = run_mapping(
            document,
            source_schema=source_doc,
            target_schema=target_doc,
            source=source_value,
            diagnostic_values=diagnostic_values,
        )
    except OpenMappingError as exc:
        typer.echo(render_issues(exc.issues), err=True)
        if all(issue.component == "verification.static" for issue in exc.issues):
            return 3
        return 4
    write_output(
        out,
        json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        force=force,
    )
    return 0
