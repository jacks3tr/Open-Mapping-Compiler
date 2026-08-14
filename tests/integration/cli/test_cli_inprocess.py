"""In-process CLI workflow tests."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from open_mapping.cli.app import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[3]


def test_help_inprocess() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "suggest" in result.stdout


def test_inspect_inprocess() -> None:
    result = runner.invoke(app, ["inspect", str(ROOT / "benchmarks/erp-mes/source.schema.json")])
    assert result.exit_code == 0
    assert "/manufacturingOrder" in result.stdout


def test_suggest_inprocess(tmp_path: Path) -> None:
    root = ROOT / "benchmarks/erp-mes"
    suggestions = tmp_path / "suggestions.json"
    mapping_out = tmp_path / "mapping.yaml"
    result = runner.invoke(
        app,
        [
            "suggest",
            str(root / "source.schema.json"),
            str(root / "target.schema.json"),
            "--hints",
            str(root / "hints.yaml"),
            "--suggestions-out",
            str(suggestions),
            "--mapping-out",
            str(mapping_out),
            "--mapping-id",
            "demo",
            "--report-format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert suggestions.exists()
    assert mapping_out.exists()
    assert "/legacyCode" in result.stdout


def test_review_verify_run_compile_inprocess(tmp_path: Path) -> None:
    root = ROOT / "benchmarks/erp-mes"
    suggestions = tmp_path / "suggestions.json"
    mapping = tmp_path / "mapping.yaml"
    suggest = runner.invoke(
        app,
        [
            "suggest",
            str(root / "source.schema.json"),
            str(root / "target.schema.json"),
            "--hints",
            str(root / "hints.yaml"),
            "--suggestions-out",
            str(suggestions),
            "--report-format",
            "json",
        ],
    )
    assert suggest.exit_code == 0, suggest.output
    result = runner.invoke(
        app,
        [
            "review",
            str(suggestions),
            "--decisions",
            str(root / "review.yaml"),
            "--source",
            str(root / "source.schema.json"),
            "--target",
            str(root / "target.schema.json"),
            "--out",
            str(mapping),
            "--require-complete-review",
        ],
    )
    assert result.exit_code == 0, result.output
    verify = runner.invoke(
        app,
        [
            "verify",
            str(mapping),
            "--source",
            str(root / "source.schema.json"),
            "--target",
            str(root / "target.schema.json"),
            "--samples",
            str(root / "samples.jsonl"),
        ],
    )
    assert verify.exit_code == 0, verify.output
    sample = json.loads((root / "samples.jsonl").read_text(encoding="utf-8").splitlines()[0])
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(sample["input"]), encoding="utf-8")
    output_path = tmp_path / "output.json"
    run_result = runner.invoke(
        app,
        [
            "run",
            str(mapping),
            "--source-schema",
            str(root / "source.schema.json"),
            "--target-schema",
            str(root / "target.schema.json"),
            "--input",
            str(input_path),
            "--out",
            str(output_path),
        ],
    )
    assert run_result.exit_code == 0, run_result.output
    for language, suffix in (("python", "py"), ("typescript", "ts")):
        generated = tmp_path / f"generated.{suffix}"
        compile_result = runner.invoke(
            app,
            [
                "compile",
                str(mapping),
                "--source",
                str(root / "source.schema.json"),
                "--target",
                str(root / "target.schema.json"),
                "--target-language",
                language,
                "--out",
                str(generated),
            ],
        )
        assert compile_result.exit_code == 0, compile_result.output
        assert generated.exists()


def test_benchmark_inprocess() -> None:
    result = runner.invoke(app, ["benchmark", "benchmarks/account-segments", "--enforce-gates"])
    assert result.exit_code == 0, result.output
    assert "account-segments" in result.output
    assert "GATE_FAILED" not in result.stderr
    assert "json_report=" in result.stdout
    assert "markdown_report=" in result.stdout
