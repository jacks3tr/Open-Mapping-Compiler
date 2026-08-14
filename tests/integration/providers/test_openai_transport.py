"""Local HTTP integration tests for the OpenAI Responses transport."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ProviderKind
from open_mapping.providers.transports import base as transport_base
from tests.integration.providers.model_transport_support import (
    LocalJsonServer,
    ScriptedResponse,
    fixed_payload,
    fixed_request,
    invoke,
)


@pytest.fixture(autouse=True)
def provider_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("MODEL_ROUTE", "route-value")
    yield


def test_openai_responses_request_and_result_are_provider_neutral() -> None:
    provider_payload = fixed_payload()
    response = {
        "id": "resp_123",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(provider_payload, separators=(",", ":")),
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 41, "output_tokens": 17},
    }
    with LocalJsonServer(ScriptedResponse(200, response)) as server:
        request = fixed_request(ProviderKind.OPENAI, server.base_url)
        result = invoke(request)

    assert len(server.requests) == 1
    recorded = server.requests[0]
    assert recorded.path == "/v1/responses"
    assert recorded.headers["authorization"] == "Bearer secret-key"
    assert recorded.headers["x-route"] == "route-value"
    assert recorded.body == {
        "model": "model-fixed",
        "instructions": request.prompt.system_instruction,
        "input": request.prompt.user_payload_json,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "open_mapping_response",
                "schema": request.prompt.response_schema,
                "strict": True,
            }
        },
        "max_output_tokens": 321,
        "temperature": 0.2,
        "top_p": 0.8,
    }
    assert result.payload == provider_payload
    assert result.provider_request_id == "resp_123"
    assert result.usage.model_dump() == {"input_tokens": 41, "output_tokens": 17}
    assert len(result.response_sha256) == 64


def test_openai_missing_credential_is_rejected_before_any_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalJsonServer() as server:
        request = fixed_request(ProviderKind.OPENAI, server.base_url)
        monkeypatch.delenv("MODEL_API_KEY")
        with pytest.raises(OpenMappingError, match="MODEL_API_KEY.*is not set"):
            invoke(request)
    assert server.requests == []


@pytest.mark.parametrize(
    "provider_response",
    [
        {
            "id": "resp_invalid",
            "output": [{"content": [{"type": "output_text", "text": "not-json-secret"}]}],
        },
        {"id": "resp_missing", "output": [{"content": [{"type": "refusal", "refusal": "no"}]}]},
    ],
)
def test_openai_rejects_invalid_or_missing_structured_output_without_exposing_it(
    provider_response: dict[str, object],
) -> None:
    with LocalJsonServer(ScriptedResponse(200, provider_response)) as server:
        request = fixed_request(ProviderKind.OPENAI, server.base_url)
        with pytest.raises(OpenMappingError, match="structured response") as raised:
            invoke(request)
    assert "not-json-secret" not in str(raised.value)


def test_openai_enforces_request_and_response_size_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    with LocalJsonServer(ScriptedResponse(200, b"{" + b"x" * 64 + b"}")) as server:
        request = fixed_request(ProviderKind.OPENAI, server.base_url)
        monkeypatch.setattr(transport_base, "MAX_REQUEST_BODY_BYTES", 32)
        with pytest.raises(OpenMappingError, match="request exceeds 8 MiB"):
            invoke(request)
        assert server.requests == []

        monkeypatch.setattr(transport_base, "MAX_REQUEST_BODY_BYTES", 8 * 1024 * 1024)
        monkeypatch.setattr(transport_base, "MAX_RESPONSE_BODY_BYTES", 32)
        with pytest.raises(OpenMappingError, match="response exceeds 4 MiB"):
            invoke(request)


def test_openai_retries_transient_status_and_honors_bounded_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(transport_base, "sleep", waits.append)
    success = {
        "id": "resp_retry",
        "output": [{"content": [{"type": "output_text", "text": json.dumps(fixed_payload())}]}],
    }
    with LocalJsonServer(
        ScriptedResponse(429, {"error": "do-not-expose"}, {"Retry-After": "0.5"}),
        ScriptedResponse(200, success),
    ) as server:
        result = invoke(fixed_request(ProviderKind.OPENAI, server.base_url, max_retries=9))
    assert result.provider_request_id == "resp_retry"
    assert len(server.requests) == 2
    assert waits == [0.5]


def test_openai_retries_timeouts_only_up_to_the_configured_cap() -> None:
    responses = tuple(ScriptedResponse(200, {}, delay_seconds=0.08) for _ in range(3))
    with LocalJsonServer(*responses) as server:
        request = fixed_request(
            ProviderKind.OPENAI,
            server.base_url,
            timeout_seconds=0.01,
            max_retries=9,
        )
        with pytest.raises(OpenMappingError, match="request failed"):
            invoke(request)
    assert len(server.requests) == 3


def test_openai_never_retries_permanent_client_errors() -> None:
    with LocalJsonServer(ScriptedResponse(400, {"error": "secret-body"})) as server:
        request = fixed_request(ProviderKind.OPENAI, server.base_url, max_retries=2)
        with pytest.raises(OpenMappingError, match="request failed") as raised:
            invoke(request)
    assert len(server.requests) == 1
    assert "secret-body" not in str(raised.value)


@pytest.mark.parametrize(
    "parameters,unsupported_name",
    [({"seed": 7}, "seed"), ({"reasoning_effort": "high"}, "reasoning_effort")],
)
def test_openai_rejects_parameters_without_a_supported_responses_api_mapping(
    parameters: Mapping[str, object], unsupported_name: str
) -> None:
    with LocalJsonServer() as server:
        request = fixed_request(
            ProviderKind.OPENAI,
            server.base_url,
            parameters=parameters,
        )
        with pytest.raises(OpenMappingError, match=unsupported_name):
            invoke(request)
    assert server.requests == []
