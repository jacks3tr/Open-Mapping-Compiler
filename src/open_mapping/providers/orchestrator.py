"""Deterministic model invocation, structural repair, and provenance."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ProviderKind, ResolvedModel
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelMappingResponse,
    mapping_context_sha256,
    validate_model_mapping_response,
)
from open_mapping.model.providers import ModelBatchRun, ModelRunDisclosure, ModelUsage
from open_mapping.providers.prompt import build_model_prompt, build_model_repair_prompt
from open_mapping.providers.protocol import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResult,
    TransportFactory,
)
from open_mapping.serialization.canonical_json import canonical_json_bytes

_COMPONENT = "providers.orchestrator"
_CORRECTION = "Continue with deterministic baseline suggestions or retry a configured model."
_MAX_DISCLOSED_COUNT = 2_147_483_647


def _issue(
    *,
    code: IssueCode,
    batch_id: str,
    message: str,
    correction: str = _CORRECTION,
) -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component=_COMPONENT,
        message=f"model batch {batch_id!r} {message}",
        correction=correction,
    )


def _failure_issues(error: Exception, *, batch_id: str) -> tuple[Issue, ...]:
    if isinstance(error, OpenMappingError):
        return error.issues
    return (
        _issue(
            code=IssueCode.PROVIDER_FAILURE,
            batch_id=batch_id,
            message="provider invocation failed",
        ),
    )


def _schema_issue(batch_id: str) -> Issue:
    return _issue(
        code=IssueCode.PROVIDER_RESPONSE_INVALID,
        batch_id=batch_id,
        message="response does not match the shared response schema",
        correction="Return one JSON object that exactly matches the shared response schema.",
    )


def _payload_bytes(payload: JsonValue) -> bytes | None:
    try:
        return canonical_json_bytes(payload)
    except (TypeError, ValueError, UnicodeError):
        return None


def _payload_sha256(payload_bytes: bytes | None) -> str | None:
    return None if payload_bytes is None else hashlib.sha256(payload_bytes).hexdigest()


def _strict_response(
    payload_bytes: bytes,
) -> tuple[ModelMappingResponse | None, ValidationError | None]:
    try:
        return ModelMappingResponse.model_validate_json(payload_bytes, strict=True), None
    except ValidationError as error:
        return None, error


def _bounded_validation_errors(error: ValidationError) -> tuple[str, ...]:
    messages: list[str] = []
    for detail in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )[:8]:
        location = ".".join(str(part) for part in detail["loc"]) or "response"
        messages.append(f"{location}: {detail['msg']} [{detail['type']}]"[:300])
    return tuple(messages)


def _repair_preserves_authority(
    payload: JsonValue,
    *,
    package: MappingContextPackage,
) -> bool:
    if not isinstance(payload, dict):
        return False
    expected_identity: tuple[tuple[str, object], ...] = (
        ("protocol_version", package.protocol_version),
        ("prompt_version", package.prompt_version),
        ("context_sha256", mapping_context_sha256(package)),
        ("batch_id", package.batch_id),
    )
    if any(payload.get(name) != expected for name, expected in expected_identity):
        return False
    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        return False
    target_paths: list[str] = []
    for proposal in proposals:
        if not isinstance(proposal, dict) or not isinstance(proposal.get("target_path"), str):
            return False
        target_paths.append(proposal["target_path"])
    expected_targets = [request.target.pointer for request in package.target_requests]
    return target_paths == expected_targets


def _bounded_sum(values: Sequence[int | None]) -> int | None:
    present = [value for value in values if value is not None and value >= 0]
    if not present:
        return None
    return min(sum(present), _MAX_DISCLOSED_COUNT)


def _combined_usage(results: Sequence[ModelTransportResult]) -> ModelUsage:
    return ModelUsage(
        input_tokens=_bounded_sum([result.usage.input_tokens for result in results]),
        output_tokens=_bounded_sum([result.usage.output_tokens for result in results]),
    )


def _combined_latency(results: Sequence[ModelTransportResult]) -> int:
    return min(
        sum(max(0, result.latency_ms) for result in results),
        _MAX_DISCLOSED_COUNT,
    )


def _batch_run(
    *,
    package: MappingContextPackage,
    results: Sequence[ModelTransportResult],
    response_sha256: str | None,
    response: ModelMappingResponse | None,
    issues: Sequence[Issue],
    attempts: int,
    format_repairs: int,
) -> ModelBatchRun:
    return ModelBatchRun(
        batch_id=package.batch_id,
        context_sha256=mapping_context_sha256(package),
        response_sha256=response_sha256,
        response=response,
        issues=sort_issues(issues),
        attempts=attempts,
        format_repairs=format_repairs,
        usage=_combined_usage(results),
        latency_ms=_combined_latency(results),
    )


def _invoke_batch(
    *,
    package: MappingContextPackage,
    resolved_model: ResolvedModel,
    transport: ModelTransport,
) -> tuple[ModelMappingResponse | None, ModelBatchRun]:
    results: list[ModelTransportResult] = []
    attempts = 1
    format_repairs = 0
    try:
        first_result = transport.invoke(
            ModelTransportRequest(
                resolved_model=resolved_model,
                prompt=build_model_prompt(package),
            )
        )
    except Exception as error:
        issues = _failure_issues(error, batch_id=package.batch_id)
        return None, _batch_run(
            package=package,
            results=results,
            response_sha256=None,
            response=None,
            issues=issues,
            attempts=attempts,
            format_repairs=format_repairs,
        )

    results.append(first_result)
    current_result = first_result
    payload_bytes = _payload_bytes(current_result.payload)
    response_sha256 = _payload_sha256(payload_bytes)
    if payload_bytes is None:
        issues = (_schema_issue(package.batch_id),)
        return None, _batch_run(
            package=package,
            results=results,
            response_sha256=response_sha256,
            response=None,
            issues=issues,
            attempts=attempts,
            format_repairs=format_repairs,
        )

    response, validation_error = _strict_response(payload_bytes)
    if validation_error is not None:
        if not _repair_preserves_authority(current_result.payload, package=package):
            issues = (_schema_issue(package.batch_id),)
            return None, _batch_run(
                package=package,
                results=results,
                response_sha256=response_sha256,
                response=None,
                issues=issues,
                attempts=attempts,
                format_repairs=format_repairs,
            )
        try:
            repair_prompt = build_model_repair_prompt(
                package,
                invalid_response=current_result.payload,
                validation_errors=_bounded_validation_errors(validation_error),
            )
        except (TypeError, ValueError):
            issues = (_schema_issue(package.batch_id),)
            return None, _batch_run(
                package=package,
                results=results,
                response_sha256=response_sha256,
                response=None,
                issues=issues,
                attempts=attempts,
                format_repairs=format_repairs,
            )

        attempts = 2
        format_repairs = 1
        try:
            repaired_result = transport.invoke(
                ModelTransportRequest(
                    resolved_model=resolved_model,
                    prompt=repair_prompt,
                )
            )
        except Exception as error:
            issues = _failure_issues(error, batch_id=package.batch_id)
            return None, _batch_run(
                package=package,
                results=results,
                response_sha256=response_sha256,
                response=None,
                issues=issues,
                attempts=attempts,
                format_repairs=format_repairs,
            )
        results.append(repaired_result)
        current_result = repaired_result
        payload_bytes = _payload_bytes(current_result.payload)
        response_sha256 = _payload_sha256(payload_bytes)
        if payload_bytes is None:
            response = None
        else:
            response, _second_validation_error = _strict_response(payload_bytes)
        if response is None:
            issues = (_schema_issue(package.batch_id),)
            return None, _batch_run(
                package=package,
                results=results,
                response_sha256=response_sha256,
                response=None,
                issues=issues,
                attempts=attempts,
                format_repairs=format_repairs,
            )

    if response is None:
        raise AssertionError("strict response validation produced no result")
    semantic_issues = validate_model_mapping_response(response, package=package)
    if semantic_issues:
        return None, _batch_run(
            package=package,
            results=results,
            response_sha256=response_sha256,
            response=None,
            issues=semantic_issues,
            attempts=attempts,
            format_repairs=format_repairs,
        )
    return response, _batch_run(
        package=package,
        results=results,
        response_sha256=response_sha256,
        response=response,
        issues=(),
        attempts=attempts,
        format_repairs=format_repairs,
    )


def _factory_failure_runs(
    packages: Sequence[MappingContextPackage],
    *,
    error: Exception,
) -> tuple[ModelBatchRun, ...]:
    runs: list[ModelBatchRun] = []
    for package in packages:
        runs.append(
            _batch_run(
                package=package,
                results=(),
                response_sha256=None,
                response=None,
                issues=_failure_issues(error, batch_id=package.batch_id),
                attempts=0,
                format_repairs=0,
            )
        )
    return tuple(runs)


def invoke_model_mapping(
    *,
    packages: Sequence[MappingContextPackage],
    resolved_model: ResolvedModel,
    config_sha256: str,
    registry: Mapping[ProviderKind, TransportFactory],
) -> tuple[tuple[ModelMappingResponse, ...], ModelRunDisclosure, tuple[Issue, ...]]:
    """Invoke deterministic model batches and return only validated responses."""

    ordered_packages = tuple(
        sorted(
            packages,
            key=lambda package: (package.batch_id, mapping_context_sha256(package)),
        )
    )
    batch_runs: tuple[ModelBatchRun, ...]
    responses: list[ModelMappingResponse] = []
    if ordered_packages:
        try:
            factory = registry[resolved_model.provider.kind]
            transport = factory(resolved_model)
        except Exception as error:
            batch_runs = _factory_failure_runs(ordered_packages, error=error)
        else:
            mutable_runs: list[ModelBatchRun] = []
            for package in ordered_packages:
                response, run = _invoke_batch(
                    package=package,
                    resolved_model=resolved_model,
                    transport=transport,
                )
                mutable_runs.append(run)
                if response is not None:
                    responses.append(response)
            batch_runs = tuple(mutable_runs)
    else:
        batch_runs = ()

    prompt_version = ordered_packages[0].prompt_version if ordered_packages else "mapping-agent-v1"
    context_mode = (
        ordered_packages[0].context_mode if ordered_packages else resolved_model.model.context_mode
    )
    disclosure = ModelRunDisclosure(
        model_alias=resolved_model.alias,
        provider_name=resolved_model.provider_name,
        provider_kind=resolved_model.provider.kind,
        model_id=resolved_model.model.model_id,
        prompt_version=prompt_version,
        config_sha256=config_sha256,
        context_mode=context_mode,
        raw_samples_included=any(package.raw_samples_included for package in ordered_packages),
        redaction_count=min(
            sum(package.redaction_count for package in ordered_packages),
            _MAX_DISCLOSED_COUNT,
        ),
        batch_runs=batch_runs,
    )
    issues = sort_issues([issue for run in batch_runs for issue in run.issues])
    return tuple(responses), disclosure, issues


__all__ = ["invoke_model_mapping"]
