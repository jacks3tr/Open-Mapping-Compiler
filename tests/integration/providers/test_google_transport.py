"""Local HTTP integration tests for the Google generateContent transport."""

from __future__ import annotations

import json

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ProviderKind
from tests.integration.providers import model_transport_support as support


@pytest.fixture(autouse=True)
def provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("MODEL_ROUTE", "route-value")


def test_google_generate_content_uses_response_json_schema_and_normalizes_text() -> None:
    payload = support.fixed_payload()
    response = {
        "responseId": "google_123",
        "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(payload)}]}}],
        "usageMetadata": {"promptTokenCount": 61, "candidatesTokenCount": 23},
    }
    with support.LocalJsonServer(support.ScriptedResponse(200, response)) as server:
        request = support.fixed_request(
            ProviderKind.GOOGLE,
            server.base_url,
            parameters={"temperature": 0.2, "top_p": 0.8, "seed": 12},
        )
        result = support.invoke(request)

    recorded = server.requests[0]
    assert recorded.path == "/v1/models/model-fixed:generateContent"
    assert recorded.headers["x-goog-api-key"] == "secret-key"
    assert "authorization" not in recorded.headers
    assert recorded.body == {
        "systemInstruction": {"parts": [{"text": request.prompt.system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": request.prompt.user_payload_json}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": request.prompt.response_schema,
            "maxOutputTokens": 321,
            "temperature": 0.2,
            "topP": 0.8,
            "seed": 12,
        },
    }
    assert result.payload == payload
    assert result.provider_request_id == "google_123"
    assert result.usage.model_dump() == {"input_tokens": 61, "output_tokens": 23}


@pytest.mark.parametrize("text", ["not-json-private", "[]"])
def test_google_strictly_validates_returned_json_text(text: str) -> None:
    response = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    with support.LocalJsonServer(support.ScriptedResponse(200, response)) as server:
        with pytest.raises(OpenMappingError, match="structured response") as raised:
            support.invoke(support.fixed_request(ProviderKind.GOOGLE, server.base_url))
    assert "not-json-private" not in str(raised.value)


def test_google_rejects_reasoning_effort_before_network() -> None:
    with support.LocalJsonServer() as server:
        request = support.fixed_request(
            ProviderKind.GOOGLE, server.base_url, parameters={"reasoning_effort": "low"}
        )
        with pytest.raises(OpenMappingError, match="reasoning_effort"):
            support.invoke(request)
    assert server.requests == []
