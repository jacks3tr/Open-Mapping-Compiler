"""Suggestion and mapping assembly command."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import typer

from open_mapping.adapters.openapi import load_schema, parse_openapi_selector
from open_mapping.cli.common import (
    CliInputError,
    ReportFormat,
    SchemaFormat,
    SuggestAssemblyPolicy,
    preflight_outputs,
    render_issues,
    require_choice,
    validate_input_files,
    write_output,
    write_outputs,
)
from open_mapping.cli.model_context import (
    build_cli_model_context,
    render_model_context,
    render_model_run_report,
)
from open_mapping.cli.models import CliModelSelection, load_cli_model_selection
from open_mapping.errors import OpenMappingError
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.profiles import FieldProfile, profile_samples
from open_mapping.matching.proposals import (
    apply_model_mapping_responses,
    apply_provider_assistance,
    build_deterministic_suggestions,
)
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonValue
from open_mapping.model.reviews import AssemblyPolicy
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.providers.protocol import ProviderRequest, ProviderResponse
from open_mapping.reports.json_report import render_suggestions_json
from open_mapping.reports.markdown_report import render_suggestions_markdown
from open_mapping.reports.text_report import render_suggestions_text
from open_mapping.verification.dynamic import _source_issues, load_verification_samples


def _schema(path: Path, fmt: SchemaFormat, selector: str | None) -> SchemaDocument:
    parsed = parse_openapi_selector(selector) if selector is not None else None
    return load_schema(
        path,
        format_name=fmt.value,
        selector=parsed,
        schema_id=None,
    )


def suggest_command(
    source: Path,
    target: Path,
    source_format: SchemaFormat,
    source_selector: str | None,
    target_format: SchemaFormat,
    target_selector: str | None,
    samples: Path | None,
    hints: Path | None,
    suggestions_out: Path | None,
    mapping_out: Path | None,
    mapping_id: str | None,
    assembly_policy: SuggestAssemblyPolicy,
    report_format: ReportFormat,
    provider_url: str | None,
    provider_token_env: str | None,
    instruction: str | None,
    allow_raw_samples: bool,
    require_provider: bool,
    force: bool,
    diagnostic_values: bool = False,
    model: str | None = None,
    require_model: bool = False,
    models_config: Path | None = None,
    model_context_out: Path | None = None,
    model_run_report_out: Path | None = None,
) -> int:
    source_format = require_choice(source_format, SchemaFormat, "--source-format")
    target_format = require_choice(target_format, SchemaFormat, "--target-format")
    assembly_policy = require_choice(assembly_policy, SuggestAssemblyPolicy, "--assembly-policy")
    report_format = require_choice(report_format, ReportFormat, "--report-format")
    if provider_url is not None and model is not None:
        raise CliInputError("--provider-url and --model are mutually exclusive")
    if allow_raw_samples and model is None and provider_url is None:
        raise CliInputError("--allow-raw-samples requires --model or --provider-url")
    if require_model and model is None:
        raise CliInputError("--require-model requires --model")
    if model_context_out is not None and model is None:
        raise CliInputError("--model-context-out requires --model")
    if model_run_report_out is not None and model is None:
        raise CliInputError("--model-run-report-out requires --model")
    if instruction is not None and provider_url is None and model is None:
        raise CliInputError("--instruction requires --provider-url unless --model is selected")
    provider_only_options = {
        "--require-provider": require_provider,
        "--provider-token-env": provider_token_env is not None,
    }
    if provider_url is None:
        for option, active in provider_only_options.items():
            if active:
                raise CliInputError(f"{option} requires --provider-url")
    selection: CliModelSelection | None = None
    if model is not None:
        selection = load_cli_model_selection(models_config, model)
    if mapping_out is not None and mapping_id is None:
        raise CliInputError("--mapping-out requires --mapping-id")
    validate_input_files(
        {"source schema": source, "target schema": target, "samples": samples, "hints": hints}
    )
    output_paths = tuple(
        path
        for path in (
            suggestions_out,
            mapping_out,
            model_context_out,
            model_run_report_out,
        )
        if path is not None
    )
    preflight_outputs(output_paths, force=force)
    source_schema = _schema(source, source_format, source_selector)
    target_schema = _schema(target, target_format, target_selector)
    source_values: tuple[JsonValue, ...] = ()
    source_profiles: tuple[FieldProfile, ...] = ()
    if samples is not None:
        loaded_samples = load_verification_samples(samples)
        sample_issues = tuple(
            issue
            for sample in loaded_samples
            for issue in _source_issues(
                source_schema,
                sample.input,
                sample.id,
                diagnostic_values=diagnostic_values,
            )
        )
        if sample_issues:
            raise OpenMappingError(sample_issues)
        source_values = tuple(sample.input for sample in loaded_samples)
        source_profiles = profile_samples(source_schema, source_values)
    candidate_sets = generate_candidates(
        source_schema,
        target_schema,
        source_profiles=source_profiles,
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=10,
    )
    mapping_hints = None
    if hints is not None:
        from open_mapping.serialization.hints import load_mapping_hints

        mapping_hints = load_mapping_hints(hints)
    report: SuggestionReport = build_deterministic_suggestions(
        source_schema,
        target_schema,
        candidate_sets=candidate_sets,
        hints=mapping_hints,
    )
    serialized_model_run_report: str | None = None
    if provider_url is not None:
        from open_mapping.providers.http import call_http_provider
        from open_mapping.providers.protocol import aggregate_provider_disclosure
        from open_mapping.providers.redaction import sanitize_provider_request

        raw_samples = source_values if source_values else None
        provider_failures: list[Issue] = []
        provider_responses: dict[str, ProviderResponse] = {}
        sanitized_requests: list[tuple[ProviderRequest, int]] = []
        for suggestion in report.suggestions:
            target_field = target_schema.field(suggestion.target_path)
            if target_field is None:
                continue
            candidate_paths = {candidate.source_path for candidate in suggestion.candidates}
            request = ProviderRequest(
                protocol_version="0.1",
                task="rerank-and-propose",
                source_schema_id=source_schema.schema_id,
                target_schema_id=target_schema.schema_id,
                target_path=suggestion.target_path,
                candidates=suggestion.candidates,
                source_field_metadata=tuple(
                    field for field in source_schema.fields if field.pointer in candidate_paths
                ),
                target_field_metadata=target_field,
                sample_profiles=tuple(
                    profile for profile in source_profiles if profile.pointer in candidate_paths
                ),
                instruction_text=instruction,
                raw_samples=raw_samples,
            )
            sanitized_requests.append(
                sanitize_provider_request(request, allow_raw_samples=allow_raw_samples)
            )
            try:
                provider_result = call_http_provider(
                    provider_url,
                    token_env=provider_token_env,
                    request=request,
                    allow_raw_samples=allow_raw_samples,
                )
                provider_responses[suggestion.target_path] = provider_result.response
            except OpenMappingError as exc:
                severity = Severity.ERROR if require_provider else Severity.WARNING
                provider_failures.extend(
                    issue.model_copy(update={"severity": severity}) for issue in exc.issues
                )
        disclosure = aggregate_provider_disclosure(
            endpoint_origin=urlparse(provider_url).netloc,
            raw_samples_included=allow_raw_samples,
            requests=sanitized_requests,
        )
        report = apply_provider_assistance(
            report,
            source_schema=source_schema,
            target_schema=target_schema,
            responses=provider_responses,
        ).model_copy(update={"provider_disclosure": disclosure})
        assistance_failures = tuple(
            issue for issue in report.issues if issue.code == IssueCode.PROVIDER_RESPONSE_INVALID
        )
        if assistance_failures:
            provider_failures.extend(
                issue.model_copy(
                    update={"severity": Severity.ERROR if require_provider else Severity.WARNING}
                )
                for issue in assistance_failures
            )
            report = report.model_copy(
                update={
                    "issues": tuple(
                        issue
                        for issue in report.issues
                        if issue.code != IssueCode.PROVIDER_RESPONSE_INVALID
                    )
                }
            )
        report = report.model_copy(update={"issues": report.issues + tuple(provider_failures)})
        if provider_failures:
            typer.echo(
                "\n".join(
                    f"{issue.severity.value}: {issue.code.value}: {issue.message}"
                    for issue in provider_failures
                ),
                err=True,
            )
        if provider_failures and require_provider:
            return 5
    elif selection is not None:
        from open_mapping.providers.orchestrator import invoke_model_mapping
        from open_mapping.providers.registry import build_transport_registry

        packages = build_cli_model_context(
            source_schema=source_schema,
            target_schema=target_schema,
            candidate_sets=candidate_sets,
            source_profiles=source_profiles,
            hints=mapping_hints,
            instruction=instruction,
            raw_samples=source_values,
            selection=selection,
            allow_raw_samples=allow_raw_samples,
        )
        if model_context_out is not None:
            write_output(
                model_context_out,
                render_model_context(packages, selection=selection),
                force=force,
            )
        responses, model_disclosure, invocation_issues = invoke_model_mapping(
            packages=packages,
            resolved_model=selection.resolved_model,
            config_sha256=selection.config_sha256,
            registry=build_transport_registry(),
        )
        assisted = apply_model_mapping_responses(
            report,
            source_schema=source_schema,
            target_schema=target_schema,
            packages=packages,
            responses=responses,
            disclosure=model_disclosure,
        )
        baseline_issue_values = {issue.model_dump_json() for issue in report.issues}
        reconciliation_issues = tuple(
            issue
            for issue in assisted.issues
            if issue.model_dump_json() not in baseline_issue_values
        )
        model_failed = bool(invocation_issues or reconciliation_issues)
        reported_invocation_issues = tuple(
            issue.model_copy(
                update={"severity": Severity.ERROR if require_model else Severity.WARNING}
            )
            for issue in invocation_issues
        )
        reported_reconciliation_issues = tuple(
            issue.model_copy(
                update={"severity": Severity.ERROR if require_model else Severity.WARNING}
            )
            for issue in reconciliation_issues
        )
        reported_model_issues = sort_issues(
            (*reported_invocation_issues, *reported_reconciliation_issues)
        )
        report = assisted.model_copy(
            update={
                "issues": sort_issues((*assisted.issues, *reported_invocation_issues)),
            }
        )
        serialized_model_run_report = render_model_run_report(
            model_disclosure,
            issues=reported_model_issues,
        )
        if reported_model_issues:
            typer.echo(
                "\n".join(
                    f"{issue.severity.value}: {issue.code.value}: {issue.message}"
                    for issue in reported_model_issues
                ),
                err=True,
            )
        if model_failed and require_model:
            if model_run_report_out is not None:
                write_output(model_run_report_out, serialized_model_run_report, force=force)
            return 5
    serialized_mapping: str | None = None
    if mapping_out is not None:
        assert mapping_id is not None
        policy = {
            SuggestAssemblyPolicy.HIGH_AND_MANUAL: AssemblyPolicy.HIGH_AND_MANUAL,
            SuggestAssemblyPolicy.MANUAL_ONLY: AssemblyPolicy.MANUAL_ONLY,
        }[assembly_policy]
        result = assemble_mapping(
            report,
            mapping_id=mapping_id,
            source_schema=source_schema,
            target_schema=target_schema,
            policy=policy,
            review=None,
            require_complete_review=False,
        )
        if result.mapping is None:
            typer.echo(render_issues(result.issues), err=True)
            return 3
        from open_mapping.serialization.mappings import dumps_mapping

        serialized_mapping = dumps_mapping(result.mapping, format_name="yaml")
    outputs: dict[Path, str] = {}
    if suggestions_out is not None:
        outputs[suggestions_out] = render_suggestions_json(report)
    if mapping_out is not None:
        assert serialized_mapping is not None
        outputs[mapping_out] = serialized_mapping
    if model_run_report_out is not None:
        assert serialized_model_run_report is not None
        outputs[model_run_report_out] = serialized_model_run_report
    if outputs:
        write_outputs(outputs, force=force)
    renderer = {
        ReportFormat.JSON: render_suggestions_json,
        ReportFormat.MARKDOWN: render_suggestions_markdown,
        ReportFormat.TEXT: render_suggestions_text,
    }[report_format]
    typer.echo(renderer(report), nl=False)
    return 0
