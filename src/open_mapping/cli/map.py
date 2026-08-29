"""Primary two-schema mapping command."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from open_mapping.cli.common import preflight_outputs, validate_input_files, write_output
from open_mapping.mapping import map_schemas
from open_mapping.reports.json_report import render_suggestions_json


def map_command(
    source: Path,
    target: Path,
    *,
    source_format: Literal["json-schema", "openapi", "json-data"],
    source_selector: str | None,
    target_format: Literal["json-schema", "openapi"],
    target_selector: str | None,
    samples: Path | None,
    hints: Path | None,
    instruction: str | None,
    out: Path | None,
    model: str | None,
    models_config: Path | None,
    allow_raw_samples: bool,
    require_model: bool,
    force: bool,
) -> int:
    """Map two schemas locally, with optional model assistance."""

    inputs = {"source input": source, "target schema": target}
    if samples is not None:
        inputs["samples"] = samples
    if hints is not None:
        inputs["hints"] = hints
    validate_input_files(inputs)
    if out is not None:
        preflight_outputs((out,), force=force)
    report = map_schemas(
        source,
        target,
        source_format=source_format,
        source_selector=source_selector,
        target_format=target_format,
        target_selector=target_selector,
        model=model,
        models_config=models_config,
        samples=samples,
        hints=hints,
        instruction=instruction,
        allow_raw_samples=allow_raw_samples,
        require_model=require_model,
    )
    serialized = render_suggestions_json(report)
    if out is None:
        typer.echo(serialized, nl=False)
    else:
        write_output(out, serialized, force=force)
    return 0


__all__ = ["map_command"]
