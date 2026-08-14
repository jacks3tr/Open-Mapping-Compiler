"""Compile command validation and error classification tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_mapping.cli.app import app
from tests.integration.cli.conftest import CliFiles, run_cli


@pytest.mark.parametrize(("language", "suffix"), (("python", "py"), ("typescript", "ts")))
def test_compile_writes_supported_language(
    cli_files: CliFiles, tmp_path: Path, language: str, suffix: str
) -> None:
    output = tmp_path / f"generated.{suffix}"
    result = run_cli(
        "compile",
        str(cli_files.mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--target-language",
        language,
        "--out",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert result.stdout == ""
    assert result.stderr == ""


def test_invalid_target_language_is_exit_two_before_input_loading() -> None:
    result = run_cli(
        "compile",
        "missing.yaml",
        "--source",
        "missing-source.json",
        "--target",
        "missing-target.json",
        "--target-language",
        "javascript",
        "--out",
        "unused.js",
    )

    assert result.returncode == 2
    assert "javascript" in result.stderr
    assert "missing.yaml" not in result.stderr
    assert "Traceback" not in result.stderr


def test_compile_static_failure_is_three_not_codegen_six(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    output = tmp_path / "generated.py"
    result = run_cli(
        "compile",
        str(cli_files.static_invalid_mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--target-language",
        "python",
        "--out",
        str(output),
    )

    assert result.returncode == 3
    assert "SOURCE_PATH_NOT_FOUND" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_codegen_failure_is_six_without_traceback_or_partial_artifact(
    cli_files: CliFiles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generated.py"

    def fail_codegen(*args: object, **kwargs: object) -> object:
        raise ValueError("synthetic code generation failure")

    monkeypatch.setattr("open_mapping.cli.compile.generate_python", fail_codegen)
    result = CliRunner().invoke(
        app,
        [
            "compile",
            str(cli_files.mapping),
            "--source",
            str(cli_files.source),
            "--target",
            str(cli_files.target),
            "--target-language",
            "python",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 6, result.output
    assert "CODEGEN" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()
