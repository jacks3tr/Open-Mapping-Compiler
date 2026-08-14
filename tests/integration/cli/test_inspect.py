"""Inspect command contract tests."""

from __future__ import annotations

from pathlib import Path

from tests.integration.cli.conftest import CliFiles, run_cli


def test_inspect_renders_canonical_field_details(cli_files: CliFiles) -> None:
    result = run_cli("inspect", str(cli_files.source))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "/value" in result.stdout
    assert "required=True" in result.stdout
    assert "ready" in result.stdout
    assert "A bounded status value." in result.stdout


def test_invalid_schema_format_is_usage_error_before_file_loading(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    result = run_cli("inspect", str(missing), "--schema-format", "json-scehma")

    assert result.returncode == 2
    assert "json-scehma" in result.stderr
    assert "missing.json" not in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_schema_is_public_input_diagnostic_without_traceback(tmp_path: Path) -> None:
    result = run_cli("inspect", str(tmp_path / "missing.json"))

    assert result.returncode == 2
    assert "INVALID_INPUT" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
