"""Optional synchronous HTTP proposal provider."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from time import sleep
from urllib.parse import urlparse

from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.providers import ProviderDisclosure
from open_mapping.providers.protocol import (
    ProviderCallResult,
    ProviderRequest,
    ProviderResponse,
    validate_provider_response,
)
from open_mapping.providers.redaction import sanitize_provider_request
from open_mapping.serialization.canonical_json import canonical_json_bytes

_MAX_BODY = 2 * 1024 * 1024
_MAX_RESPONSE = 2 * 1024 * 1024
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 30.0


def _issue(message: str, correction: str) -> Issue:
    return Issue(
        code=IssueCode.PROVIDER_FAILURE,
        severity=Severity.ERROR,
        component="providers.http",
        message=message,
        correction=correction,
    )


def _is_loopback(hostname: str) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"} or hostname.startswith("127.")


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and _is_loopback(parsed.hostname or ""):
        return
    raise OpenMappingError(
        (
            _issue(
                "provider URL must be HTTPS or loopback HTTP", "Use an HTTPS endpoint or localhost."
            ),
        )
    )


def _validate_response(response: ProviderResponse, request: ProviderRequest) -> None:
    validate_provider_response(response, request)


def _collect_get_paths(expression: object) -> set[str]:
    result: set[str] = set()
    stack = [expression]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("op") == "get" and node.get("document", "input") == "input":
            result.add(str(node.get("path")))
        for value in node.values():
            if isinstance(value, dict):
                stack.append(value)
            elif isinstance(value, list):
                stack.extend(item for item in value if isinstance(item, dict))
    return result


def call_http_provider(
    url: str,
    *,
    token_env: str | None,
    request: ProviderRequest,
    allow_raw_samples: bool,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> ProviderCallResult:
    _validate_url(url)
    try:
        import httpx
    except ImportError as exc:
        raise OpenMappingError(
            (_issue("httpx is not installed", "Install open-mapping[ai]."),)
        ) from exc
    token = os.environ.get(token_env) if token_env else None
    if token_env and not token:
        raise OpenMappingError(
            (
                _issue(
                    f"environment variable {token_env!r} is not set",
                    "Provide the named token environment variable.",
                ),
            )
        )
    sanitized_request, redaction_count = sanitize_provider_request(
        request, allow_raw_samples=allow_raw_samples
    )
    payload = sanitized_request.model_dump(mode="json")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_BODY:
        raise OpenMappingError(
            (_issue("provider request exceeds 2 MiB", "Reduce candidate or profile context."),)
        )
    request_headers = {"Content-Type": "application/json"}
    if headers is not None:
        for name, value in headers.items():
            if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise OpenMappingError(
                    (
                        _issue(
                            "provider header contains a line break",
                            "Use a single-line HTTP header name and value.",
                        ),
                    )
                )
            request_headers[name] = value
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    read_timeout = _READ_TIMEOUT if timeout_seconds is None else timeout_seconds
    retry_count = 1 if max_retries is None else min(max(max_retries, 0), 2)
    client = httpx.Client(timeout=httpx.Timeout(read_timeout, connect=_CONNECT_TIMEOUT))
    try:
        response_body = b""
        for attempt in range(retry_count + 1):
            with client.stream("POST", url, content=body, headers=request_headers) as response:
                if response.status_code in {429, 502, 503, 504} and attempt < retry_count:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after is not None else 0.0
                    except ValueError:
                        wait = 0.0
                    if 0 < wait <= 10:
                        sleep(wait)
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > _MAX_RESPONSE:
                        raise OpenMappingError(
                            (
                                _issue(
                                    "provider response exceeds 2 MiB", "Return a smaller response."
                                ),
                            )
                        )
                    chunks.append(chunk)
                response_body = b"".join(chunks)
                break
        parsed = json.loads(response_body.decode("utf-8"))
        provider_response = ProviderResponse.model_validate(parsed)
        _validate_response(provider_response, sanitized_request)
    except OpenMappingError:
        raise
    except (httpx.HTTPError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise OpenMappingError(
            (_issue("provider request failed", "Check the provider endpoint and retry."),)
        ) from exc
    finally:
        client.close()
    disclosure = ProviderDisclosure(
        endpoint_origin=urlparse(url).netloc,
        raw_samples_included=allow_raw_samples,
        source_field_count=len(request.source_field_metadata),
        candidate_count=len(request.candidates),
        sample_profile_count=len(request.sample_profiles),
        redaction_count=redaction_count,
        request_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )
    return ProviderCallResult(response=provider_response, disclosure=disclosure)
