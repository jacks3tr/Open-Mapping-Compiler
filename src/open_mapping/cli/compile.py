"""Mapping compile command."""

from __future__ import annotations

from pathlib import Path

import typer

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import (
    SchemaFormat,
    TargetLanguage,
    preflight_outputs,
    render_issues,
    require_choice,
    validate_input_files,
    write_output,
)
from open_mapping.codegen.python import generate_python
from open_mapping.codegen.typescript import generate_typescript
from open_mapping.errors import OpenMappingError
from open_mapping.serialization.mappings import load_mapping


def compile_command(
    mapping: Path,
    source: Path,
    target: Path,
    source_format: SchemaFormat,
    source_selector: str | None,
    target_format: SchemaFormat,
    target_selector: str | None,
    target_language: TargetLanguage,
    out: Path,
    force: bool,
) -> int:
    source_format = require_choice(source_format, SchemaFormat, "--source-format")
    target_format = require_choice(target_format, SchemaFormat, "--target-format")
    target_language = require_choice(target_language, TargetLanguage, "--target-language")
    validate_input_files({"mapping": mapping, "source schema": source, "target schema": target})
    preflight_outputs((out,), force=force)
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
    try:
        generator = {
            TargetLanguage.PYTHON: generate_python,
            TargetLanguage.TYPESCRIPT: generate_typescript,
        }[target_language]
        artifact = generator(document, source_schema=source_schema, target_schema=target_schema)
    except OpenMappingError as exc:
        typer.echo(render_issues(exc.issues), err=True)
        if all(issue.component == "verification.static" for issue in exc.issues):
            return 3
        return 6
    except (OverflowError, ValueError):
        typer.echo("CODEGEN_FAILED: code generation failed", err=True)
        return 6
    write_output(out, artifact.source, force=force)
    return 0
