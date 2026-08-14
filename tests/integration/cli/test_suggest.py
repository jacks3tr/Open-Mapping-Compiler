"""Suggest command contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_mapping.cli.app import app
from tests.integration.cli.conftest import ROOT, CliFiles, run_cli


@pytest.mark.parametrize(
    ("option", "value"),
    (("--report-format", "jsno"), ("--assembly-policy", "everything")),
)
def test_invalid_typed_option_is_rejected_before_schema_loading(
    tmp_path: Path, option: str, value: str
) -> None:
    result = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        option,
        value,
    )

    assert result.returncode == 2
    assert value in result.stderr
    assert "missing-source" not in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "args",
    (
        ("--require-provider",),
        ("--instruction", "rank by business meaning"),
        ("--provider-token-env", "MODEL_TOKEN"),
    ),
)
def test_custom_provider_only_options_require_url_before_any_input_load(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        *args,
    )

    assert result.returncode == 2
    assert "requires --provider-url" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("args", "requirement"),
    (
        (("--allow-raw-samples",), "--allow-raw-samples requires --model or --provider-url"),
        (("--require-model",), "--require-model requires --model"),
    ),
)
def test_model_related_options_require_a_selection_before_any_input_load(
    tmp_path: Path, args: tuple[str, ...], requirement: str
) -> None:
    result = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        *args,
    )

    assert result.returncode == 2
    assert requirement in result.stderr
    assert "missing-source" not in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_model_and_custom_provider_are_mutually_exclusive_before_schema_loading(
    tmp_path: Path,
) -> None:
    result = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        "--provider-url",
        "http://127.0.0.1:9",
        "--model",
        "accurate-mapper",
    )

    assert result.returncode == 2
    assert "--provider-url and --model are mutually exclusive" in result.stderr
    assert "missing-source" not in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_model_without_resolved_configuration_fails_before_schema_loading(tmp_path: Path) -> None:
    result = run_cli(
        "suggest",
        str(tmp_path / "missing-source.json"),
        str(tmp_path / "missing-target.json"),
        "--model",
        "accurate-mapper",
    )

    assert result.returncode == 2
    assert "--model requires --models-config" in result.stderr
    assert "missing-source" not in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_all_local_inputs_are_validated_before_provider_call(
    cli_files: CliFiles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def forbidden_call(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("provider call must happen after local validation")

    monkeypatch.setattr("open_mapping.providers.http.call_http_provider", forbidden_call)
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(cli_files.source),
            str(cli_files.target),
            "--hints",
            str(tmp_path / "missing-hints.yaml"),
            "--provider-url",
            "http://127.0.0.1:9",
        ],
    )

    assert result.exit_code == 2, result.output
    assert not called
    assert "Traceback" not in result.output


def test_optional_provider_diagnostic_is_stderr_and_json_report_stays_stdout(
    cli_files: CliFiles,
) -> None:
    result = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--provider-url",
        "http://127.0.0.1:9",
        "--report-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["summary"]["total_targets"] == 1
    assert "PROVIDER_FAILURE" in result.stderr
    assert "Traceback" not in result.stderr


def test_output_set_is_preflighted_before_provider_contact(
    cli_files: CliFiles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suggestions = tmp_path / "suggestions.json"
    mapping = tmp_path / "assembled.yaml"
    mapping.write_text("keep", encoding="utf-8")
    called = False

    def forbidden_call(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("provider call must happen after output preflight")

    monkeypatch.setattr("open_mapping.providers.http.call_http_provider", forbidden_call)
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(cli_files.source),
            str(cli_files.target),
            "--provider-url",
            "http://127.0.0.1:9",
            "--suggestions-out",
            str(suggestions),
            "--mapping-out",
            str(mapping),
            "--mapping-id",
            "contract",
        ],
    )

    assert result.exit_code == 2, result.output
    assert not called
    assert not suggestions.exists()
    assert mapping.read_text(encoding="utf-8") == "keep"


def test_static_assembly_failure_leaves_no_partial_output_set(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    suggestions = tmp_path / "suggestions.json"
    mapping = tmp_path / "mapping.yaml"
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
                "required": ["value", "unmapped"],
                "properties": {
                    "value": {"type": "string"},
                    "unmapped": {"type": "integer"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "suggest",
        str(source),
        str(target),
        "--suggestions-out",
        str(suggestions),
        "--mapping-out",
        str(mapping),
        "--mapping-id",
        "must-fail",
    )

    assert result.returncode == 3, result.stderr
    assert not suggestions.exists()
    assert not mapping.exists()


def test_interrupted_output_replacement_rolls_back_entire_artifact_set(
    cli_files: CliFiles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suggestions = tmp_path / "suggestions.json"
    mapping = tmp_path / "assembled.yaml"
    import open_mapping.cli.common as common

    real_replace = common.replace
    calls = 0

    def fail_second_replace(source: Path | str, target: Path | str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic interrupted replacement")
        real_replace(source, target)

    monkeypatch.setattr(common, "replace", fail_second_replace)
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(cli_files.source),
            str(cli_files.target),
            "--suggestions-out",
            str(suggestions),
            "--mapping-out",
            str(mapping),
            "--mapping-id",
            "atomic-set",
        ],
    )

    assert result.exit_code == 2, result.output
    assert not suggestions.exists()
    assert not mapping.exists()
    assert not tuple(tmp_path.glob(".*.tmp"))
    assert not tuple(tmp_path.glob(".*.bak"))


def test_suggest_help_documents_provider_privacy_behavior() -> None:
    result = run_cli("suggest", "--help")

    assert result.returncode == 0
    normalized_help = " ".join(result.stdout.lower().replace("|", " ").split())
    assert "raw samples" in normalized_help
    assert "selected provider or model" in normalized_help
    assert "--require-provider" in result.stdout
    assert str(ROOT) not in result.stdout
