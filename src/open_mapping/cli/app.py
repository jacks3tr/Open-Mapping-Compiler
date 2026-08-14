"""Open Mapping Compiler command-line application."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from open_mapping.cli.benchmark import benchmark_command
from open_mapping.cli.common import (
    ReportFormat,
    SchemaFormat,
    SuggestAssemblyPolicy,
    TargetLanguage,
    run_public_command,
)
from open_mapping.cli.compile import compile_command
from open_mapping.cli.inspect import inspect_command
from open_mapping.cli.model_context import model_context_command
from open_mapping.cli.models import models_app
from open_mapping.cli.review import review_command
from open_mapping.cli.run import run_command
from open_mapping.cli.suggest import suggest_command
from open_mapping.cli.verify import verify_command

_ROOT_HELP = """Open Mapping Compiler provides deterministic schema mapping and verification.

Privacy: raw samples are excluded from providers by default.
Cost: only an explicit --model selection can initiate a billable model call.
Semantics: confidence and disposition are separate concepts.
Review: model proposals are drafts; noninteractive review records automation-safe decisions.
Providers: a required provider failure is fatal; baseline use is offline.
Exit codes: 0 success; 2 input; 3 static; 4 dynamic; 5 provider; 6 codegen; 7 benchmark; 8 review.
"""

app = typer.Typer(name="open-mapping", help=_ROOT_HELP, add_completion=False)
app.add_typer(models_app, name="models")


def _exit(operation: Callable[[], int]) -> None:
    raise typer.Exit(run_public_command(operation))


@app.command()
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
    help=(
        "Only --model initiates a model call and possible cost. Raw samples require explicit "
        "opt-in, and model proposals remain subject to review."
    )
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


@app.command()
def review(
    suggestions: Annotated[Path, typer.Argument(help="Suggestion report.", metavar="SUGGESTIONS")],
    decisions: Annotated[
        Path,
        typer.Option("--decisions", help="Required noninteractive review decision file."),
    ],
    source: Annotated[Path, typer.Option("--source")],
    target: Annotated[Path, typer.Option("--target")],
    out: Annotated[Path, typer.Option("--out")],
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
        )
    )


@app.command()
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


@app.command()
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


@app.command()
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


@app.command()
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
