"""Shared local HTTP support for neighboring model transport integration tests."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from open_mapping.model.model_config import (
    ModelProviderConfig,
    ProviderKind,
    StructuredOutputMode,
)
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelTargetRequest,
)
from open_mapping.providers.config import resolve_model
from open_mapping.providers.prompt import build_model_prompt
from open_mapping.providers.protocol import ModelTransportRequest, ModelTransportResult
from open_mapping.providers.registry import build_transport_registry


@dataclass(frozen=True)
class RecordedRequest:
    """One decoded request received by a local scripted server."""

    path: str
    headers: Mapping[str, str]
    body: dict[str, object]


@dataclass(frozen=True)
class ScriptedResponse:
    """One response returned by a local scripted server."""

    status: int
    body: object
    headers: Mapping[str, str] | None = None
    delay_seconds: float = 0


class LocalJsonServer(AbstractContextManager["LocalJsonServer"]):
    """Small deterministic server that records requests and scripts responses."""

    def __init__(self, *responses: ScriptedResponse) -> None:
        self.responses = deque(responses)
        self.requests: list[RecordedRequest] = []
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                with owner._lock:
                    owner.requests.append(
                        RecordedRequest(
                            path=self.path,
                            headers={
                                name.casefold(): value for name, value in self.headers.items()
                            },
                            body=json.loads(raw_body),
                        )
                    )
                    scripted = owner.responses.popleft()
                if scripted.delay_seconds:
                    time.sleep(scripted.delay_seconds)
                payload = (
                    scripted.body
                    if isinstance(scripted.body, bytes)
                    else json.dumps(scripted.body, separators=(",", ":")).encode("utf-8")
                )
                self.send_response(scripted.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in (scripted.headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = cast(tuple[str, int], self._server.server_address)
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> LocalJsonServer:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)


def fixed_payload() -> dict[str, object]:
    """Return the literal shared model response used by all transport fixtures."""

    return {
        "protocol_version": "0.1",
        "prompt_version": "mapping-agent-v1",
        "context_sha256": "a" * 64,
        "batch_id": "batch-fixed",
        "proposals": [
            {
                "target_path": "/display_name",
                "action": "propose",
                "selected_source_paths": ["/source_name"],
                "expression": {
                    "op": "get",
                    "path": "/source_name",
                    "document": "input",
                },
                "reason": "same semantic field",
                "evidence": ["names and types align"],
            }
        ],
    }


def fixed_request(
    kind: ProviderKind,
    base_url: str,
    *,
    structured_output: StructuredOutputMode = StructuredOutputMode.AUTO,
    api_key_env: str | None = "MODEL_API_KEY",
    timeout_seconds: float = 1,
    max_retries: int = 1,
    parameters: Mapping[str, object] | None = None,
) -> ModelTransportRequest:
    """Build one fully resolved request pointed at an explicit local endpoint."""

    provider: dict[str, object] = {"kind": kind.value, "base_url": base_url}
    if api_key_env is not None:
        provider["api_key_env"] = api_key_env
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {
                "local": {
                    **provider,
                    "headers_from_env": {"X-Route": "MODEL_ROUTE"},
                    "timeout_seconds": timeout_seconds,
                    "max_retries": max_retries,
                }
            },
            "models": {
                "mapper": {
                    "provider": "local",
                    "model_id": "model-fixed",
                    "structured_output": structured_output.value,
                    "max_output_tokens": 321,
                    "parameters": dict(parameters or {"temperature": 0.2, "top_p": 0.8}),
                }
            },
        }
    )
    package = MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id="batch-fixed",
        context_mode="targeted",
        source_schema_id="source",
        source_schema_version="1",
        target_schema_id="target",
        target_schema_version="1",
        source_fields=(
            ModelFieldSummary(pointer="/source_name", types=("string",), required=True),
        ),
        target_requests=(
            ModelTargetRequest(
                target=ModelFieldSummary(pointer="/display_name", types=("string",), required=True),
                candidates=(
                    ModelCandidateSummary(
                        source_path="/source_name",
                        raw_score=0.9,
                        evidence=("same semantic name",),
                    ),
                ),
            ),
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=("get",),
        allowed_source_paths=("/source_name",),
        raw_samples=None,
    )
    resolved = resolve_model(config, "mapper")
    return ModelTransportRequest(resolved_model=resolved, prompt=build_model_prompt(package))


def invoke(request: ModelTransportRequest) -> ModelTransportResult:
    """Route a request through the same registry used by production callers."""

    transport = build_transport_registry()[request.resolved_model.provider.kind](
        request.resolved_model
    )
    return transport.invoke(request)


__all__ = [
    "LocalJsonServer",
    "RecordedRequest",
    "ScriptedResponse",
    "fixed_payload",
    "fixed_request",
    "invoke",
]
