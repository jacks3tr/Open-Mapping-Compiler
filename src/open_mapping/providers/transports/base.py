"""Shared safety boundary and synchronous model transport contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from time import monotonic, sleep
from types import MappingProxyType
from typing import NoReturn, cast

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ResolvedModel
from open_mapping.providers.protocol import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResult,
    ModelUsage,
    TransportFactory,
)
from open_mapping.serialization.canonical_json import canonical_json_bytes

MAX_REQUEST_BODY_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BODY_BYTES = 4 * 1024 * 1024
MAX_TRANSIENT_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 10.0
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r} is not allowed")
        result[key] = value
    return result


def _strict_json_loads(value: str | bytes) -> object:
    decoded = json.loads(
        value,
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    canonical_json_bytes(cast(JsonValue, decoded))
    return decoded


def transport_error(
    message: str,
    correction: str,
    *,
    component: str = "providers.transports",
    code: IssueCode = IssueCode.PROVIDER_FAILURE,
) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=code,
                severity=Severity.ERROR,
                component=component,
                message=message,
                correction=correction,
            ),
        )
    )


@dataclass(frozen=True)
class TransportCredentials:
    """Credential values resolved immediately before a transport call."""

    api_key: str | None
    headers: Mapping[str, str]


def sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return safe HTTP headers without allowing line-break injection."""

    sanitized: dict[str, str] = {}
    normalized_names: set[str] = set()
    for name, value in headers.items():
        normalized_name = name.strip()
        if not normalized_name or _HEADER_NAME.fullmatch(normalized_name) is None:
            raise transport_error(
                "configured provider header name is invalid",
                "Use a valid HTTP header name without whitespace or control characters.",
            )
        if "\r" in value or "\n" in value:
            raise transport_error(
                "configured provider header value contains a line break",
                "Store a single-line header value in the named environment variable.",
            )
        normalized_key = normalized_name.casefold()
        if normalized_key in normalized_names:
            raise transport_error(
                "configured provider headers contain a duplicate name",
                "Use each HTTP header name at most once.",
            )
        normalized_names.add(normalized_key)
        sanitized[normalized_name] = value
    return sanitized


def resolve_transport_credentials(
    resolved_model: ResolvedModel,
    *,
    environment: Mapping[str, str] | None = None,
) -> TransportCredentials:
    """Resolve configured credential environment variables only at call time."""

    source_environment = os.environ if environment is None else environment
    provider = resolved_model.provider
    api_key: str | None = None
    if provider.api_key_env is not None:
        api_key = source_environment.get(provider.api_key_env)
        if not api_key:
            raise transport_error(
                f"environment variable {provider.api_key_env!r} is not set",
                "Provide the named provider credential environment variable.",
            )
    configured_headers: dict[str, str] = {}
    for header_name, environment_name in provider.headers_from_env.items():
        header_value = source_environment.get(environment_name)
        if not header_value:
            raise transport_error(
                f"environment variable {environment_name!r} is not set",
                "Provide the named provider header environment variable.",
            )
        configured_headers[header_name] = header_value
    return TransportCredentials(
        api_key=api_key,
        headers=MappingProxyType(sanitize_headers(configured_headers)),
    )


def provider_timeout_seconds(resolved_model: ResolvedModel) -> float:
    """Return the validated timeout for one resolved provider model."""

    return resolved_model.provider.timeout_seconds


def bounded_retry_count(resolved_model: ResolvedModel) -> int:
    """Return the configured retry count capped at the transport boundary."""

    return min(resolved_model.provider.max_retries, MAX_TRANSIENT_RETRIES)


def encode_bounded_json_body(payload: JsonValue) -> bytes:
    """Serialize a JSON request while enforcing the shared request cap."""

    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise transport_error(
            "model transport request is not JSON serializable",
            "Provide only JSON-compatible model prompt data.",
        ) from exc
    if len(body) > MAX_REQUEST_BODY_BYTES:
        raise transport_error(
            "model transport request exceeds 8 MiB",
            "Reduce the model context or configured batch size.",
        )
    return body


def read_bounded_response_body(chunks: Iterable[bytes]) -> bytes:
    """Collect a streamed response without retaining bodies above the shared cap."""

    body_parts: list[bytes] = []
    size = 0
    for chunk in chunks:
        size += len(chunk)
        if size > MAX_RESPONSE_BODY_BYTES:
            raise transport_error(
                "model transport response exceeds 4 MiB",
                "Return a smaller structured response.",
            )
        body_parts.append(chunk)
    return b"".join(body_parts)


def call_with_transient_retries[Value](
    operation: Callable[[], Value],
    *,
    max_retries: int,
    is_transient: Callable[[Exception], bool],
    retry_after_seconds: Callable[[Exception], float | None] | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> Value:
    """Retry only caller-classified transient failures within the shared bound."""

    retries_remaining = min(max(max_retries, 0), MAX_TRANSIENT_RETRIES)
    while True:
        try:
            return operation()
        except Exception as exc:
            if retries_remaining == 0 or not is_transient(exc):
                raise
            retries_remaining -= 1
            retry_after = retry_after_seconds(exc) if retry_after_seconds is not None else None
            if retry_after is not None and 0 < retry_after <= MAX_RETRY_AFTER_SECONDS:
                sleep_fn(retry_after)


def stable_transport_failure(exc: Exception) -> OpenMappingError:
    """Convert unexpected transport failures without exposing provider response text."""

    if isinstance(exc, OpenMappingError):
        return exc
    return transport_error(
        "model transport request failed",
        "Check the provider endpoint, credentials, and configured response mode.",
    )


@dataclass(frozen=True)
class HttpJsonResponse:
    """Bounded JSON response metadata shared by provider adapters."""

    payload: dict[str, object]
    headers: Mapping[str, str]


class HttpStatusFailure(Exception):
    """HTTP status information without retaining a provider response body."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP status {status_code}")
        self.status_code = status_code


def provider_endpoint(base_url: str, suffix: str) -> str:
    """Append a provider route once to an API base URL."""

    normalized_base = base_url.rstrip("/")
    normalized_suffix = "/" + suffix.strip("/")
    if normalized_base.endswith(normalized_suffix):
        return normalized_base
    return normalized_base + normalized_suffix


def require_matching_request(
    request: ModelTransportRequest,
    resolved_model: ResolvedModel,
    *,
    component: str,
) -> None:
    """Reject attempts to invoke a transport with a different model resolution."""

    if request.resolved_model != resolved_model:
        raise transport_error(
            "model transport request does not match the configured model",
            "Build the transport from the same resolved model passed to invoke.",
            component=component,
        )


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if 0 < parsed <= MAX_RETRY_AFTER_SECONDS else None


def post_json(
    *,
    url: str,
    payload: JsonValue,
    headers: Mapping[str, str],
    resolved_model: ResolvedModel,
) -> HttpJsonResponse:
    """POST bounded JSON with the shared timeout and retry policy."""

    try:
        import httpx
    except ImportError as exc:
        raise transport_error(
            "httpx is not installed",
            "Install open-mapping[ai] before invoking a model provider.",
        ) from exc

    body = encode_bounded_json_body(payload)
    request_headers = {"Content-Type": "application/json", **headers}
    retries_remaining = bounded_retry_count(resolved_model)
    client = httpx.Client(timeout=provider_timeout_seconds(resolved_model))
    try:
        while True:
            try:
                with client.stream("POST", url, content=body, headers=request_headers) as response:
                    normalized_headers = {
                        name.casefold(): value for name, value in response.headers.items()
                    }
                    if response.status_code in {429, 502, 503, 504}:
                        if retries_remaining > 0:
                            retries_remaining -= 1
                            retry_after = _retry_after_seconds(normalized_headers)
                            if retry_after is not None:
                                sleep(retry_after)
                            continue
                        raise HttpStatusFailure(response.status_code)
                    if response.status_code >= 400:
                        raise HttpStatusFailure(response.status_code)
                    raw_body = read_bounded_response_body(response.iter_bytes())
                try:
                    decoded = _strict_json_loads(raw_body.decode("utf-8"))
                except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                    raise transport_error(
                        "model provider returned invalid JSON",
                        "Configure an endpoint that returns one JSON response object.",
                        code=IssueCode.PROVIDER_RESPONSE_INVALID,
                    ) from exc
                if not isinstance(decoded, dict):
                    raise transport_error(
                        "model provider returned a non-object JSON response",
                        "Configure an endpoint that returns one JSON response object.",
                        code=IssueCode.PROVIDER_RESPONSE_INVALID,
                    )
                return HttpJsonResponse(payload=decoded, headers=normalized_headers)
            except httpx.TimeoutException:
                if retries_remaining == 0:
                    raise
                retries_remaining -= 1
    finally:
        client.close()


def normalized_model_payload(value: object, *, component: str) -> JsonValue:
    """Strictly parse one provider JSON object without retaining its raw text."""

    try:
        decoded = _strict_json_loads(value) if isinstance(value, str) else value
        canonical_json_bytes(cast(JsonValue, decoded))
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError) as exc:
        raise transport_error(
            "model provider returned an invalid structured response",
            "Return exactly one JSON object that matches the configured response schema.",
            component=component,
            code=IssueCode.PROVIDER_RESPONSE_INVALID,
        ) from exc
    if not isinstance(decoded, dict):
        raise transport_error(
            "model provider returned an invalid structured response",
            "Return exactly one JSON object that matches the configured response schema.",
            component=component,
            code=IssueCode.PROVIDER_RESPONSE_INVALID,
        )
    return cast(JsonValue, decoded)


def transport_result(
    payload: JsonValue,
    *,
    provider_request_id: object,
    input_tokens: object,
    output_tokens: object,
    started_at: float,
) -> ModelTransportResult:
    """Build the common transport result without retaining a raw response."""

    request_id = provider_request_id if isinstance(provider_request_id, str) else None
    safe_input_tokens = (
        input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else None
    )
    safe_output_tokens = (
        output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else None
    )
    return ModelTransportResult(
        payload=payload,
        provider_request_id=request_id,
        usage=ModelUsage(
            input_tokens=safe_input_tokens,
            output_tokens=safe_output_tokens,
        ),
        latency_ms=max(0, round((monotonic() - started_at) * 1000)),
        response_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )


__all__ = [
    "MAX_REQUEST_BODY_BYTES",
    "MAX_RESPONSE_BODY_BYTES",
    "MAX_RETRY_AFTER_SECONDS",
    "MAX_TRANSIENT_RETRIES",
    "HttpJsonResponse",
    "HttpStatusFailure",
    "ModelTransport",
    "ModelTransportRequest",
    "ModelTransportResult",
    "ModelUsage",
    "TransportCredentials",
    "TransportFactory",
    "bounded_retry_count",
    "call_with_transient_retries",
    "encode_bounded_json_body",
    "provider_timeout_seconds",
    "provider_endpoint",
    "post_json",
    "read_bounded_response_body",
    "resolve_transport_credentials",
    "require_matching_request",
    "sanitize_headers",
    "stable_transport_failure",
    "normalized_model_payload",
    "transport_error",
    "transport_result",
]
