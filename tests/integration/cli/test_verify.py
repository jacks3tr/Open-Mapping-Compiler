"""Verify command report and exit-code tests."""

from __future__ import annotations

import json

import pytest

from tests.integration.cli.conftest import CliFiles, run_cli


@pytest.mark.parametrize(
    ("report_format", "marker"),
    (("json", '"mapping_id"'), ("text", "Mapping:"), ("markdown", "# Verification Report")),
)
def test_verify_renders_selected_machine_or_human_report_to_stdout(
    cli_files: CliFiles, report_format: str, marker: str
) -> None:
    result = run_cli(
        "verify",
        str(cli_files.mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--samples",
        str(cli_files.samples),
        "--report-format",
        report_format,
    )

    assert result.returncode == 0, result.stderr
    assert marker in result.stdout
    assert result.stderr == ""


def test_verify_static_failure_is_exit_three_with_json_report(cli_files: CliFiles) -> None:
    result = run_cli(
        "verify",
        str(cli_files.static_invalid_mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--samples",
        str(cli_files.samples),
        "--report-format",
        "json",
    )

    assert result.returncode == 3
    assert json.loads(result.stdout)["static"]["issues"][0]["code"] == "SOURCE_PATH_NOT_FOUND"
    assert result.stderr == ""


def test_verify_dynamic_failure_is_exit_four(cli_files: CliFiles) -> None:
    result = run_cli(
        "verify",
        str(cli_files.mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--samples",
        str(cli_files.dynamic_invalid_samples),
    )

    assert result.returncode == 4
    assert (
        json.loads(result.stdout)["samples"][0]["issues"][0]["code"] == "SOURCE_SCHEMA_VALIDATION"
    )
    assert result.stderr == ""


def test_invalid_verify_report_format_is_exit_two_before_inputs() -> None:
    result = run_cli(
        "verify",
        "missing.yaml",
        "--source",
        "missing-source.json",
        "--target",
        "missing-target.json",
        "--samples",
        "missing.jsonl",
        "--report-format",
        "jsno",
    )

    assert result.returncode == 2
    assert "jsno" in result.stderr
    assert "Traceback" not in result.stderr
