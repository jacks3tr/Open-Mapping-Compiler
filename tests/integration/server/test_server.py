"""Optional HTTP sidecar contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from open_mapping import Compiler, Mapper, OpenMappingError
from open_mapping.cli.app import app
from open_mapping.server.app import create_app
from tests.support.streamlined import source_schema, target_schema


def _client(*, api_key: str | None = None) -> TestClient:
    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    return TestClient(create_app(Mapper.from_bundle(bundle), api_key=api_key))


def test_server_health_metadata_validation_and_transform() -> None:
    with _client() as client:
        health = client.get("/health")
        metadata = client.get("/metadata")
        validation = client.post("/validate", json={"input": {"name": "Ada"}})
        transformed = client.post("/transform", json={"input": {"name": "Ada"}})

    assert health.json() == {
        "status": "ok",
        "mapping_id": "customer",
        "compiler_version": "0.2.0",
    }
    assert metadata.json()["mapping_id"] == "customer"
    assert validation.json() == {"valid": True, "issues": []}
    assert transformed.json() == {"output": {"name": "Ada"}}


def test_server_batch_limit_and_stable_validation_errors() -> None:
    with _client() as client:
        invalid = client.post("/transform", json={"input": {"name": 3}})
        oversized = client.post(
            "/transform-batch",
            json={"inputs": [{"name": "Ada"}] * 1001},
        )

    assert invalid.status_code == 422
    assert invalid.json()["issues"][0]["code"] == "SOURCE_SCHEMA_VALIDATION"
    assert oversized.status_code == 413
    assert oversized.json()["issues"][0]["code"] == "EVALUATION_LIMIT_EXCEEDED"


def test_server_request_shape_errors_use_stable_redacted_issues() -> None:
    with _client() as client:
        malformed = client.post(
            "/transform", content="{not-json", headers={"content-type": "application/json"}
        )
        extra = client.post(
            "/transform", json={"input": {"name": "Ada"}, "secret": "must-not-echo"}
        )

    assert malformed.status_code == 422
    assert malformed.json()["issues"][0]["code"] == "INVALID_INPUT"
    assert extra.json()["issues"][0]["code"] == "INVALID_INPUT"
    assert "must-not-echo" not in extra.text


def test_server_bearer_authentication() -> None:
    with _client(api_key="sidecar-secret") as client:
        missing = client.get("/health")
        valid = client.get("/health", headers={"Authorization": "Bearer sidecar-secret"})

    assert missing.status_code == 401
    assert valid.status_code == 200
    assert "sidecar-secret" not in missing.text


def test_serve_rejects_nonloopback_before_bundle_loading() -> None:
    result = CliRunner().invoke(app, ["serve", "missing.omc", "--host", "0.0.0.0"])

    assert result.exit_code == 2
    assert "--allow-remote" in result.stderr
    assert "missing.omc" not in result.stderr


def test_server_rejects_oversized_request_body() -> None:
    payload = '{"input":{"name":"' + ("x" * (10 * 1024 * 1024)) + '"}}'
    with _client() as client:
        response = client.post(
            "/transform",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["issues"][0]["code"] == "EVALUATION_LIMIT_EXCEEDED"


def test_invalid_bundle_fails_before_server_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from open_mapping.cli.serve import serve_command

    path = tmp_path / "invalid.omc"
    path.write_text("{}", encoding="utf-8")
    started = False

    def forbidden_run(*args: object, **kwargs: object) -> None:
        nonlocal started
        started = True

    with pytest.raises(OpenMappingError):
        monkeypatch.setattr("uvicorn.run", forbidden_run)
        serve_command(
            path,
            host="127.0.0.1",
            port=8080,
            allow_remote=False,
            api_key_env=None,
        )
    assert not started


def test_remote_server_requires_a_present_api_key_before_bundle_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPEN_MAPPING_SERVER_KEY", raising=False)
    result = CliRunner().invoke(
        app,
        [
            "serve",
            "missing.omc",
            "--host",
            "0.0.0.0",
            "--allow-remote",
            "--api-key-env",
            "OPEN_MAPPING_SERVER_KEY",
        ],
    )

    assert result.exit_code == 2
    assert "OPEN_MAPPING_SERVER_KEY" in result.stderr
    assert "missing.omc" not in result.stderr
