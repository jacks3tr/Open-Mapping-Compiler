"""Provider-neutral model transport registry tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ModelProviderConfig, ProviderKind, ResolvedModel
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelTargetRequest,
    mapping_context_sha256,
)
from open_mapping.providers.config import resolve_model
from open_mapping.providers.prompt import ModelPrompt, build_model_prompt
from open_mapping.providers.protocol import (
    ModelTransportRequest,
    ProviderCallResult,
    ProviderProposal,
    ProviderRequest,
    ProviderResponse,
)
from open_mapping.providers.registry import build_transport_registry
from open_mapping.providers.transports import base as transport_base
from open_mapping.providers.transports.base import (
    ModelTransport,
    bounded_retry_count,
    call_with_transient_retries,
    encode_bounded_json_body,
    provider_timeout_seconds,
    read_bounded_response_body,
    resolve_transport_credentials,
    sanitize_headers,
    stable_transport_failure,
)
from open_mapping.providers.transports.custom_http import CustomHttpTransport
from open_mapping.providers.transports.openai import OpenAITransport
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _resolved_model(kind: ProviderKind) -> ResolvedModel:
    provider: dict[str, object] = {"kind": kind.value}
    if kind in {ProviderKind.OPENAI, ProviderKind.ANTHROPIC, ProviderKind.GOOGLE}:
        provider["api_key_env"] = "OPEN_MAPPING_TEST_API_KEY"
    if kind in {ProviderKind.OPENAI_COMPATIBLE, ProviderKind.CUSTOM_HTTP}:
        provider["base_url"] = "http://127.0.0.1:8080/v1"
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {"provider": provider},
            "models": {"mapper": {"provider": "provider", "model_id": "fixed-model"}},
        }
    )
    return resolve_model(config, "mapper")


def _resolved_openai_model(
    *, max_retries: int = 1, headers_from_env: dict[str, str] | None = None
) -> ResolvedModel:
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {
                "provider": {
                    "kind": "openai",
                    "api_key_env": "OPEN_MAPPING_TEST_API_KEY",
                    "headers_from_env": headers_from_env or {},
                    "max_retries": max_retries,
                }
            },
            "models": {"mapper": {"provider": "provider", "model_id": "fixed-model"}},
        }
    )
    return resolve_model(config, "mapper")


def _custom_http_request() -> ModelTransportRequest:
    source_field = ModelFieldSummary(
        pointer="/source_name",
        types=("string",),
        required=True,
        description="Source display name",
    )
    target_field = ModelFieldSummary(
        pointer="/display_name",
        types=("string",),
        required=True,
        description="Target display name",
    )
    package = MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id="batch-fixed",
        context_mode="targeted",
        source_schema_id="source",
        source_schema_version="1",
        target_schema_id="target",
        target_schema_version="1",
        source_fields=(source_field,),
        target_requests=(
            ModelTargetRequest(
                target=target_field,
                candidates=(
                    ModelCandidateSummary(
                        source_path="/source_name",
                        raw_score=0.9,
                        evidence=("same semantic name",),
                    ),
                ),
            ),
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=("get",),
        allowed_source_paths=("/source_name",),
        raw_samples=None,
    )
    return ModelTransportRequest(
        resolved_model=_resolved_model(ProviderKind.CUSTOM_HTTP),
        prompt=build_model_prompt(package),
    )


def _resolved_custom_http_model_with_boundary_settings() -> ResolvedModel:
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {
                "provider": {
                    "kind": "custom-http",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "headers_from_env": {"X-Provider-Token": "OPEN_MAPPING_CUSTOM_HEADER"},
                    "timeout_seconds": 7,
                    "max_retries": 99,
                }
            },
            "models": {"mapper": {"provider": "provider", "model_id": "fixed-model"}},
        }
    )
    return resolve_model(config, "mapper")


@pytest.mark.parametrize("provider_kind", tuple(ProviderKind))
def test_every_configured_provider_kind_resolves_to_a_synchronous_transport(
    provider_kind: ProviderKind,
) -> None:
    registry = build_transport_registry()

    transport = registry[provider_kind](_resolved_model(provider_kind))

    assert set(registry) == set(ProviderKind)
    assert isinstance(transport, ModelTransport)


def test_unknown_provider_kind_cannot_enter_the_transport_registry_through_config_validation() -> (
    None
):
    with pytest.raises(ValidationError, match="ProviderKind|Input should be"):
        ModelProviderConfig.model_validate(
            {
                "config_version": "0.1",
                "providers": {"unknown": {"kind": "not-a-provider"}},
                "models": {"mapper": {"provider": "unknown", "model_id": "fixed-model"}},
            }
        )


def test_legacy_provider_requests_omit_the_new_model_prompt_field_when_unused() -> None:
    request = ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="source",
        target_schema_id="target",
        target_path="/target",
        candidates=(),
        source_field_metadata=(),
        target_field_metadata={
            "pointer": "/target",
            "types": ["string"],
            "required": True,
        },
        sample_profiles=(),
    )

    assert "model_prompt" not in request.model_dump(mode="json")


def test_native_factory_defers_credential_resolution_until_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = _resolved_model(ProviderKind.OPENAI)
    monkeypatch.delenv("OPEN_MAPPING_TEST_API_KEY", raising=False)

    transport = build_transport_registry()[ProviderKind.OPENAI](resolved)

    request = ModelTransportRequest(
        resolved_model=resolved,
        prompt=ModelPrompt(
            prompt_version="mapping-agent-v1",
            system_instruction="fixed instruction",
            user_payload_json="{}",
            response_schema={},
        ),
    )
    with pytest.raises(OpenMappingError, match="OPEN_MAPPING_TEST_API_KEY.*is not set"):
        transport.invoke(request)
    assert isinstance(transport, OpenAITransport)


def test_credential_headers_are_resolved_fresh_and_sanitized_at_the_transport_boundary() -> None:
    resolved = _resolved_openai_model(headers_from_env={"X-Provider-Token": "TEST_HEADER"})

    first = resolve_transport_credentials(
        resolved,
        environment={"OPEN_MAPPING_TEST_API_KEY": "first-key", "TEST_HEADER": "first-header"},
    )
    second = resolve_transport_credentials(
        resolved,
        environment={"OPEN_MAPPING_TEST_API_KEY": "rotated-key", "TEST_HEADER": "rotated-header"},
    )

    assert first.api_key == "first-key"
    assert dict(first.headers) == {"X-Provider-Token": "first-header"}
    assert second.api_key == "rotated-key"
    assert dict(second.headers) == {"X-Provider-Token": "rotated-header"}
    with pytest.raises(OpenMappingError, match="line break"):
        sanitize_headers({"X-Provider-Token": "value\r\nInjected: value"})


def test_shared_body_limits_and_retry_boundaries_are_enforced() -> None:
    original_request_limit = transport_base.MAX_REQUEST_BODY_BYTES
    original_response_limit = transport_base.MAX_RESPONSE_BODY_BYTES
    transport_base.MAX_REQUEST_BODY_BYTES = 4
    transport_base.MAX_RESPONSE_BODY_BYTES = 4
    try:
        with pytest.raises(OpenMappingError, match="request exceeds 8 MiB"):
            encode_bounded_json_body({"a": "too long"})
        with pytest.raises(OpenMappingError, match="response exceeds 4 MiB"):
            read_bounded_response_body((b"abc", b"def"))
    finally:
        transport_base.MAX_REQUEST_BODY_BYTES = original_request_limit
        transport_base.MAX_RESPONSE_BODY_BYTES = original_response_limit

    attempts = 0
    sleeps: list[float] = []

    class TransientFailure(Exception):
        pass

    def fail_transiently() -> None:
        nonlocal attempts
        attempts += 1
        raise TransientFailure("temporary")

    with pytest.raises(TransientFailure):
        call_with_transient_retries(
            fail_transiently,
            max_retries=99,
            is_transient=lambda error: isinstance(error, TransientFailure),
            retry_after_seconds=lambda _error: 0.5,
            sleep_fn=sleeps.append,
        )

    assert attempts == 3
    assert sleeps == [0.5, 0.5]
    assert bounded_retry_count(_resolved_openai_model(max_retries=99)) == 2
    assert provider_timeout_seconds(_resolved_openai_model()) == 120

    retry_after_attempts = 0

    def eventually_succeeds() -> str:
        nonlocal retry_after_attempts
        retry_after_attempts += 1
        if retry_after_attempts == 1:
            raise TransientFailure("temporary")
        return "ok"

    assert (
        call_with_transient_retries(
            eventually_succeeds,
            max_retries=1,
            is_transient=lambda error: isinstance(error, TransientFailure),
            retry_after_seconds=lambda _error: 11,
            sleep_fn=sleeps.append,
        )
        == "ok"
    )
    assert sleeps == [0.5, 0.5]


def test_nontransient_failures_are_not_retried_or_exposed_as_response_text() -> None:
    attempts = 0

    def fail_permanently() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("raw response text that must not escape")

    with pytest.raises(ValueError):
        call_with_transient_retries(
            fail_permanently,
            max_retries=2,
            is_transient=lambda _error: False,
        )

    converted = stable_transport_failure(ValueError("raw response text that must not escape"))
    assert attempts == 1
    assert "raw response text" not in str(converted)


def test_custom_http_transport_adapts_the_legacy_provider_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPEN_MAPPING_CUSTOM_HEADER", "header-value")
    request = _custom_http_request().model_copy(
        update={"resolved_model": _resolved_custom_http_model_with_boundary_settings()}
    )
    legacy_requests: list[ProviderRequest] = []

    def legacy_call(
        url: str,
        *,
        token_env: str | None,
        request: ProviderRequest,
        allow_raw_samples: bool,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_retries: int,
    ) -> ProviderCallResult:
        assert url == "http://127.0.0.1:8080/v1"
        assert token_env is None
        assert allow_raw_samples is False
        assert dict(headers) == {"X-Provider-Token": "header-value"}
        assert timeout_seconds == 7
        assert max_retries == 2
        legacy_requests.append(request)
        return ProviderCallResult(
            response=ProviderResponse(
                protocol_version="0.1",
                proposals=(
                    ProviderProposal(
                        target_path="/display_name",
                        abstain=False,
                        selected_source_paths=("/source_name",),
                        expression={"op": "get", "path": "/source_name"},
                        reason="same semantic name",
                    ),
                ),
            ),
            disclosure={
                "endpoint_origin": "127.0.0.1:8080",
                "raw_samples_included": False,
                "source_field_count": 1,
                "candidate_count": 1,
                "sample_profile_count": 0,
                "redaction_count": 0,
                "request_sha256": "0" * 64,
            },
        )

    monkeypatch.setattr(
        "open_mapping.providers.transports.custom_http.call_http_provider", legacy_call
    )

    transport = build_transport_registry()[ProviderKind.CUSTOM_HTTP](request.resolved_model)
    result = transport.invoke(request)
    payload = ModelMappingResponse.model_validate(result.payload)

    assert isinstance(transport, CustomHttpTransport)
    assert len(legacy_requests) == 1
    assert legacy_requests[0].task == "rerank-and-propose"
    assert legacy_requests[0].target_path == "/display_name"
    assert legacy_requests[0].instruction_text == request.prompt.system_instruction
    assert legacy_requests[0].model_prompt == request.prompt
    assert payload.batch_id == "batch-fixed"
    assert payload.context_sha256 == mapping_context_sha256(
        MappingContextPackage.model_validate_json(request.prompt.user_payload_json)
    )
    assert payload.proposals[0].selected_source_paths == ("/source_name",)
    assert result.provider_request_id is None
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert (
        result.response_sha256
        == hashlib.sha256(canonical_json_bytes(payload.model_dump(mode="json"))).hexdigest()
    )
