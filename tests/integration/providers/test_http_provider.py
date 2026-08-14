"""Real local-HTTP provider boundary integration tests."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.model.suggestions import MatchCandidate
from open_mapping.providers import http
from open_mapping.providers.protocol import ProviderRequest


def _request(*, instruction: str | None = None) -> ProviderRequest:
    return ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="source",
        target_schema_id="target",
        target_path="/result",
        candidates=(MatchCandidate(source_path="/value", target_path="/result", raw_score=0.8),),
        source_field_metadata=(
            SchemaField(
                pointer="/value",
                types=frozenset({JsonType.STRING}),
                required=True,
                description="alice@example.com",
            ),
        ),
        target_field_metadata=SchemaField(
            pointer="/result", types=frozenset({JsonType.STRING}), required=True
        ),
        sample_profiles=(),
        instruction_text=instruction,
        raw_samples=({"value": "alice@example.com"},),
    )


class _Handler(BaseHTTPRequestHandler):
    queued_responses: ClassVar[list[tuple[int, dict[str, str], bytes]]] = []
    requests: ClassVar[list[dict[str, object]]] = []
    delay: ClassVar[float] = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        type(self).requests.append(json.loads(self.rfile.read(length)))
        if type(self).delay:
            time.sleep(type(self).delay)
        status, headers, body = type(self).queued_responses.pop(0)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


@pytest.fixture
def provider_url() -> Generator[str]:
    _Handler.queued_responses = []
    _Handler.requests = []
    _Handler.delay = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _success() -> bytes:
    return json.dumps(
        {
            "protocol_version": "0.1",
            "proposals": [
                {
                    "target_path": "/result",
                    "abstain": False,
                    "selected_source_paths": ["/value"],
                    "expression": {"op": "get", "path": "/value"},
                    "reason": "best candidate",
                }
            ],
        }
    ).encode()


def test_success_posts_sanitized_request(provider_url: str) -> None:
    _Handler.queued_responses = [(200, {"Content-Type": "application/json"}, _success())]
    result = http.call_http_provider(
        provider_url,
        token_env=None,
        request=_request(instruction="token=abcdefghijklmnopqrstuvwxyz0123456789"),
        allow_raw_samples=False,
    )
    sent = _Handler.requests[0]
    assert sent["raw_samples"] is None
    assert "alice" not in str(sent)
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in str(sent)
    assert result.response.proposals[0].selected_source_paths == ("/value",)
    assert result.disclosure.redaction_count == 2


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_transient_status_retries_exactly_once(provider_url: str, status: int) -> None:
    _Handler.queued_responses = [(status, {}, b"temporary"), (200, {}, _success())]
    http.call_http_provider(
        provider_url, token_env=None, request=_request(), allow_raw_samples=False
    )
    assert len(_Handler.requests) == 2


@pytest.mark.parametrize("retry_after, expected_sleeps", [("0.01", [0.01]), ("11", [])])
def test_retry_after_is_honored_only_through_ten_seconds(
    provider_url: str,
    retry_after: str,
    expected_sleeps: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(http, "sleep", sleeps.append)
    _Handler.queued_responses = [
        (429, {"Retry-After": retry_after}, b"wait"),
        (200, {}, _success()),
    ]
    http.call_http_provider(
        provider_url, token_env=None, request=_request(), allow_raw_samples=False
    )
    assert sleeps == expected_sleeps


def test_non_transient_client_error_is_not_retried(provider_url: str) -> None:
    _Handler.queued_responses = [(400, {}, b"bad")]
    with pytest.raises(OpenMappingError):
        http.call_http_provider(
            provider_url, token_env=None, request=_request(), allow_raw_samples=False
        )
    assert len(_Handler.requests) == 1


def test_timeout_is_explicit(provider_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "_READ_TIMEOUT", 0.01)
    _Handler.delay = 0.1
    _Handler.queued_responses = [(200, {}, _success())]
    with pytest.raises(OpenMappingError, match="provider request failed"):
        http.call_http_provider(
            provider_url, token_env=None, request=_request(), allow_raw_samples=False
        )


def test_invalid_json_is_rejected(provider_url: str) -> None:
    _Handler.queued_responses = [(200, {}, b"not json")]
    with pytest.raises(OpenMappingError):
        http.call_http_provider(
            provider_url, token_env=None, request=_request(), allow_raw_samples=False
        )


def test_programmer_errors_are_not_masked(
    provider_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def stream(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("programmer defect")

        def close(self) -> None:
            pass

    monkeypatch.setattr("httpx.Client", BrokenClient)
    with pytest.raises(RuntimeError, match="programmer defect"):
        http.call_http_provider(
            provider_url, token_env=None, request=_request(), allow_raw_samples=False
        )


def test_oversized_request_is_rejected_before_network(
    provider_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http, "_MAX_BODY", 1)
    with pytest.raises(OpenMappingError, match="request exceeds"):
        http.call_http_provider(
            provider_url, token_env=None, request=_request(), allow_raw_samples=False
        )
    assert not _Handler.requests


def test_oversized_streamed_response_stops_at_limit(
    provider_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http, "_MAX_RESPONSE", 64)
    _Handler.queued_responses = [(200, {}, b"{" + b" " * 256 + b"}")]
    with pytest.raises(OpenMappingError, match="response exceeds"):
        http.call_http_provider(
            provider_url, token_env=None, request=_request(), allow_raw_samples=False
        )


def test_missing_token_variable_and_remote_plaintext_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPEN_MAPPING_TEST_TOKEN", raising=False)
    with pytest.raises(OpenMappingError, match="is not set"):
        http.call_http_provider(
            "https://example.com",
            token_env="OPEN_MAPPING_TEST_TOKEN",
            request=_request(),
            allow_raw_samples=False,
        )
    with pytest.raises(OpenMappingError, match="HTTPS or loopback"):
        http.call_http_provider(
            "http://example.com", token_env=None, request=_request(), allow_raw_samples=False
        )
