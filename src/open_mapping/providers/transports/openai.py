"""OpenAI Responses API transport."""

from __future__ import annotations

from time import monotonic

from open_mapping.errors import OpenMappingError
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

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_COMPONENT = "providers.transports.openai"


def _unsupported_parameter(name: str) -> OpenMappingError:
    return transport_error(
        f"OpenAI Responses transport does not support configured parameter {name!r}",
        f"Remove parameters.{name} for this provider transport.",
        component=_COMPONENT,
    )


class OpenAITransport:
    """Invoke OpenAI Responses with strict JSON Schema output."""

    def __init__(self, resolved_model: ResolvedModel) -> None:
        self._resolved_model = resolved_model

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        require_matching_request(request, self._resolved_model, component=_COMPONENT)
        model = request.resolved_model.model
        if model.structured_output not in {
            StructuredOutputMode.AUTO,
            StructuredOutputMode.JSON_SCHEMA,
        }:
            raise transport_error(
                f"OpenAI Responses transport does not support structured_output {model.structured_output.value!r}",
                "Use structured_output 'auto' or 'json-schema'.",
                component=_COMPONENT,
            )
        if model.parameters.seed is not None:
            raise _unsupported_parameter("seed")
        if model.parameters.reasoning_effort is not None:
            raise _unsupported_parameter("reasoning_effort")
        credentials = resolve_transport_credentials(request.resolved_model)
        headers = dict(credentials.headers)
        if credentials.api_key is not None:
            headers["Authorization"] = f"Bearer {credentials.api_key}"
        body: dict[str, object] = {
            "model": model.model_id,
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
            "max_output_tokens": model.max_output_tokens,
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
                    "responses",
                ),
                payload=body,
                headers=headers,
                resolved_model=request.resolved_model,
            )
        except HttpStatusFailure as exc:
            raise stable_transport_failure(exc) from exc
        except Exception as exc:
            raise stable_transport_failure(exc) from exc

        output_texts: list[str] = []
        output = response.payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "output_text"
                        and isinstance(part.get("text"), str)
                    ):
                        output_texts.append(part["text"])
        if len(output_texts) != 1:
            raise transport_error(
                "OpenAI returned an invalid structured response",
                "Return exactly one output_text item matching the configured JSON schema.",
                component=_COMPONENT,
            )
        payload = normalized_model_payload(output_texts[0], component=_COMPONENT)
        usage = response.payload.get("usage")
        usage_mapping = usage if isinstance(usage, dict) else {}
        return transport_result(
            payload,
            provider_request_id=response.payload.get("id"),
            input_tokens=usage_mapping.get("input_tokens"),
            output_tokens=usage_mapping.get("output_tokens"),
            started_at=started,
        )


__all__ = ["OpenAITransport"]
