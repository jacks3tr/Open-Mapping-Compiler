"""Provider boundary tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from open_mapping.errors import OpenMappingError
from open_mapping.model.json_types import JsonValue
from open_mapping.providers.http import call_http_provider
from open_mapping.providers.protocol import (
    ProviderCallResult,
    ProviderRequest,
    ProviderResponse,
)
from open_mapping.providers.redaction import redact_json, redact_text


def test_redaction() -> None:
    value: JsonValue = {
        "email": "user@example.com",
        "token": "Bearer abcdefghijklmnopqrstuvwxyz123456",
        "ok": 1,
    }
    redacted = redact_json(value)
    assert "user@" not in str(redacted)
    assert isinstance(redacted, dict)
    assert redacted["ok"] == 1
    assert "REDACTED" in redact_text("api_key=secret")


def _request() -> ProviderRequest:
    from open_mapping.model.schema import JsonType, SchemaField

    return ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="s",
        target_schema_id="t",
        target_path="/a",
        candidates=(),
        source_field_metadata=(),
        target_field_metadata=SchemaField(
            pointer="/a", types=frozenset({JsonType.STRING}), required=True
        ),
        sample_profiles=(),
    )


def _server(handler: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_http_provider_success() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            payload = json.dumps(
                {
                    "protocol_version": "0.1",
                    "proposals": [{"target_path": "/a", "abstain": True, "reason": "ok"}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    server, port = _server(Handler)
    try:
        result = call_http_provider(
            f"http://127.0.0.1:{port}",
            token_env=None,
            request=_request(),
            allow_raw_samples=False,
        )
        assert isinstance(result, ProviderCallResult)
        assert result.disclosure.endpoint_origin == f"127.0.0.1:{port}"
    finally:
        server.shutdown()


def test_http_provider_rejects_remote_http() -> None:
    try:
        call_http_provider(
            "http://example.com", token_env=None, request=_request(), allow_raw_samples=False
        )
    except OpenMappingError:
        pass
    else:
        raise AssertionError("remote plaintext HTTP should be rejected")


def test_protocol_rejects_unknown_fields() -> None:
    from pydantic import ValidationError

    try:
        ProviderResponse.model_validate({"protocol_version": "0.1", "proposals": (), "extra": 1})
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown provider response fields should be rejected")
