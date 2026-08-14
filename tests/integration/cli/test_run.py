"""Run command output and failure contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.cli.conftest import CliFiles, run_cli


def _args(cli_files: CliFiles, input_path: Path, output_path: Path) -> tuple[str, ...]:
    return (
        "run",
        str(cli_files.mapping),
        "--source-schema",
        str(cli_files.source),
        "--target-schema",
        str(cli_files.target),
        "--input",
        str(input_path),
        "--out",
        str(output_path),
    )


def test_run_writes_output_atomically_without_clobbering_fixed_tmp_name(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    output = tmp_path / "output.json"
    collision = tmp_path / "output.json.tmp"
    collision.write_text("unrelated", encoding="utf-8")

    result = run_cli(*_args(cli_files, cli_files.input, output))

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert json.loads(output.read_text(encoding="utf-8")) == {"value": "ready"}
    assert collision.read_text(encoding="utf-8") == "unrelated"


def test_run_refuses_existing_output_without_force(cli_files: CliFiles, tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text("keep", encoding="utf-8")

    result = run_cli(*_args(cli_files, cli_files.input, output))

    assert result.returncode == 2
    assert "already exists" in result.stderr
    assert "Traceback" not in result.stderr
    assert output.read_text(encoding="utf-8") == "keep"


def test_run_static_failure_is_three_and_writes_nothing(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    output = tmp_path / "output.json"
    args = list(_args(cli_files, cli_files.input, output))
    args[1] = str(cli_files.static_invalid_mapping)

    result = run_cli(*args)

    assert result.returncode == 3
    assert "SOURCE_PATH_NOT_FOUND" in result.stderr
    assert not output.exists()


def test_run_dynamic_failure_is_four_and_writes_nothing(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    output = tmp_path / "output.json"

    result = run_cli(*_args(cli_files, cli_files.dynamic_invalid_input, output))

    assert result.returncode == 4
    assert "SOURCE_SCHEMA_VALIDATION" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()
