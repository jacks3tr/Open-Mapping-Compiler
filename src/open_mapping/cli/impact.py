"""Read-only contract impact reporting for automation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from open_mapping.compiler import Compiler
from open_mapping.serialization.bundles import load_bundle


def impact_command(
    bundle: Path,
    source: Path,
    target: Path,
    *,
    source_format: Literal["json-schema", "openapi"],
    source_selector: str | None,
    target_format: Literal["json-schema", "openapi"],
    target_selector: str | None,
) -> int:
    report = Compiler(offline=True).analyze_changes(
        load_bundle(bundle),
        source=source,
        target=target,
        source_format=source_format,
        source_selector=source_selector,
        target_format=target_format,
        target_selector=target_selector,
    )
    typer.echo(report.model_dump_json(indent=2))
    return 3 if not report.static_valid else 8 if report.requires_review else 0
