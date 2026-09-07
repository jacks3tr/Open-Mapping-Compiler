"""Open Mapping Compiler command-line application."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from open_mapping.cli.apply import apply_command
from open_mapping.cli.benchmark import benchmark_command
from open_mapping.cli.build import build_command, resume_command
from open_mapping.cli.common import (
    ErrorMode,
    ReportFormat,
    SchemaFormat,
    SourceFormat,
    SuggestAssemblyPolicy,
    TargetLanguage,
    run_public_command,
)
from open_mapping.cli.compile import compile_command
from open_mapping.cli.demo import demo_command
from open_mapping.cli.impact import impact_command
from open_mapping.cli.inspect import inspect_command
from open_mapping.cli.map import map_command
from open_mapping.cli.model_context import model_context_command
from open_mapping.cli.models import models_app
from open_mapping.cli.review import review_command, review_draft_command
from open_mapping.cli.run import run_command
from open_mapping.cli.serve import serve_command
from open_mapping.cli.suggest import suggest_command
from open_mapping.cli.verify import verify_command

_ROOT_HELP = """Map source data or a schema locally and return structured JSON.

Run: open-mapping map SOURCE TARGET
Add --model PROVIDER:MODEL only when model assistance is wanted.
"""

app = typer.Typer(name="open-mapping", help=_ROOT_HELP, add_completion=False)
app.add_typer(models_app, name="models", hidden=True)


@app.command("map", help="Map source data or a schema with optional model assistance.")
def map_two_schemas(
    source: Annotated[Path, typer.Argument(help="Source data or schema.", metavar="SOURCE")],
    target: Annotated[Path, typer.Argument(help="Target schema.", metavar="TARGET")],
    source_format: Annotated[
        SourceFormat, typer.Option("--source-format")
    ] = SourceFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    samples: Annotated[Path | None, typer.Option("--samples")] = None,
    hints: Annotated[Path | None, typer.Option("--hints")] = None,
    instruction: Annotated[
        str | None, typer.Option("--instruction", help="Optional mapping context for a model.")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the structured JSON result to this file."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help=(
                "Optional provider:model selection; otherwise uses OPEN_MAPPING_MODEL "
                "or the local fallback."
            ),
        ),
    ] = None,
    models_config: Annotated[
        Path | None,
        typer.Option("--models-config", help="Optional advanced provider configuration."),
    ] = None,
    allow_raw_samples: Annotated[
        bool,
        typer.Option("--allow-raw-samples", help="Allow a selected model to receive raw samples."),
    ] = False,
    require_model: Annotated[
        bool,
        typer.Option("--require-model", help="Fail instead of falling back when model use fails."),
    ] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Disable model calls, including environment defaults.")
    ] = False,
    model_concurrency: Annotated[int, typer.Option("--model-concurrency", min=1, max=8)] = 1,
) -> None:
    _exit(
        lambda: map_command(
            source,
            target,
            source_format=source_format.value,
            source_selector=source_selector,
            target_format=target_format.value,
            target_selector=target_selector,
            samples=samples,
            hints=hints,
            instruction=instruction,
            out=out,
            offline=offline,
            model_concurrency=model_concurrency,
            model=model,
            models_config=models_config,
            allow_raw_samples=allow_raw_samples,
            require_model=require_model,
            force=force,
        )
    )


@app.command()
def build(
    source: Annotated[Path, typer.Argument(help="Source data or schema.", metavar="SOURCE")],
    target: Annotated[Path, typer.Argument(help="Target schema.", metavar="TARGET")],
    source_format: Annotated[
        SourceFormat, typer.Option("--source-format")
    ] = SourceFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    samples: Annotated[Path | None, typer.Option("--samples")] = None,
    hints: Annotated[Path | None, typer.Option("--hints")] = None,
    review: Annotated[Path | None, typer.Option("--review")] = None,
    mapping_id: Annotated[str | None, typer.Option("--mapping-id")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    models_config: Annotated[Path | None, typer.Option("--models-config")] = None,
    instruction: Annotated[str | None, typer.Option("--instruction")] = None,
    allow_raw_samples: Annotated[bool, typer.Option("--allow-raw-samples")] = False,
    require_model: Annotated[bool, typer.Option("--require-model")] = False,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Disable all model calls, including environment defaults."),
    ] = False,
    model_concurrency: Annotated[int, typer.Option("--model-concurrency", min=1, max=8)] = 1,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    require_samples: Annotated[bool, typer.Option("--require-samples")] = False,
    require_complete_review: Annotated[bool, typer.Option("--require-complete-review")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    report_format: Annotated[ReportFormat, typer.Option("--report-format")] = ReportFormat.TEXT,
) -> None:
    _exit(
        lambda: build_command(
            source,
            target,
            source_format=source_format.value,
            source_selector=source_selector,
            target_format=target_format.value,
            target_selector=target_selector,
            samples=samples,
            hints=hints,
            review=review,
            mapping_id=mapping_id,
            model=model,
            models_config=models_config,
            instruction=instruction,
            allow_raw_samples=allow_raw_samples,
            require_model=require_model,
            offline=offline,
            model_concurrency=model_concurrency,
            work_dir=work_dir,
            out=out,
            require_samples=require_samples,
            require_complete_review=require_complete_review,
            force=force,
            report_format=report_format,
        ),
        json_errors=report_format is ReportFormat.JSON,
        mapping_id=mapping_id or f"{source.stem}-to-{target.stem}",
    )


@app.command(help="Resume the exact saved draft without model calls.")
def resume(
    draft: Annotated[Path, typer.Argument(help="Saved draft.json.")],
    review: Annotated[Path, typer.Option("--review")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    report_format: Annotated[ReportFormat, typer.Option("--report-format")] = ReportFormat.TEXT,
) -> None:
    _exit(
        lambda: resume_command(
            draft, review=review, out=out, force=force, report_format=report_format
        ),
        json_errors=report_format is ReportFormat.JSON,
    )


@app.command(help="Report how changed contracts affect a bundle; never modifies or reapproves it.")
def impact(
    bundle: Annotated[Path, typer.Argument()],
    source: Annotated[Path, typer.Argument()],
    target: Annotated[Path, typer.Argument()],
    source_format: Annotated[
        SchemaFormat, typer.Option("--source-format")
    ] = SchemaFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
) -> None:
    _exit(
        lambda: impact_command(
            bundle,
            source,
            target,
            source_format=source_format.value,
            source_selector=source_selector,
            target_format=target_format.value,
            target_selector=target_selector,
        ),
        json_errors=True,
    )


@app.command(
    "review-draft",
    help="Review a frozen draft in the terminal or write a focused decision template.",
)
def review_draft(
    draft: Annotated[Path, typer.Argument(help="Saved draft.json.")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
    interactive: Annotated[bool, typer.Option("--interactive")] = False,
    all_targets: Annotated[bool, typer.Option("--all-targets")] = False,
    show_sample_values: Annotated[bool, typer.Option("--show-sample-values")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _exit(
        lambda: review_draft_command(
            draft,
            out=out,
            interactive=interactive,
            all_targets=all_targets,
            show_sample_values=show_sample_values,
            force=force,
        )
    )


@app.command(help="Run the bundled example with no credentials or network access.")
def demo(
    out_dir: Annotated[Path | None, typer.Option("--out-dir")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _exit(lambda: demo_command(out_dir=out_dir, force=force), json_errors=True)


@app.command()
def apply(
    bundle: Annotated[Path, typer.Argument(help="Verified .omc mapping bundle.", metavar="BUNDLE")],
    input_file: Annotated[Path | None, typer.Option("--input")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    on_error: Annotated[
        ErrorMode,
        typer.Option(
            "--on-error", help="Collect per-record outcomes for JSONL, or stop at the first error."
        ),
    ] = ErrorMode.RAISE,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    diagnostic_values: Annotated[bool, typer.Option("--diagnostic-values")] = False,
) -> None:
    _exit(
        lambda: apply_command(
            bundle,
            input_file=input_file,
            out=out,
            jsonl=jsonl,
            on_error=on_error.value,
            pretty=pretty,
            force=force,
            diagnostic_values=diagnostic_values,
        )
    )


@app.command()
def serve(
    bundle: Annotated[Path, typer.Argument(help="Verified .omc mapping bundle.", metavar="BUNDLE")],
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8080,
    allow_remote: Annotated[bool, typer.Option("--allow-remote")] = False,
    api_key_env: Annotated[str | None, typer.Option("--api-key-env")] = None,
) -> None:
    _exit(
        lambda: serve_command(
            bundle,
            host=host,
            port=port,
            allow_remote=allow_remote,
            api_key_env=api_key_env,
        )
    )


def _exit(
    operation: Callable[[], int],
    *,
    json_errors: bool = False,
    mapping_id: str | None = None,
) -> None:
    raise typer.Exit(run_public_command(operation, json_errors=json_errors, mapping_id=mapping_id))


@app.command(hidden=True)
def inspect(
    schema: Annotated[Path, typer.Argument(help="JSON Schema or OpenAPI file.", metavar="SCHEMA")],
    schema_format: Annotated[
        SchemaFormat,
        typer.Option("--schema-format", help="Input format: json-schema or openapi."),
    ] = SchemaFormat.JSON_SCHEMA,
    selector: Annotated[str | None, typer.Option("--selector", help="OpenAPI selector.")] = None,
) -> None:
    def operation() -> int:
        typer.echo(inspect_command(schema, schema_format, selector), nl=False)
        return 0

    _exit(operation)


@app.command(
    "model-context",
    hidden=True,
    help=(
        "Preview the exact sanitized model package without a provider call. "
        "Raw samples require opt-in; proposals still require review."
    ),
)
def model_context(
    source: Annotated[Path, typer.Argument(help="Source JSON Schema.", metavar="SOURCE")],
    target: Annotated[Path, typer.Argument(help="Target JSON Schema.", metavar="TARGET")],
    model: Annotated[str, typer.Option("--model", help="Configured model alias.")],
    out: Annotated[Path, typer.Option("--out", help="Sanitized context JSON output.")],
    models_config: Annotated[
        Path | None,
        typer.Option("--models-config", help="Provider/model configuration file."),
    ] = None,
    samples: Annotated[Path | None, typer.Option("--samples")] = None,
    hints: Annotated[Path | None, typer.Option("--hints")] = None,
    instruction: Annotated[str | None, typer.Option("--instruction")] = None,
    allow_raw_samples: Annotated[
        bool,
        typer.Option("--allow-raw-samples", help="Include bounded, sanitized raw samples."),
    ] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    def operation() -> int:
        typer.echo(
            model_context_command(
                source,
                target,
                model,
                out,
                models_config,
                samples,
                hints,
                instruction,
                allow_raw_samples,
                force,
            ),
            nl=False,
        )
        return 0

    _exit(operation)


@app.command(
    hidden=True,
    help=(
        "Only --model initiates a model call and possible cost. Raw samples require explicit "
        "opt-in, and model proposals remain subject to review."
    ),
)
def suggest(
    source: Annotated[Path, typer.Argument(help="Source schema.", metavar="SOURCE")],
    target: Annotated[Path, typer.Argument(help="Target schema.", metavar="TARGET")],
    source_format: Annotated[
        SchemaFormat, typer.Option("--source-format")
    ] = SchemaFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    samples: Annotated[Path | None, typer.Option("--samples")] = None,
    hints: Annotated[Path | None, typer.Option("--hints")] = None,
    suggestions_out: Annotated[Path | None, typer.Option("--suggestions-out")] = None,
    mapping_out: Annotated[Path | None, typer.Option("--mapping-out")] = None,
    mapping_id: Annotated[str | None, typer.Option("--mapping-id")] = None,
    assembly_policy: Annotated[
        SuggestAssemblyPolicy,
        typer.Option("--assembly-policy", help="Automatic assembly policy."),
    ] = SuggestAssemblyPolicy.HIGH_AND_MANUAL,
    report_format: Annotated[
        ReportFormat, typer.Option("--report-format", help="Stdout report format.")
    ] = ReportFormat.TEXT,
    diagnostic_values: Annotated[
        bool,
        typer.Option(
            "--diagnostic-values",
            help="Include bounded redacted value summaries in sample diagnostics.",
        ),
    ] = False,
    provider_url: Annotated[
        str | None, typer.Option("--provider-url", help="Optional proposal-provider URL.")
    ] = None,
    models_config: Annotated[
        Path | None,
        typer.Option("--models-config", help="Provider/model configuration file."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Explicit model alias for model-assisted suggestions."),
    ] = None,
    model_context_out: Annotated[
        Path | None,
        typer.Option("--model-context-out", help="Sanitized pre-call context report."),
    ] = None,
    model_run_report_out: Annotated[
        Path | None,
        typer.Option("--model-run-report-out", help="Sanitized model run disclosure report."),
    ] = None,
    provider_token_env: Annotated[
        str | None,
        typer.Option("--provider-token-env", help="Environment variable containing its token."),
    ] = None,
    instruction: Annotated[
        str | None, typer.Option("--instruction", help="Bounded provider instruction text.")
    ] = None,
    allow_raw_samples: Annotated[
        bool,
        typer.Option(
            "--allow-raw-samples",
            help="Opt in to sending raw samples to the selected provider or model.",
        ),
    ] = False,
    require_model: Annotated[
        bool,
        typer.Option(
            "--require-model",
            help="Fail when requested model assistance cannot be completed.",
        ),
    ] = False,
    require_provider: Annotated[
        bool,
        typer.Option(
            "--require-provider",
            help="Exit 5 without artifacts if the selected provider fails.",
        ),
    ] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _exit(
        lambda: suggest_command(
            source,
            target,
            source_format,
            source_selector,
            target_format,
            target_selector,
            samples,
            hints,
            suggestions_out,
            mapping_out,
            mapping_id,
            assembly_policy,
            report_format,
            provider_url,
            provider_token_env,
            instruction,
            allow_raw_samples,
            require_provider,
            force,
            diagnostic_values,
            model,
            require_model,
            models_config,
            model_context_out,
            model_run_report_out,
        )
    )


@app.command(hidden=True)
def review(
    suggestions: Annotated[Path, typer.Argument(help="Suggestion report.", metavar="SUGGESTIONS")],
    source: Annotated[Path, typer.Option("--source")],
    target: Annotated[Path, typer.Option("--target")],
    out: Annotated[Path, typer.Option("--out")],
    decisions: Annotated[
        Path,
        typer.Option("--decisions", help="Review decision file or interactive output."),
    ],
    source_format: Annotated[
        SchemaFormat, typer.Option("--source-format")
    ] = SchemaFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    review_report_out: Annotated[Path | None, typer.Option("--review-report-out")] = None,
    require_complete_review: Annotated[bool, typer.Option("--require-complete-review")] = False,
    interactive: Annotated[bool, typer.Option("--interactive")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _exit(
        lambda: review_command(
            suggestions,
            decisions,
            source,
            target,
            source_format,
            source_selector,
            target_format,
            target_selector,
            out,
            review_report_out,
            require_complete_review,
            force,
            interactive,
        )
    )


@app.command(hidden=True)
def verify(
    mapping: Annotated[Path, typer.Argument(help="Mapping document.", metavar="MAPPING")],
    source: Annotated[Path, typer.Option("--source")],
    target: Annotated[Path, typer.Option("--target")],
    samples: Annotated[Path, typer.Option("--samples")],
    source_format: Annotated[
        SchemaFormat, typer.Option("--source-format")
    ] = SchemaFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    report_format: Annotated[ReportFormat, typer.Option("--report-format")] = ReportFormat.JSON,
    diagnostic_values: Annotated[
        bool,
        typer.Option(
            "--diagnostic-values",
            help="Include bounded redacted value summaries in verification diagnostics.",
        ),
    ] = False,
) -> None:
    _exit(
        lambda: verify_command(
            mapping,
            source,
            target,
            source_format,
            source_selector,
            target_format,
            target_selector,
            samples,
            report_format,
            diagnostic_values,
        )
    )


@app.command(hidden=True)
def run(
    mapping: Annotated[Path, typer.Argument(help="Mapping document.", metavar="MAPPING")],
    source_schema: Annotated[Path, typer.Option("--source-schema")],
    target_schema: Annotated[Path, typer.Option("--target-schema")],
    input_file: Annotated[Path, typer.Option("--input")],
    out: Annotated[Path, typer.Option("--out")],
    source_format: Annotated[
        SchemaFormat, typer.Option("--source-format")
    ] = SchemaFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    diagnostic_values: Annotated[
        bool,
        typer.Option(
            "--diagnostic-values",
            help="Include bounded redacted value summaries in verification diagnostics.",
        ),
    ] = False,
) -> None:
    _exit(
        lambda: run_command(
            mapping,
            source_schema,
            target_schema,
            source_format,
            source_selector,
            target_format,
            target_selector,
            input_file,
            out,
            force,
            diagnostic_values,
        )
    )


@app.command(hidden=True)
def compile(
    mapping: Annotated[Path, typer.Argument(help="Mapping document.", metavar="MAPPING")],
    source: Annotated[Path, typer.Option("--source")],
    target: Annotated[Path, typer.Option("--target")],
    target_language: Annotated[TargetLanguage, typer.Option("--target-language")],
    out: Annotated[Path, typer.Option("--out")],
    source_format: Annotated[
        SchemaFormat, typer.Option("--source-format")
    ] = SchemaFormat.JSON_SCHEMA,
    source_selector: Annotated[str | None, typer.Option("--source-selector")] = None,
    target_format: Annotated[
        SchemaFormat, typer.Option("--target-format")
    ] = SchemaFormat.JSON_SCHEMA,
    target_selector: Annotated[str | None, typer.Option("--target-selector")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _exit(
        lambda: compile_command(
            mapping,
            source,
            target,
            source_format,
            source_selector,
            target_format,
            target_selector,
            target_language,
            out,
            force,
        )
    )


@app.command(hidden=True)
def benchmark(
    paths: Annotated[
        list[Path], typer.Argument(help="Benchmark pack directories.", metavar="PATHS")
    ],
    enforce_gates: Annotated[bool, typer.Option("--enforce-gates")] = False,
    report_out: Annotated[Path | None, typer.Option("--report-out")] = None,
    models_config: Annotated[
        Path | None,
        typer.Option("--models-config", help="Provider/model configuration file."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Configured model alias; this is the only model-call switch."),
    ] = None,
    model_results_dir: Annotated[
        Path | None,
        typer.Option(
            "--model-results-dir",
            help="Bounded JSON and Markdown model-comparison report directory.",
        ),
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _exit(
        lambda: benchmark_command(
            paths,
            enforce_gates,
            report_out,
            force,
            models_config,
            model,
            model_results_dir,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
