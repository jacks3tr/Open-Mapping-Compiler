"""Local HTTP integration tests for the Anthropic Messages transport."""

from __future__ import annotations

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ProviderKind
from tests.integration.providers import model_transport_support as support


@pytest.fixture(autouse=True)
def provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("MODEL_ROUTE", "route-value")


def test_anthropic_forces_one_output_tool_and_normalizes_its_input() -> None:
    payload = support.fixed_payload()
    response = {
        "id": "msg_123",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_1",
                "name": "submit_mapping_response",
                "input": payload,
            }
        ],
        "usage": {"input_tokens": 51, "output_tokens": 19},
    }
    with support.LocalJsonServer(support.ScriptedResponse(200, response)) as server:
        request = support.fixed_request(ProviderKind.ANTHROPIC, server.base_url)
        result = support.invoke(request)

    recorded = server.requests[0]
    assert recorded.path == "/v1/messages"
    assert recorded.headers["x-api-key"] == "secret-key"
    assert recorded.headers["anthropic-version"] == "2023-06-01"
    assert recorded.body == {
        "model": "model-fixed",
        "max_tokens": 321,
        "system": request.prompt.system_instruction,
        "messages": [{"role": "user", "content": request.prompt.user_payload_json}],
        "tools": [
            {
                "name": "submit_mapping_response",
                "description": "Submit the complete mapping response.",
                "input_schema": request.prompt.response_schema,
            }
        ],
        "tool_choice": {"type": "tool", "name": "submit_mapping_response"},
        "temperature": 0.2,
        "top_p": 0.8,
    }
    assert result.payload == payload
    assert result.provider_request_id == "msg_123"
    assert result.usage.model_dump() == {"input_tokens": 51, "output_tokens": 19}


@pytest.mark.parametrize(
    "content",
    [
        [],
        [{"type": "text", "text": "ordinary prose"}],
        [
            {
                "type": "tool_use",
                "name": "submit_mapping_response",
                "input": support.fixed_payload(),
            },
            {
                "type": "tool_use",
                "name": "submit_mapping_response",
                "input": support.fixed_payload(),
            },
        ],
        [
            {"type": "text", "text": "prose alongside tool"},
            {
                "type": "tool_use",
                "name": "submit_mapping_response",
                "input": support.fixed_payload(),
            },
        ],
    ],
)
def test_anthropic_rejects_missing_conflicting_or_prose_output(content: list[object]) -> None:
    with support.LocalJsonServer(
        support.ScriptedResponse(200, {"id": "msg_bad", "content": content})
    ) as server:
        with pytest.raises(OpenMappingError, match="one forced output tool"):
            support.invoke(support.fixed_request(ProviderKind.ANTHROPIC, server.base_url))


def test_anthropic_rejects_unsupported_seed_before_network() -> None:
    with support.LocalJsonServer() as server:
        request = support.fixed_request(
            ProviderKind.ANTHROPIC, server.base_url, parameters={"seed": 5}
        )
        with pytest.raises(OpenMappingError, match="seed"):
            support.invoke(request)
    assert server.requests == []
