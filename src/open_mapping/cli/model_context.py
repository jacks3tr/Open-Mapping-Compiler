"""Sanitized model-context preview command and shared rendering helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from open_mapping.adapters.openapi import load_schema
from open_mapping.cli.common import (
    CliInputError,
    preflight_outputs,
    validate_input_files,
    write_output,
)
from open_mapping.cli.models import CliModelSelection, load_cli_model_selection
from open_mapping.errors import OpenMappingError
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.profiles import FieldProfile, profile_samples
from open_mapping.model.hints import MappingHints
from open_mapping.model.issues import Issue
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_protocol import MappingContextPackage, mapping_context_sha256
from open_mapping.model.providers import ModelRunDisclosure
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import TargetCandidateSet
from open_mapping.providers.context import ContextPackingOptions, build_mapping_context_batches
from open_mapping.serialization.canonical_json import canonical_json
from open_mapping.verification.dynamic import _source_issues, load_verification_samples


def build_cli_model_context(
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    candidate_sets: Sequence[TargetCandidateSet],
    source_profiles: tuple[FieldProfile, ...],
    hints: MappingHints | None,
    instruction: str | None,
    raw_samples: tuple[JsonValue, ...],
    selection: CliModelSelection,
    allow_raw_samples: bool,
) -> tuple[MappingContextPackage, ...]:
    """Build the exact package sequence used by the selected CLI model."""

    model = selection.resolved_model.model
    return build_mapping_context_batches(
        source_schema=source_schema,
        target_schema=target_schema,
        candidate_sets=candidate_sets,
        source_profiles=source_profiles,
        hints=hints,
        instruction=instruction,
        raw_samples=raw_samples,
        options=ContextPackingOptions(
            mode=model.context_mode,
            input_token_budget=model.input_token_budget,
            target_batch_size=model.target_batch_size,
            candidate_limit_per_target=model.candidate_limit_per_target,
            include_raw_samples=allow_raw_samples,
        ),
    )


def render_model_context(
    packages: tuple[MappingContextPackage, ...],
    *,
    selection: CliModelSelection,
) -> str:
    """Render every sanitized package beside its canonical digest."""

    resolved = selection.resolved_model
    payload: JsonValue = {
        "config_sha256": selection.config_sha256,
        "context_version": "0.1",
        "model_alias": resolved.alias,
        "model_id": resolved.model.model_id,
        "packages": [
            {
                "context_sha256": mapping_context_sha256(package),
                "package": cast(JsonValue, package.model_dump(mode="json")),
            }
            for package in packages
        ],
        "provider_kind": resolved.provider.kind.value,
        "provider_name": resolved.provider_name,
        "raw_samples_included": any(package.raw_samples_included for package in packages),
    }
    return canonical_json(payload) + "\n"


def render_model_run_report(
    disclosure: ModelRunDisclosure,
    *,
    issues: tuple[Issue, ...],
) -> str:
    """Render bounded disclosure metadata without typed responses or provider transcripts."""

    payload: JsonValue = {
        "batch_runs": [
            cast(
                JsonValue,
                run.model_dump(mode="json", exclude={"response"}),
            )
            for run in disclosure.batch_runs
        ],
        "config_sha256": disclosure.config_sha256,
        "context_mode": disclosure.context_mode.value,
        "issues": [cast(JsonValue, issue.model_dump(mode="json")) for issue in issues],
        "model_alias": disclosure.model_alias,
        "model_id": disclosure.model_id,
        "prompt_version": disclosure.prompt_version,
        "provider_kind": disclosure.provider_kind.value,
        "provider_name": disclosure.provider_name,
        "raw_samples_included": disclosure.raw_samples_included,
        "redaction_count": disclosure.redaction_count,
        "report_version": "0.1",
    }
    return canonical_json(payload) + "\n"


def _load_context_inputs(
    source: Path,
    target: Path,
    samples: Path | None,
    hints: Path | None,
) -> tuple[
    SchemaDocument,
    SchemaDocument,
    tuple[JsonValue, ...],
    tuple[FieldProfile, ...],
    MappingHints | None,
]:
    source_schema = load_schema(source, format_name="json-schema", selector=None, schema_id=None)
    target_schema = load_schema(target, format_name="json-schema", selector=None, schema_id=None)
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
                diagnostic_values=False,
            )
        )
        if sample_issues:
            raise OpenMappingError(sample_issues)
        source_values = tuple(sample.input for sample in loaded_samples)
        source_profiles = profile_samples(source_schema, source_values)
    mapping_hints: MappingHints | None = None
    if hints is not None:
        from open_mapping.serialization.hints import load_mapping_hints

        mapping_hints = load_mapping_hints(hints)
    return source_schema, target_schema, source_values, source_profiles, mapping_hints


def model_context_command(
    source: Path,
    target: Path,
    model: str,
    out: Path,
    models_config: Path | None,
    samples: Path | None,
    hints: Path | None,
    instruction: str | None,
    allow_raw_samples: bool,
    force: bool,
) -> str:
    """Build and atomically write a provider-free sanitized context preview."""

    if not model.strip():
        raise CliInputError("--model must not be empty")
    selection = load_cli_model_selection(models_config, model)
    validate_input_files(
        {"source schema": source, "target schema": target, "samples": samples, "hints": hints}
    )
    preflight_outputs((out,), force=force)
    source_schema, target_schema, raw_samples, source_profiles, mapping_hints = (
        _load_context_inputs(source, target, samples, hints)
    )
    candidate_sets = generate_candidates(
        source_schema,
        target_schema,
        source_profiles=source_profiles,
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=10,
    )
    packages = build_cli_model_context(
        source_schema=source_schema,
        target_schema=target_schema,
        candidate_sets=candidate_sets,
        source_profiles=source_profiles,
        hints=mapping_hints,
        instruction=instruction,
        raw_samples=raw_samples,
        selection=selection,
        allow_raw_samples=allow_raw_samples,
    )
    rendered = render_model_context(packages, selection=selection)
    write_output(out, rendered, force=force)
    return rendered


__all__ = [
    "build_cli_model_context",
    "model_context_command",
    "render_model_context",
    "render_model_run_report",
]
