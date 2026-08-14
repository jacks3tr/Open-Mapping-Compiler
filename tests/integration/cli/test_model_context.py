"""Sanitized model-context preview CLI contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.integration.cli.conftest import CliFiles, run_cli


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "config_version": "0.1",
                "providers": {
                    "local": {
                        "kind": "custom-http",
                        "base_url": "http://127.0.0.1:8765/model",
                        "headers_from_env": {"X-Test": "LOCAL_FAKE_TOKEN"},
                    }
                },
                "models": {
                    "mapper": {
                        "provider": "local",
                        "model_id": "fake-mapper",
                        "context_mode": "targeted",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_model_context_writes_exact_hashed_sanitized_package_without_calling_provider(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    config = tmp_path / "models.yaml"
    output = tmp_path / "context.json"
    _write_config(config)

    result = run_cli(
        "model-context",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--samples",
        str(cli_files.samples),
        "--instruction",
        "Use the approved business status.",
        "--out",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == result.stdout
    wrapper = json.loads(result.stdout)
    assert wrapper["context_version"] == "0.1"
    assert wrapper["model_alias"] == "mapper"
    assert wrapper["provider_kind"] == "custom-http"
    assert wrapper["raw_samples_included"] is False
    assert len(wrapper["packages"]) == 1
    item = wrapper["packages"][0]
    assert item["context_sha256"] == _canonical_sha256(item["package"])
    assert item["package"]["raw_samples"] is None
    serialized = json.dumps(wrapper, sort_keys=True)
    assert "127.0.0.1" not in serialized
    assert "LOCAL_FAKE_TOKEN" not in serialized
    assert result.stderr == ""


def test_model_context_raw_samples_require_opt_in_and_output_honors_force(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    config = tmp_path / "models.yaml"
    output = tmp_path / "context.json"
    output.write_text("keep", encoding="utf-8")
    _write_config(config)
    args = (
        "model-context",
        str(cli_files.source),
        str(cli_files.target),
        "--models-config",
        str(config),
        "--model",
        "mapper",
        "--samples",
        str(cli_files.samples),
        "--allow-raw-samples",
        "--out",
        str(output),
    )

    collision = run_cli(*args)
    assert collision.returncode == 2
    assert output.read_text(encoding="utf-8") == "keep"

    replaced = run_cli(*args, "--force")
    assert replaced.returncode == 0, replaced.stderr
    wrapper = json.loads(output.read_text(encoding="utf-8"))
    assert wrapper["raw_samples_included"] is True
    assert wrapper["packages"][0]["package"]["raw_samples"] == [{"value": "ready"}]
