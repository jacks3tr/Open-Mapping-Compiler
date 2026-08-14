"""Benchmark command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from pydantic import ValidationError

from open_mapping.benchmark.loader import find_benchmark_packs
from open_mapping.benchmark.runner import persist_model_comparison, run_benchmark_pack
from open_mapping.cli.common import (
    CliInputError,
    preflight_outputs,
    validate_input_files,
    write_output,
)
from open_mapping.cli.models import load_cli_model_selection
from open_mapping.errors import OpenMappingError


def _write_invalid_pack_report(pack_dir: Path, message: str) -> tuple[Path, Path]:
    report_dir = Path("results") / pack_dir.name
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "benchmark.json"
    markdown_path = report_dir / "benchmark.md"
    value = {
        "report_version": "0.1",
        "id": pack_dir.name,
        "status": "invalid",
        "error_code": "INVALID_INPUT",
        "message": message,
    }
    json_path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        f"# Benchmark {pack_dir.name}\n\nStatus: invalid\n\nINVALID_INPUT: {message}\n",
        encoding="utf-8",
    )
    return json_path, markdown_path


def benchmark_command(
    paths: list[Path],
    enforce_gates: bool,
    report_out: Path | None,
    force: bool,
    models_config: Path | None = None,
    model: str | None = None,
    model_results_dir: Path | None = None,
) -> int:
    if model_results_dir is not None and model is None:
        raise CliInputError("--model-results-dir requires --model")
    selection = load_cli_model_selection(models_config, model) if model is not None else None
    for index, path in enumerate(paths, start=1):
        if not path.exists():
            validate_input_files({f"benchmark path {index}": path})
    if report_out is not None:
        preflight_outputs((report_out,), force=force)
    failed = False
    lines: list[str] = []
    diagnostics: list[str] = []
    modeled_runs = []
    for pack in paths:
        for pack_dir in find_benchmark_packs(pack):
            try:
                result_dir = None
                if selection is not None:
                    comparison_root = (
                        model_results_dir
                        if model_results_dir is not None
                        else Path("results") / "models"
                    )
                    result_dir = comparison_root / selection.resolved_model.alias / pack_dir.name
                run = run_benchmark_pack(
                    pack_dir,
                    enforce_gates=enforce_gates,
                    result_dir=result_dir,
                    model_selection=selection,
                )
            except (
                OpenMappingError,
                OSError,
                subprocess.SubprocessError,
                json.JSONDecodeError,
                ValidationError,
                TypeError,
                ValueError,
            ) as exc:
                failed = True
                message = str(exc).strip() or type(exc).__name__
                json_path, markdown_path = _write_invalid_pack_report(pack_dir, message)
                lines.append(f"# {pack_dir.name}")
                lines.append("status=invalid")
                lines.append(f"json_report={json_path.resolve()}")
                lines.append(f"markdown_report={markdown_path.resolve()}")
                diagnostics.append(f"PACK_INVALID: {pack_dir.name}: {message}")
                continue
            lines.append(f"# {run.id}")
            lines.append(run.metrics.model_dump_json(indent=2))
            lines.append(
                f"baseline_confidence_counts={getattr(run, 'baseline_confidence_counts', run.confidence_counts)}"
            )
            lines.append(
                f"baseline_disposition_counts={getattr(run, 'baseline_disposition_counts', run.disposition_counts)}"
            )
            lines.append(
                f"assisted_confidence_counts={getattr(run, 'assisted_confidence_counts', run.confidence_counts)}"
            )
            lines.append(
                f"assisted_disposition_counts={getattr(run, 'assisted_disposition_counts', run.disposition_counts)}"
            )
            json_report_path = getattr(run, "json_report_path", None)
            markdown_report_path = getattr(run, "markdown_report_path", None)
            if json_report_path is not None:
                lines.append(f"json_report={json_report_path.resolve()}")
            if markdown_report_path is not None:
                lines.append(f"markdown_report={markdown_report_path.resolve()}")
            if run.gate_issues:
                failed = True
                for issue in run.gate_issues:
                    diagnostics.append(f"GATE_FAILED: {issue.message}")
            model_results = getattr(run, "model_results", {})
            if model_results:
                modeled_runs.append(run)
                for result in model_results.values():
                    lines.append(f"model={result.comparison_key}")
                    lines.append(result.metrics.model_dump_json(indent=2))
    if selection is not None and modeled_runs:
        comparison_root = (
            model_results_dir if model_results_dir is not None else Path("results") / "models"
        )
        comparison_json, comparison_markdown = persist_model_comparison(
            modeled_runs, comparison_root
        )
        lines.append(f"model_comparison_json={comparison_json.resolve()}")
        lines.append(f"model_comparison_markdown={comparison_markdown.resolve()}")
    text = "\n".join(lines) + "\n"
    typer.echo(text, nl=False)
    if diagnostics:
        typer.echo("\n".join(diagnostics), err=True)
    if report_out is not None:
        write_output(report_out, text, force=force)
    return 7 if failed and enforce_gates else 0
