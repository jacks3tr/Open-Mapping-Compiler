"""Google generateContent API transport."""

from __future__ import annotations

from time import monotonic
from urllib.parse import quote

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

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_COMPONENT = "providers.transports.google"


class GoogleTransport:
    """Invoke Google generateContent with responseJsonSchema."""

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
                f"Google transport does not support structured_output {model.structured_output.value!r}",
                "Use structured_output 'auto' or 'json-schema'.",
                component=_COMPONENT,
            )
        if model.parameters.reasoning_effort is not None:
            raise transport_error(
                "Google transport does not support configured parameter 'reasoning_effort'",
                "Remove parameters.reasoning_effort for this provider transport.",
                component=_COMPONENT,
            )
        credentials = resolve_transport_credentials(request.resolved_model)
        headers = {**dict(credentials.headers), "x-goog-api-key": credentials.api_key or ""}
        generation_config: dict[str, object] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": request.prompt.response_schema,
            "maxOutputTokens": model.max_output_tokens,
        }
        if model.parameters.temperature is not None:
            generation_config["temperature"] = model.parameters.temperature
        if model.parameters.top_p is not None:
            generation_config["topP"] = model.parameters.top_p
        if model.parameters.seed is not None:
            generation_config["seed"] = model.parameters.seed
        body: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": request.prompt.system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": request.prompt.user_payload_json}]}],
            "generationConfig": generation_config,
        }
        started = monotonic()
        route = f"models/{quote(model.model_id, safe='')}:generateContent"
        try:
            response = post_json(
                url=provider_endpoint(
                    request.resolved_model.provider.base_url or _DEFAULT_BASE_URL,
                    route,
                ),
                payload=body,
                headers=headers,
                resolved_model=request.resolved_model,
            )
        except HttpStatusFailure as exc:
            raise stable_transport_failure(exc) from exc
        except Exception as exc:
            raise stable_transport_failure(exc) from exc

        candidates = response.payload.get("candidates")
        texts: list[str] = []
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                if not isinstance(content, dict):
                    continue
                parts = content.get("parts")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        texts.append(part["text"])
        if len(texts) != 1:
            raise transport_error(
                "Google returned an invalid structured response",
                "Return exactly one candidate text part matching responseJsonSchema.",
                component=_COMPONENT,
            )
        payload = normalized_model_payload(texts[0], component=_COMPONENT)
        usage = response.payload.get("usageMetadata")
        usage_mapping = usage if isinstance(usage, dict) else {}
        return transport_result(
            payload,
            provider_request_id=response.payload.get("responseId"),
            input_tokens=usage_mapping.get("promptTokenCount"),
            output_tokens=usage_mapping.get("candidatesTokenCount"),
            started_at=started,
        )


__all__ = ["GoogleTransport"]
