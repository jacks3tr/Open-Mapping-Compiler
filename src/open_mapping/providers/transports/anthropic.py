"""Anthropic Messages API transport."""

from __future__ import annotations

from time import monotonic

from open_mapping.model.model_config import ResolvedModel, StructuredOutputMode
from open_mapping.providers.protocol import ModelTransportRequest, ModelTransportResult
from open_mapping.providers.transports.base import (
    HttpStatusFailure,
    normalized_model_payload,
    post_json,
    provider_endpoint,
    require_matching_request,
    resolve_transport_credentials,
    stable_transport_failure,
    transport_error,
    transport_result,
)

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_COMPONENT = "providers.transports.anthropic"
_OUTPUT_TOOL = "submit_mapping_response"


class AnthropicTransport:
    """Invoke Anthropic Messages with one forced output tool."""

    def __init__(self, resolved_model: ResolvedModel) -> None:
        self._resolved_model = resolved_model

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        require_matching_request(request, self._resolved_model, component=_COMPONENT)
        model = request.resolved_model.model
        if model.structured_output not in {
            StructuredOutputMode.AUTO,
            StructuredOutputMode.TOOL,
        }:
            raise transport_error(
                f"Anthropic transport does not support structured_output {model.structured_output.value!r}",
                "Use structured_output 'auto' or 'tool'.",
                component=_COMPONENT,
            )
        if model.parameters.seed is not None:
            raise transport_error(
                "Anthropic transport does not support configured parameter 'seed'",
                "Remove parameters.seed for this provider transport.",
                component=_COMPONENT,
            )
        if model.parameters.reasoning_effort is not None:
            raise transport_error(
                "Anthropic forced-tool transport does not support configured parameter 'reasoning_effort'",
                "Remove parameters.reasoning_effort when using forced structured output.",
                component=_COMPONENT,
            )
        credentials = resolve_transport_credentials(request.resolved_model)
        headers = {
            **dict(credentials.headers),
            "x-api-key": credentials.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        body: dict[str, object] = {
            "model": model.model_id,
            "max_tokens": model.max_output_tokens,
            "system": request.prompt.system_instruction,
            "messages": [{"role": "user", "content": request.prompt.user_payload_json}],
            "tools": [
                {
                    "name": _OUTPUT_TOOL,
                    "description": "Submit the complete mapping response.",
                    "input_schema": request.prompt.response_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": _OUTPUT_TOOL},
        }
        if model.parameters.temperature is not None:
            body["temperature"] = model.parameters.temperature
        if model.parameters.top_p is not None:
            body["top_p"] = model.parameters.top_p
        started = monotonic()
        try:
            response = post_json(
                url=provider_endpoint(
                    request.resolved_model.provider.base_url or _DEFAULT_BASE_URL,
                    "messages",
                ),
                payload=body,
                headers=headers,
                resolved_model=request.resolved_model,
            )
        except HttpStatusFailure as exc:
            raise stable_transport_failure(exc) from exc
        except Exception as exc:
            raise stable_transport_failure(exc) from exc

        content = response.payload.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise transport_error(
                "Anthropic must return exactly one forced output tool call",
                f"Return one {_OUTPUT_TOOL!r} tool_use block and no prose.",
                component=_COMPONENT,
            )
        block = content[0]
        if (
            not isinstance(block, dict)
            or block.get("type") != "tool_use"
            or block.get("name") != _OUTPUT_TOOL
            or not isinstance(block.get("input"), dict)
        ):
            raise transport_error(
                "Anthropic must return exactly one forced output tool call",
                f"Return one {_OUTPUT_TOOL!r} tool_use block and no prose.",
                component=_COMPONENT,
            )
        payload = normalized_model_payload(block["input"], component=_COMPONENT)
        usage = response.payload.get("usage")
        usage_mapping = usage if isinstance(usage, dict) else {}
        return transport_result(
            payload,
            provider_request_id=response.payload.get("id"),
            input_tokens=usage_mapping.get("input_tokens"),
            output_tokens=usage_mapping.get("output_tokens"),
            started_at=started,
        )


__all__ = ["AnthropicTransport"]
