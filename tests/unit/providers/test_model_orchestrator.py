"""Deterministic model invocation, repair, and disclosure tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ModelProviderConfig, ProviderKind, ResolvedModel
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelTargetRequest,
    mapping_context_sha256,
)
from open_mapping.model.providers import ModelRunDisclosure
from open_mapping.providers.config import resolve_model
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.prompt import build_model_prompt
from open_mapping.providers.protocol import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResult,
    ModelUsage,
    TransportFactory,
)
from open_mapping.providers.transports.base import normalized_model_payload
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _resolved_model() -> ResolvedModel:
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {
                "local": {
                    "kind": "openai-compatible",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "api_key_env": None,
                }
            },
            "models": {
                "mapper": {
                    "provider": "local",
                    "model_id": "fixed-model",
                    "context_mode": "targeted",
                }
            },
        }
    )
    return resolve_model(config, "mapper")


def _package(
    batch_id: str = "batch-a",
    *,
    target_paths: tuple[str, ...] = ("/display_name",),
) -> MappingContextPackage:
    return MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id=batch_id,
        context_mode="targeted",
        source_schema_id="source",
        source_schema_version="1",
        target_schema_id="target",
        target_schema_version="1",
        source_fields=(
            ModelFieldSummary(pointer="/source_name", types=("string",), required=True),
        ),
        target_requests=tuple(
            ModelTargetRequest(
                target=ModelFieldSummary(pointer=target, types=("string",), required=True),
                candidates=(
                    ModelCandidateSummary(
                        source_path="/source_name",
                        raw_score=0.9,
                        evidence=("same semantic name",),
                    ),
                ),
            )
            for target in target_paths
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=("get", "literal", "divide"),
        allowed_source_paths=("/source_name",),
        raw_samples=None,
        redaction_count=2,
    )


def _response_payload(
    package: MappingContextPackage,
    *,
    abstain: bool = False,
) -> dict[str, object]:
    proposals: list[dict[str, object]] = []
    for request in package.target_requests:
        if abstain:
            proposals.append(
                {
                    "target_path": request.target.pointer,
                    "action": "abstain",
                    "selected_source_paths": [],
                    "expression": None,
                    "reason": "context is insufficient",
                    "evidence": [],
                }
            )
        else:
            proposals.append(
                {
                    "target_path": request.target.pointer,
                    "action": "propose",
                    "selected_source_paths": ["/source_name"],
                    "expression": {"op": "get", "path": "/source_name"},
                    "reason": "same semantic field",
                    "evidence": ["names and types align"],
                }
            )
    return {
        "protocol_version": "0.1",
        "prompt_version": "mapping-agent-v1",
        "context_sha256": mapping_context_sha256(package),
        "batch_id": package.batch_id,
        "proposals": proposals,
    }


def _result(
    payload: JsonValue,
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    latency_ms: int = 7,
) -> ModelTransportResult:
    return ModelTransportResult(
        payload=payload,
        provider_request_id="request-secret-not-disclosed",
        usage=ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        latency_ms=latency_ms,
        response_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )


@dataclass
class _ScriptedTransport:
    script: list[ModelTransportResult | Exception]
    requests: list[ModelTransportRequest] = field(default_factory=list)

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _registry(transport: _ScriptedTransport) -> Mapping[ProviderKind, TransportFactory]:
    def factory(resolved_model: ResolvedModel) -> ModelTransport:
        assert resolved_model == _resolved_model()
        return transport

    return {ProviderKind.OPENAI_COMPATIBLE: factory}


def _invoke(
    package: MappingContextPackage,
    transport: _ScriptedTransport,
) -> tuple[
    tuple[ModelMappingResponse, ...],
    ModelRunDisclosure,
    tuple[Issue, ...],
]:
    return invoke_model_mapping(
        packages=(package,),
        resolved_model=_resolved_model(),
        config_sha256="c" * 64,
        registry=_registry(transport),
    )


def test_first_pass_success_records_attributable_bounded_metadata() -> None:
    package = _package()
    payload = cast(JsonValue, _response_payload(package))
    transport = _ScriptedTransport([_result(payload)])

    responses, disclosure, issues = _invoke(package, transport)

    assert issues == ()
    assert responses == (ModelMappingResponse.model_validate(payload),)
    assert disclosure.model_alias == "mapper"
    assert disclosure.provider_name == "local"
    assert disclosure.provider_kind is ProviderKind.OPENAI_COMPATIBLE
    assert disclosure.model_id == "fixed-model"
    assert disclosure.config_sha256 == "c" * 64
    assert disclosure.raw_samples_included is False
    assert disclosure.redaction_count == 2
    (run,) = disclosure.batch_runs
    assert run.batch_id == package.batch_id
    assert run.context_sha256 == mapping_context_sha256(package)
    assert run.response_sha256 == hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    assert run.response == responses[0]
    assert run.issues == ()
    assert run.attempts == 1
    assert run.format_repairs == 0
    assert run.usage == ModelUsage(input_tokens=10, output_tokens=5)
    assert run.latency_ms == 7


def test_structural_schema_failure_gets_one_bounded_format_repair() -> None:
    package = _package(target_paths=("/display_name", "/legal_name"))
    invalid = _response_payload(package)
    first_proposal = cast(dict[str, object], cast(list[object], invalid["proposals"])[0])
    first_proposal.pop("evidence")
    repaired = _response_payload(package)
    transport = _ScriptedTransport(
        [
            _result(cast(JsonValue, invalid), input_tokens=11, output_tokens=3, latency_ms=4),
            _result(cast(JsonValue, repaired), input_tokens=7, output_tokens=5, latency_ms=6),
        ]
    )

    responses, disclosure, issues = _invoke(package, transport)

    assert issues == ()
    assert responses == (ModelMappingResponse.model_validate(repaired),)
    assert len(transport.requests) == 2
    repair_prompt = transport.requests[1].prompt
    repair_payload = json.loads(repair_prompt.user_payload_json)
    assert repair_payload["task"] == "repair-model-mapping-response"
    assert repair_payload["protocol_version"] == package.protocol_version
    assert repair_payload["prompt_version"] == package.prompt_version
    assert repair_payload["batch_id"] == package.batch_id
    assert repair_payload["context_sha256"] == mapping_context_sha256(package)
    assert repair_payload["requested_target_paths"] == ["/display_name", "/legal_name"]
    assert repair_payload["invalid_response"] == invalid
    assert repair_payload["response_schema"] == build_model_prompt(package).response_schema
    assert 1 <= len(repair_payload["validation_errors"]) <= 8
    assert all(len(message) <= 300 for message in repair_payload["validation_errors"])
    assert "Do not change" in repair_prompt.system_instruction
    (run,) = disclosure.batch_runs
    assert run.attempts == 2
    assert run.format_repairs == 1
    assert run.usage == ModelUsage(input_tokens=18, output_tokens=8)
    assert run.latency_ms == 10
    assert (
        run.response_sha256
        == hashlib.sha256(canonical_json_bytes(cast(JsonValue, repaired))).hexdigest()
    )


def test_second_schema_failure_is_not_repaired_again() -> None:
    package = _package()
    first = _response_payload(package)
    cast(dict[str, object], cast(list[object], first["proposals"])[0]).pop("evidence")
    second = _response_payload(package)
    cast(dict[str, object], cast(list[object], second["proposals"])[0]).pop("reason")
    transport = _ScriptedTransport(
        [_result(cast(JsonValue, first)), _result(cast(JsonValue, second))]
    )

    responses, disclosure, issues = _invoke(package, transport)

    assert responses == ()
    assert len(transport.requests) == 2
    assert [issue.code for issue in issues] == [IssueCode.PROVIDER_RESPONSE_INVALID]
    (run,) = disclosure.batch_runs
    assert run.response is None
    assert run.attempts == 2
    assert run.format_repairs == 1
    assert run.issues == issues


@pytest.mark.parametrize("identity_field", ("context_sha256", "batch_id", "target_path"))
def test_repair_cannot_change_identity_or_requested_target_coverage(
    identity_field: str,
) -> None:
    package = _package()
    invalid = _response_payload(package)
    proposal = cast(dict[str, object], cast(list[object], invalid["proposals"])[0])
    proposal.pop("evidence")
    if identity_field == "target_path":
        proposal["target_path"] = "/different"
    else:
        invalid[identity_field] = "different"
    transport = _ScriptedTransport(
        [
            _result(cast(JsonValue, invalid)),
            _result(cast(JsonValue, _response_payload(package))),
        ]
    )

    responses, disclosure, issues = _invoke(package, transport)

    assert responses == ()
    assert len(transport.requests) == 1
    assert [issue.code for issue in issues] == [IssueCode.PROVIDER_RESPONSE_INVALID]
    (run,) = disclosure.batch_runs
    assert run.attempts == 1
    assert run.format_repairs == 0


def test_semantically_invalid_response_is_rejected_without_format_repair() -> None:
    package = _package()
    payload = _response_payload(package)
    proposal = cast(dict[str, object], cast(list[object], payload["proposals"])[0])
    proposal["selected_source_paths"] = ["/outside"]
    proposal["expression"] = {"op": "get", "path": "/outside"}
    transport = _ScriptedTransport([_result(cast(JsonValue, payload))])

    responses, disclosure, issues = _invoke(package, transport)

    assert responses == ()
    assert len(transport.requests) == 1
    assert {issue.message for issue in issues} == {
        "expression reads a source path that is not allowed",
        "selected source path is not allowed",
    }
    (run,) = disclosure.batch_runs
    assert run.attempts == 1
    assert run.format_repairs == 0


def test_statically_invalid_typed_expression_is_left_for_later_verification() -> None:
    package = _package()
    payload = _response_payload(package)
    proposal = cast(dict[str, object], cast(list[object], payload["proposals"])[0])
    proposal["selected_source_paths"] = []
    proposal["expression"] = {
        "op": "divide",
        "left": {"op": "literal", "value": 1},
        "right": {"op": "literal", "value": 0},
    }
    transport = _ScriptedTransport([_result(cast(JsonValue, payload))])

    responses, disclosure, issues = _invoke(package, transport)

    assert len(responses) == 1
    assert issues == ()
    assert len(transport.requests) == 1
    assert disclosure.batch_runs[0].format_repairs == 0


def test_invalid_json_transport_failure_is_not_repaired() -> None:
    package = _package()
    failure = OpenMappingError(
        (
            Issue(
                code=IssueCode.PROVIDER_RESPONSE_INVALID,
                severity=Severity.ERROR,
                component="providers.fake",
                message="model provider returned invalid JSON",
                correction="Return one JSON object.",
            ),
        )
    )
    transport = _ScriptedTransport([failure, _result(cast(JsonValue, _response_payload(package)))])

    responses, disclosure, issues = _invoke(package, transport)

    assert responses == ()
    assert len(transport.requests) == 1
    assert issues == failure.issues
    assert disclosure.batch_runs[0].format_repairs == 0


def test_disclosure_never_contains_raw_provider_text_request_id_or_credentials() -> None:
    package = _package()
    secret = "raw-provider-text-SUPER-SECRET"
    transport = _ScriptedTransport([RuntimeError(secret)])

    responses, disclosure, issues = _invoke(package, transport)

    serialized = disclosure.model_dump_json()
    assert responses == ()
    assert [issue.code for issue in issues] == [IssueCode.PROVIDER_FAILURE]
    assert secret not in serialized
    assert secret not in str(issues)
    assert "request-secret-not-disclosed" not in serialized
    assert "api_key" not in serialized


def test_transport_normalization_defers_shared_schema_validation_to_orchestrator() -> None:
    structurally_invalid = {"protocol_version": "0.1"}

    assert (
        normalized_model_payload(json.dumps(structurally_invalid), component="providers.fake")
        == structurally_invalid
    )
