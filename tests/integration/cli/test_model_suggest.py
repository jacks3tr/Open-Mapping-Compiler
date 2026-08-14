"""Model-selected suggest CLI contracts through a deterministic local provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from tests.integration.cli.conftest import ROOT, CliFiles, run_cli


class _FakeModelHandler(BaseHTTPRequestHandler):
    mode: ClassVar[str] = "success"
    requests: ClassVar[list[dict[str, object]]] = []
    expected_context_path: ClassVar[Path | None] = None
    context_existed_before_call: ClassVar[bool] = False

    def do_POST(self) -> None:  # noqa: N802
        expected_context_path = type(self).expected_context_path
        if expected_context_path is not None:
            type(self).context_existed_before_call = expected_context_path.is_file()
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        type(self).requests.append(request)
        if type(self).mode == "failure":
            self.send_response(500)
            self.end_headers()
            return
        target_path = request["target_path"]
        if type(self).mode == "abstain":
            proposal = {
                "target_path": target_path,
                "abstain": True,
                "selected_source_paths": [],
                "expression": None,
                "reason": "The local fake abstained.",
            }
        elif type(self).mode == "static-invalid":
            proposal = {
                "target_path": target_path,
                "abstain": False,
                "selected_source_paths": [],
                "expression": {"op": "literal", "value": 42},
                "reason": "Deliberately wrong type.",
            }
        else:
            proposal = {
                "target_path": target_path,
                "abstain": False,
                "selected_source_paths": [],
                "expression": {"op": "literal", "value": "ready"},
                "reason": "Deterministic local fake proposal.",
            }
        body = json.dumps(
            {"protocol_version": "0.1", "proposals": [proposal]},
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


@pytest.fixture
def fake_model_url() -> Generator[str]:
    _FakeModelHandler.mode = "success"
    _FakeModelHandler.requests = []
    _FakeModelHandler.expected_context_path = None
    _FakeModelHandler.context_existed_before_call = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/model"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _write_config(
    path: Path,
    base_url: str,
    *,
    alias: str = "mapper",
    model_id: str = "fake-model",
    api_key_env: str | None = None,
) -> None:
    provider: dict[str, object] = {
        "kind": "custom-http",
        "base_url": base_url,
        "max_retries": 0,
    }
    if api_key_env is not None:
        provider["api_key_env"] = api_key_env
    path.write_text(
        json.dumps(
            {
                "config_version": "0.1",
                "providers": {"local": provider},
                "models": {
                    alias: {
                        "provider": "local",
                        "model_id": model_id,
                        "context_mode": "targeted",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _subprocess(
    *args: str,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", *args],
        cwd=cwd,
        env=os.environ if environment is None else environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def test_explicit_model_success_writes_sanitized_context_run_and_suggestion_reports(
    cli_files: CliFiles, tmp_path: Path, fake_model_url: str
) -> None:
    config = tmp_path / "models.yaml"
    context_out = tmp_path / "context.json"
    run_out = tmp_path / "run.json"
    suggestions_out = tmp_path / "suggestions.json"
    _write_config(config, fake_model_url)
    _FakeModelHandler.expected_context_path = context_out

    result = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--model-context-out",
        str(context_out),
        "--model-run-report-out",
        str(run_out),
        "--suggestions-out",
        str(suggestions_out),
        "--report-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    assert len(_FakeModelHandler.requests) == 1
    assert _FakeModelHandler.context_existed_before_call
    stdout_report = json.loads(result.stdout)
    assert stdout_report["suggestions"][0]["origin"] == "model"
    assert stdout_report["model_run_disclosure"]["model_alias"] == "mapper"
    assert json.loads(suggestions_out.read_text(encoding="utf-8")) == stdout_report
    context = json.loads(context_out.read_text(encoding="utf-8"))
    run_report = json.loads(run_out.read_text(encoding="utf-8"))
    assert context["packages"][0]["context_sha256"] == run_report["batch_runs"][0]["context_sha256"]
    assert run_report["issues"] == []
    assert "response" not in run_report["batch_runs"][0]
    serialized_reports = context_out.read_text(encoding="utf-8") + run_out.read_text(
        encoding="utf-8"
    )
    assert fake_model_url not in serialized_reports
    assert "Authorization" not in serialized_reports
    assert result.stderr == ""


def test_model_transport_failure_falls_back_with_warning_and_required_mode_is_fatal(
    cli_files: CliFiles, tmp_path: Path, fake_model_url: str
) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config, fake_model_url)
    _FakeModelHandler.mode = "failure"
    fallback_out = tmp_path / "fallback.json"
    fallback = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--suggestions-out",
        str(fallback_out),
        "--report-format",
        "json",
    )

    assert fallback.returncode == 0
    fallback_report = json.loads(fallback.stdout)
    assert fallback_report["suggestions"][0].get("origin", "deterministic") == "deterministic"
    assert any(issue["severity"] == "warning" for issue in fallback_report["issues"])
    assert "PROVIDER_FAILURE" in fallback.stderr
    assert fallback_out.exists()

    required_suggestions = tmp_path / "required.json"
    required_mapping = tmp_path / "required.yaml"
    required_context = tmp_path / "required-context.json"
    required_run = tmp_path / "required-run.json"
    required = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--require-model",
        "--model-context-out",
        str(required_context),
        "--model-run-report-out",
        str(required_run),
        "--suggestions-out",
        str(required_suggestions),
        "--mapping-out",
        str(required_mapping),
        "--mapping-id",
        "required",
        "--report-format",
        "json",
    )

    assert required.returncode == 5
    assert required.stdout == ""
    assert "PROVIDER_FAILURE" in required.stderr
    assert not required_suggestions.exists()
    assert not required_mapping.exists()
    assert required_context.exists()
    assert required_run.exists()


def test_required_model_accepts_valid_abstention_but_rejects_invalid_proposal(
    cli_files: CliFiles, tmp_path: Path, fake_model_url: str
) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config, fake_model_url)
    _FakeModelHandler.mode = "abstain"
    abstained = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--require-model",
        "--report-format",
        "json",
    )
    assert abstained.returncode == 0, abstained.stderr
    assert "Model abstained" in abstained.stdout

    _FakeModelHandler.mode = "static-invalid"
    invalid_out = tmp_path / "invalid.json"
    invalid = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--require-model",
        "--suggestions-out",
        str(invalid_out),
        "--report-format",
        "json",
    )
    assert invalid.returncode == 5
    assert invalid.stdout == ""
    assert not invalid_out.exists()
    assert "STATIC_" in invalid.stderr or "PROVIDER_RESPONSE_INVALID" in invalid.stderr


def test_config_precedence_selects_explicit_then_environment_then_project_default(
    cli_files: CliFiles, tmp_path: Path, fake_model_url: str
) -> None:
    explicit = tmp_path / "explicit.yaml"
    configured = tmp_path / "environment.yaml"
    default = tmp_path / "open-mapping.models.yaml"
    _write_config(explicit, fake_model_url, model_id="explicit-model")
    _write_config(configured, fake_model_url, model_id="environment-model")
    _write_config(default, fake_model_url, model_id="default-model")
    environment = {**os.environ, "OPEN_MAPPING_MODELS_CONFIG": str(configured)}

    explicit_result = _subprocess(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(explicit),
        "--model",
        "mapper",
        "--report-format",
        "json",
        cwd=tmp_path,
        environment=environment,
    )
    environment_result = _subprocess(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--model",
        "mapper",
        "--report-format",
        "json",
        cwd=tmp_path,
        environment=environment,
    )
    default_environment = dict(os.environ)
    default_environment.pop("OPEN_MAPPING_MODELS_CONFIG", None)
    default_result = _subprocess(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--model",
        "mapper",
        "--report-format",
        "json",
        cwd=tmp_path,
        environment=default_environment,
    )

    assert [
        result.returncode for result in (explicit_result, environment_result, default_result)
    ] == [
        0,
        0,
        0,
    ]
    assert [
        json.loads(result.stdout)["model_run_disclosure"]["model_id"]
        for result in (explicit_result, environment_result, default_result)
    ] == ["explicit-model", "environment-model", "default-model"]


@pytest.mark.parametrize("failure", ("unknown-alias", "invalid-config"))
def test_model_selection_errors_precede_schema_loading_and_network(
    tmp_path: Path, fake_model_url: str, failure: str
) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config, fake_model_url)
    alias = "missing" if failure == "unknown-alias" else "mapper"
    if failure == "invalid-config":
        raw = json.loads(config.read_text(encoding="utf-8"))
        raw["unexpected"] = True
        config.write_text(json.dumps(raw), encoding="utf-8")

    result = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        "--models-config",
        str(config),
        "--model",
        alias,
    )

    assert result.returncode == 2
    assert "missing-source" not in result.stderr
    assert not _FakeModelHandler.requests
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


def test_models_config_alone_is_offline_and_model_only_outputs_require_explicit_selection(
    cli_files: CliFiles, tmp_path: Path, fake_model_url: str
) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config, fake_model_url)
    baseline = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--report-format",
        "json",
    )
    assert baseline.returncode == 0, baseline.stderr
    assert not _FakeModelHandler.requests
    assert "model_run_disclosure" not in json.loads(baseline.stdout)

    without_model = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        "--model-context-out",
        str(tmp_path / "context.json"),
    )
    assert without_model.returncode == 2
    assert "requires --model" in without_model.stderr
    assert "missing-source" not in without_model.stderr


def test_missing_api_key_is_a_sanitized_required_model_failure_without_network(
    cli_files: CliFiles,
    tmp_path: Path,
    fake_model_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "models.yaml"
    credential_name = "OPEN_MAPPING_MISSING_LOCAL_FAKE_KEY"
    monkeypatch.delenv(credential_name, raising=False)
    _write_config(config, fake_model_url, api_key_env=credential_name)

    result = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--require-model",
        "--report-format",
        "json",
    )

    assert result.returncode == 5
    assert credential_name in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert not _FakeModelHandler.requests


def test_model_output_set_is_preflighted_and_force_replaces_it_before_network(
    cli_files: CliFiles, tmp_path: Path, fake_model_url: str
) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config, fake_model_url)
    context = tmp_path / "context.json"
    run_report = tmp_path / "run.json"
    suggestions = tmp_path / "suggestions.json"
    context.write_text("keep", encoding="utf-8")
    args = (
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--model-context-out",
        str(context),
        "--model-run-report-out",
        str(run_report),
        "--suggestions-out",
        str(suggestions),
        "--report-format",
        "json",
    )

    collision = run_cli(*args)
    assert collision.returncode == 2
    assert context.read_text(encoding="utf-8") == "keep"
    assert not _FakeModelHandler.requests
    assert not run_report.exists()
    assert not suggestions.exists()

    replaced = run_cli(*args, "--force")
    assert replaced.returncode == 0, replaced.stderr
    assert len(_FakeModelHandler.requests) == 1
    assert json.loads(context.read_text(encoding="utf-8"))["model_alias"] == "mapper"
    assert run_report.exists()
    assert suggestions.exists()


def test_suggest_help_explains_explicit_cost_privacy_and_review_behavior() -> None:
    result = run_cli("suggest", "--help")

    assert result.returncode == 0
    normalized = " ".join(result.stdout.lower().split())
    assert "only --model" in normalized
    assert "cost" in normalized
    assert "raw samples" in normalized
    assert "review" in normalized
    assert "--models-config" in result.stdout
    assert str(ROOT) not in result.stdout
