"""Cross-module model invocation behavior with a deterministic fake transport."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ModelProviderConfig, ProviderKind, ResolvedModel
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelTargetRequest,
    mapping_context_sha256,
)
from open_mapping.providers.config import resolve_model
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.protocol import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResult,
    ModelUsage,
    TransportFactory,
)
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _resolved_model() -> ResolvedModel:
    return resolve_model(
        ModelProviderConfig.model_validate(
            {
                "config_version": "0.1",
                "providers": {
                    "fake": {
                        "kind": "openai-compatible",
                        "base_url": "http://127.0.0.1:8080/v1",
                    }
                },
                "models": {"mapper": {"provider": "fake", "model_id": "fake-model"}},
            }
        ),
        "mapper",
    )


def _package(batch_id: str, target_path: str) -> MappingContextPackage:
    return MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id=batch_id,
        context_mode="targeted",
        source_schema_id="source",
        source_schema_version="1",
        target_schema_id="target",
        target_schema_version="1",
        source_fields=(ModelFieldSummary(pointer="/source", types=("string",), required=True),),
        target_requests=(
            ModelTargetRequest(
                target=ModelFieldSummary(pointer=target_path, types=("string",), required=True),
                candidates=(),
            ),
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=("literal",),
        allowed_source_paths=(),
        raw_samples=None,
    )


def _payload(package: MappingContextPackage, *, abstain: bool = False) -> JsonValue:
    proposal: dict[str, object]
    if abstain:
        proposal = {
            "target_path": package.target_requests[0].target.pointer,
            "action": "abstain",
            "selected_source_paths": [],
            "expression": None,
            "reason": "uncertain",
            "evidence": [],
        }
    else:
        proposal = {
            "target_path": package.target_requests[0].target.pointer,
            "action": "propose",
            "selected_source_paths": [],
            "expression": {"op": "literal", "value": "fixed"},
            "reason": "fixed business constant",
            "evidence": ["business instruction"],
        }
    return cast(
        JsonValue,
        {
            "protocol_version": "0.1",
            "prompt_version": "mapping-agent-v1",
            "context_sha256": mapping_context_sha256(package),
            "batch_id": package.batch_id,
            "proposals": [proposal],
        },
    )


def _result(payload: JsonValue) -> ModelTransportResult:
    return ModelTransportResult(
        payload=payload,
        provider_request_id="not-persisted",
        usage=ModelUsage(input_tokens=3, output_tokens=2),
        latency_ms=1,
        response_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )


@dataclass
class _FakeTransport:
    script: list[ModelTransportResult | Exception]
    requests: list[ModelTransportRequest] = field(default_factory=list)

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        self.requests.append(request)
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _registry(transport: _FakeTransport) -> Mapping[ProviderKind, TransportFactory]:
    def factory(_resolved: ResolvedModel) -> ModelTransport:
        return transport

    return {ProviderKind.OPENAI_COMPATIBLE: factory}


def test_batches_are_deterministic_and_partial_failures_preserve_successes() -> None:
    first = _package("batch-a", "/a")
    failed = _package("batch-b", "/b")
    abstained = _package("batch-c", "/c")
    raw_secret = "provider-body-that-must-not-escape"
    transport = _FakeTransport(
        [
            _result(_payload(first)),
            RuntimeError(raw_secret),
            _result(_payload(abstained, abstain=True)),
        ]
    )

    responses, disclosure, issues = invoke_model_mapping(
        packages=(abstained, failed, first),
        resolved_model=_resolved_model(),
        config_sha256="d" * 64,
        registry=_registry(transport),
    )

    request_packages = tuple(
        MappingContextPackage.model_validate_json(request.prompt.user_payload_json)
        for request in transport.requests
    )
    assert tuple(package.batch_id for package in request_packages) == (
        "batch-a",
        "batch-b",
        "batch-c",
    )
    assert tuple(response.batch_id for response in responses) == ("batch-a", "batch-c")
    assert tuple(run.batch_id for run in disclosure.batch_runs) == (
        "batch-a",
        "batch-b",
        "batch-c",
    )
    assert disclosure.batch_runs[1].response is None
    assert disclosure.batch_runs[2].response == ModelMappingResponse.model_validate(
        _payload(abstained, abstain=True)
    )
    assert len(issues) == 1
    assert raw_secret not in str(issues)
    assert raw_secret not in disclosure.model_dump_json()
