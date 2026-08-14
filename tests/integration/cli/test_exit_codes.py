"""Stable process exit codes and root diagnostic boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from open_mapping.cli.app import app
from open_mapping.model.issues import Issue, IssueCode, Severity
from tests.integration.cli.conftest import CliFiles, run_cli


def test_stable_zero_two_three_four_and_five_exit_codes(
    cli_files: CliFiles, tmp_path: Path
) -> None:
    success = run_cli("--help")
    usage = run_cli("inspect", str(cli_files.source), "--schema-format", "invalid")
    static = run_cli(
        "verify",
        str(cli_files.static_invalid_mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--samples",
        str(cli_files.samples),
    )
    dynamic = run_cli(
        "verify",
        str(cli_files.mapping),
        "--source",
        str(cli_files.source),
        "--target",
        str(cli_files.target),
        "--samples",
        str(cli_files.dynamic_invalid_samples),
    )
    provider = run_cli(
        "suggest",
        str(cli_files.source),
        str(cli_files.target),
        "--provider-url",
        "http://127.0.0.1:9",
        "--require-provider",
        "--suggestions-out",
        str(tmp_path / "suggestions.json"),
    )

    assert [
        success.returncode,
        usage.returncode,
        static.returncode,
        dynamic.returncode,
        provider.returncode,
    ] == [0, 2, 3, 4, 5]
    for result in (usage, static, dynamic, provider):
        assert "Traceback" not in result.stderr


def test_benchmark_gate_failure_is_exit_seven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "manifest.yaml").write_text("id: ignored\n", encoding="utf-8")
    issue = Issue(
        code=IssueCode.BENCHMARK_GATE_FAILED,
        severity=Severity.ERROR,
        component="benchmark.gates",
        message="synthetic gate failure",
        correction="Fix the benchmark behavior.",
    )
    monkeypatch.setattr(
        "open_mapping.cli.benchmark.run_benchmark_pack",
        lambda *_args, **_kwargs: SimpleNamespace(
            id="synthetic",
            metrics=SimpleNamespace(model_dump_json=lambda **_kwargs: "{}"),
            confidence_counts={},
            disposition_counts={},
            gate_issues=(issue,),
        ),
    )

    result = CliRunner().invoke(app, ["benchmark", str(pack), "--enforce-gates"])

    assert result.exit_code == 7, result.output
    assert "GATE_FAILED" in result.stderr
    assert "GATE_FAILED" not in result.stdout
    assert "Traceback" not in result.output


def test_keyboard_interrupt_exits_130_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(*args: object, **kwargs: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("open_mapping.cli.app.inspect_command", interrupt)

    result = CliRunner().invoke(app, ["inspect", "unused.json"])

    assert result.exit_code == 130, result.output
    assert "interrupted" in result.output.lower()
    assert "Traceback" not in result.output


def test_root_help_documents_semantics_privacy_review_and_exit_codes() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    help_text = result.stdout.lower()
    for phrase in (
        "privacy",
        "raw samples",
        "confidence",
        "disposition",
        "noninteractive review",
        "exit codes",
        "required provider",
    ):
        assert phrase in help_text
    for code in ("0", "2", "3", "4", "5", "6", "7", "8"):
        assert code in result.stdout
