"""Regression contracts for the pre-model suggestion workflow."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import pytest

from tests.integration.cli.conftest import ROOT

_EXAMPLE = ROOT / "examples" / "erp-mes"
_FROZEN_REPORT = _EXAMPLE / "suggestions.json"


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


class _RecordingProvider(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, object]]] = []
    queued_bodies: ClassVar[list[bytes]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        type(self).requests.append(json.loads(self.rfile.read(length)))
        response = type(self).queued_bodies.pop(0) if type(self).queued_bodies else b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


@pytest.fixture
def provider_url() -> Generator[str]:
    _RecordingProvider.requests = []
    _RecordingProvider.queued_bodies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _write_single_field_schemas(directory: Path) -> tuple[Path, Path]:
    source = directory / "source.schema.json"
    target = directory / "target.schema.json"
    source.write_text(
        json.dumps(
            {
                "$id": "source",
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    target.write_text(
        json.dumps(
            {
                "$id": "target",
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    return source, target


def _custom_provider_response() -> bytes:
    return json.dumps(
        {
            "protocol_version": "0.1",
            "proposals": [
                {
                    "target_path": "/value",
                    "abstain": False,
                    "selected_source_paths": ["/value"],
                    "expression": {"op": "get", "path": "/value"},
                    "reason": "The custom protocol selected the direct field.",
                }
            ],
        }
    ).encode("utf-8")


def test_suggest_without_model_writes_the_frozen_serialized_baseline_report(
    tmp_path: Path,
) -> None:
    report = tmp_path / "suggestions.json"

    result = _run_cli(
        ROOT,
        "suggest",
        str(_EXAMPLE / "source.schema.json"),
        str(_EXAMPLE / "target.schema.json"),
        "--samples",
        str(_EXAMPLE / "samples.jsonl"),
        "--hints",
        str(_EXAMPLE / "hints.yaml"),
        "--suggestions-out",
        str(report),
    )

    assert result.returncode == 0, result.stderr
    assert report.read_bytes() == _FROZEN_REPORT.read_bytes()


def test_models_config_in_working_directory_does_not_call_network_without_model(
    tmp_path: Path, provider_url: str
) -> None:
    source, target = _write_single_field_schemas(tmp_path)
    (tmp_path / "open-mapping.models.yaml").write_text(
        "\n".join(
            (
                'config_version: "0.1"',
                "providers:",
                "  local:",
                "    kind: custom-http",
                f"    base_url: {provider_url}",
                "    api_key_env: null",
                "    headers_from_env: {}",
                "    timeout_seconds: 1",
                "    max_retries: 0",
                "models:",
                "  test-model:",
                "    provider: local",
                "    model_id: local-test-model",
                "    structured_output: json",
                "    context_mode: auto",
                "    input_token_budget: 1024",
                "    max_output_tokens: 1024",
                "    target_batch_size: 1",
                "    candidate_limit_per_target: 1",
                "    parameters: {}",
                "",
            )
        ),
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "suggest",
        str(source),
        str(target),
        "--report-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    assert _RecordingProvider.requests == []
    assert json.loads(result.stdout)["provider_disclosure"] is None


def test_provider_url_preserves_the_existing_custom_protocol(
    tmp_path: Path, provider_url: str
) -> None:
    source, target = _write_single_field_schemas(tmp_path)
    _RecordingProvider.queued_bodies = [_custom_provider_response()]

    result = _run_cli(
        ROOT,
        "suggest",
        str(source),
        str(target),
        "--provider-url",
        provider_url,
        "--report-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    assert len(_RecordingProvider.requests) == 1
    request = _RecordingProvider.requests[0]
    assert request["protocol_version"] == "0.1"
    assert request["task"] == "rerank-and-propose"
    assert request["target_path"] == "/value"
    report = json.loads(result.stdout)
    assert report["provider_disclosure"]["endpoint_origin"] == urlparse(provider_url).netloc


def test_provider_url_sends_opted_in_raw_samples_to_the_custom_protocol(
    tmp_path: Path, provider_url: str
) -> None:
    source, target = _write_single_field_schemas(tmp_path)
    samples = tmp_path / "samples.jsonl"
    samples.write_text(
        json.dumps({"id": "raw-sample", "input": {"value": "provider-visible"}}) + "\n",
        encoding="utf-8",
    )
    _RecordingProvider.queued_bodies = [_custom_provider_response()]

    result = _run_cli(
        ROOT,
        "suggest",
        str(source),
        str(target),
        "--samples",
        str(samples),
        "--provider-url",
        provider_url,
        "--allow-raw-samples",
        "--report-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    assert _RecordingProvider.requests[0]["raw_samples"] == [{"value": "provider-visible"}]
