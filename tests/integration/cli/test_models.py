"""Model configuration CLI contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.integration.cli.conftest import ROOT, run_cli


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "config_version": "0.1",
                "providers": {
                    "local": {
                        "kind": "custom-http",
                        "base_url": "http://127.0.0.1:8765/model",
                    }
                },
                "models": {
                    "zippy": {"provider": "local", "model_id": "fake-fast"},
                    "accurate": {
                        "provider": "local",
                        "model_id": "fake-accurate",
                        "context_mode": "targeted",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_models_validate_emits_only_sanitized_structured_summary(tmp_path: Path) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config)

    result = run_cli("models", "validate", "--config", str(config))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["config_version"] == "0.1"
    assert payload["provider_count"] == 1
    assert payload["model_count"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", payload["config_sha256"])
    assert "127.0.0.1" not in result.stdout
    assert result.stderr == ""


def test_models_list_is_sorted_and_excludes_connection_and_credential_fields(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    _write_config(config)

    result = run_cli("models", "list", "--config", str(config))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["models"] == [
        {
            "alias": "accurate",
            "context_mode": "targeted",
            "model_id": "fake-accurate",
            "provider_kind": "custom-http",
            "provider_name": "local",
        },
        {
            "alias": "zippy",
            "context_mode": "auto",
            "model_id": "fake-fast",
            "provider_kind": "custom-http",
            "provider_name": "local",
        },
    ]
    assert "base_url" not in result.stdout
    assert "api_key" not in result.stdout
    assert result.stderr == ""


def test_models_invalid_config_is_a_traceback_free_input_failure(tmp_path: Path) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        json.dumps(
            {
                "config_version": "0.1",
                "providers": {
                    "local": {
                        "kind": "custom-http",
                        "base_url": "http://127.0.0.1:8765/model",
                    }
                },
                "models": {
                    "broken": {
                        "provider": "missing",
                        "model_id": "fake",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli("models", "validate", "--config", str(config))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "required document schema" in result.stderr
    assert "Traceback" not in result.stderr


def test_model_command_help_explains_cost_privacy_and_review() -> None:
    root_help = run_cli("--help")
    models_help = run_cli("models", "--help")

    assert root_help.returncode == models_help.returncode == 0
    combined = " ".join((root_help.stdout + models_help.stdout).lower().split())
    assert "cost" in combined
    assert "privacy" in combined
    assert "review" in combined
    assert "model-context" in root_help.stdout
    assert str(ROOT) not in combined
