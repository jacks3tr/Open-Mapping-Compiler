"""OpenAI-compatible Chat Completions transport."""

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

_COMPONENT = "providers.transports.openai_compatible"


class OpenAICompatibleTransport:
    """Invoke a configured Chat Completions endpoint with an explicit response mode."""

    def __init__(self, resolved_model: ResolvedModel) -> None:
        self._resolved_model = resolved_model

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        require_matching_request(request, self._resolved_model, component=_COMPONENT)
        model = request.resolved_model.model
        mode = (
            StructuredOutputMode.JSON_SCHEMA
            if model.structured_output is StructuredOutputMode.AUTO
            else model.structured_output
        )
        if mode not in {StructuredOutputMode.JSON_SCHEMA, StructuredOutputMode.JSON}:
            raise transport_error(
                f"OpenAI-compatible transport does not support structured_output {mode.value!r}",
                "Use structured_output 'auto', 'json-schema', or 'json'.",
                component=_COMPONENT,
            )
        if model.parameters.seed is not None:
            raise transport_error(
                "OpenAI-compatible transport does not declare support for parameter 'seed'",
                "Remove parameters.seed or use a provider-specific transport that supports it.",
                component=_COMPONENT,
            )
        if model.parameters.reasoning_effort is not None:
            raise transport_error(
                "OpenAI-compatible transport does not declare support for parameter 'reasoning_effort'",
                "Remove parameters.reasoning_effort or use a provider-specific transport that supports it.",
                component=_COMPONENT,
            )
        credentials = resolve_transport_credentials(request.resolved_model)
        headers = dict(credentials.headers)
        if credentials.api_key is not None:
            headers["Authorization"] = f"Bearer {credentials.api_key}"
        response_format: dict[str, object]
        if mode is StructuredOutputMode.JSON_SCHEMA:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "open_mapping_response",
                    "strict": True,
                    "schema": request.prompt.response_schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
        body: dict[str, object] = {
            "model": model.model_id,
            "messages": [
                {"role": "system", "content": request.prompt.system_instruction},
                {"role": "user", "content": request.prompt.user_payload_json},
            ],
            "response_format": response_format,
            "max_tokens": model.max_output_tokens,
        }
        if model.parameters.temperature is not None:
            body["temperature"] = model.parameters.temperature
        if model.parameters.top_p is not None:
            body["top_p"] = model.parameters.top_p
        base_url = request.resolved_model.provider.base_url
        if base_url is None:
            raise transport_error(
                "OpenAI-compatible transport has no base_url",
                "Configure the HTTPS or loopback HTTP endpoint base URL.",
                component=_COMPONENT,
            )
        started = monotonic()
        try:
            response = post_json(
                url=provider_endpoint(base_url, "chat/completions"),
                payload=body,
                headers=headers,
                resolved_model=request.resolved_model,
            )
        except HttpStatusFailure as exc:
            if mode is StructuredOutputMode.JSON_SCHEMA and 400 <= exc.status_code < 500:
                raise transport_error(
                    "OpenAI-compatible endpoint rejected structured_output 'json-schema'",
                    "Set structured_output to 'json' only if this endpoint documents JSON mode support.",
                    component=_COMPONENT,
                ) from exc
            raise stable_transport_failure(exc) from exc
        except Exception as exc:
            raise stable_transport_failure(exc) from exc

        choices = response.payload.get("choices")
        content: object = None
        if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
        if not isinstance(content, str):
            raise transport_error(
                "OpenAI-compatible endpoint returned an invalid structured response",
                "Return exactly one assistant message with JSON string content.",
                component=_COMPONENT,
            )
        payload = normalized_model_payload(content, component=_COMPONENT)
        usage = response.payload.get("usage")
        usage_mapping = usage if isinstance(usage, dict) else {}
        return transport_result(
            payload,
            provider_request_id=response.payload.get("id"),
            input_tokens=usage_mapping.get("prompt_tokens"),
            output_tokens=usage_mapping.get("completion_tokens"),
            started_at=started,
        )


__all__ = ["OpenAICompatibleTransport"]
