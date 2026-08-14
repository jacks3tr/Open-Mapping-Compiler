"""Local HTTP integration tests for OpenAI-compatible Chat Completions."""

from __future__ import annotations

import json

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ProviderKind, StructuredOutputMode
from tests.integration.providers import model_transport_support as support


@pytest.fixture(autouse=True)
def provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("MODEL_ROUTE", "route-value")


@pytest.mark.parametrize(
    "configured_mode,expected_format",
    [
        (
            StructuredOutputMode.AUTO,
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "open_mapping_response",
                    "strict": True,
                    "schema": "RESPONSE_SCHEMA",
                },
            },
        ),
        (
            StructuredOutputMode.JSON_SCHEMA,
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "open_mapping_response",
                    "strict": True,
                    "schema": "RESPONSE_SCHEMA",
                },
            },
        ),
        (StructuredOutputMode.JSON, {"type": "json_object"}),
    ],
)
def test_compatible_chat_completions_implements_each_response_mode(
    configured_mode: StructuredOutputMode,
    expected_format: dict[str, object],
) -> None:
    payload = support.fixed_payload()
    response = {
        "id": "chatcmpl_123",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 71, "completion_tokens": 29},
    }
    with support.LocalJsonServer(support.ScriptedResponse(200, response)) as server:
        request = support.fixed_request(
            ProviderKind.OPENAI_COMPATIBLE,
            server.base_url,
            structured_output=configured_mode,
        )
        result = support.invoke(request)

    if expected_format.get("type") == "json_schema":
        expected_format["json_schema"] = {
            "name": "open_mapping_response",
            "strict": True,
            "schema": request.prompt.response_schema,
        }
    recorded = server.requests[0]
    assert recorded.path == "/v1/chat/completions"
    assert recorded.headers["authorization"] == "Bearer secret-key"
    assert recorded.body == {
        "model": "model-fixed",
        "messages": [
            {"role": "system", "content": request.prompt.system_instruction},
            {"role": "user", "content": request.prompt.user_payload_json},
        ],
        "response_format": expected_format,
        "max_tokens": 321,
        "temperature": 0.2,
        "top_p": 0.8,
    }
    assert result.payload == payload
    assert result.provider_request_id == "chatcmpl_123"
    assert result.usage.model_dump() == {"input_tokens": 71, "output_tokens": 29}


def test_compatible_local_endpoint_can_run_without_an_api_key() -> None:
    response = {"choices": [{"message": {"content": json.dumps(support.fixed_payload())}}]}
    with support.LocalJsonServer(support.ScriptedResponse(200, response)) as server:
        request = support.fixed_request(
            ProviderKind.OPENAI_COMPATIBLE, server.base_url, api_key_env=None
        )
        result = support.invoke(request)
    assert result.payload == support.fixed_payload()
    assert "authorization" not in server.requests[0].headers


def test_compatible_rejects_tool_mode_before_network() -> None:
    with support.LocalJsonServer() as server:
        request = support.fixed_request(
            ProviderKind.OPENAI_COMPATIBLE,
            server.base_url,
            structured_output=StructuredOutputMode.TOOL,
        )
        with pytest.raises(OpenMappingError, match="structured_output.*tool"):
            support.invoke(request)
    assert server.requests == []


def test_compatible_json_schema_rejection_is_actionable_and_never_downgrades() -> None:
    with support.LocalJsonServer(
        support.ScriptedResponse(400, {"error": "response_format unsupported private detail"})
    ) as server:
        request = support.fixed_request(
            ProviderKind.OPENAI_COMPATIBLE,
            server.base_url,
            structured_output=StructuredOutputMode.JSON_SCHEMA,
            max_retries=2,
        )
        with pytest.raises(
            OpenMappingError, match="rejected structured_output 'json-schema'"
        ) as raised:
            support.invoke(request)
    assert len(server.requests) == 1
    assert "private detail" not in str(raised.value)
