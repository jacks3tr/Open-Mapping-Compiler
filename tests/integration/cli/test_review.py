"""Noninteractive review CLI contract tests."""

from __future__ import annotations

from pathlib import Path

from tests.integration.cli.conftest import ROOT, run_cli


def _suggestions(tmp_path: Path) -> tuple[Path, Path]:
    pack = ROOT / "benchmarks/erp-mes"
    suggestions = tmp_path / "suggestions.json"
    result = run_cli(
        "suggest",
        str(pack / "source.schema.json"),
        str(pack / "target.schema.json"),
        "--hints",
        str(pack / "hints.yaml"),
        "--suggestions-out",
        str(suggestions),
        "--report-format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    return pack, suggestions


def test_review_requires_decisions_option_not_second_positional(tmp_path: Path) -> None:
    pack, suggestions = _suggestions(tmp_path)
    output = tmp_path / "mapping.yaml"

    result = run_cli(
        "review",
        str(suggestions),
        str(pack / "review.yaml"),
        "--source",
        str(pack / "source.schema.json"),
        "--target",
        str(pack / "target.schema.json"),
        "--out",
        str(output),
    )

    assert result.returncode == 2
    assert "--decisions" in result.stderr
    assert not output.exists()


def test_review_accepts_document_noninteractively_via_decisions_option(tmp_path: Path) -> None:
    pack, suggestions = _suggestions(tmp_path)
    output = tmp_path / "mapping.yaml"

    result = run_cli(
        "review",
        str(suggestions),
        "--decisions",
        str(pack / "review.yaml"),
        "--source",
        str(pack / "source.schema.json"),
        "--target",
        str(pack / "target.schema.json"),
        "--out",
        str(output),
        "--require-complete-review",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert output.exists()


def test_stale_review_exits_eight_and_writes_no_artifacts(tmp_path: Path) -> None:
    pack, suggestions = _suggestions(tmp_path)
    decisions = tmp_path / "stale.yaml"
    mapping = tmp_path / "mapping.yaml"
    report = tmp_path / "review.json"
    decisions.write_text(
        "review_version: '0.1'\n"
        "suggestion_report_sha256: stale\n"
        "mapping_id: stale-review\n"
        "decisions: []\n",
        encoding="utf-8",
    )

    result = run_cli(
        "review",
        str(suggestions),
        "--decisions",
        str(decisions),
        "--source",
        str(pack / "source.schema.json"),
        "--target",
        str(pack / "target.schema.json"),
        "--out",
        str(mapping),
        "--review-report-out",
        str(report),
    )

    assert result.returncode == 8
    assert "STALE_SUGGESTION_REPORT" in result.stderr
    assert "Traceback" not in result.stderr
    assert not mapping.exists()
    assert not report.exists()


def test_review_preflights_all_outputs_without_partial_artifact(tmp_path: Path) -> None:
    pack, suggestions = _suggestions(tmp_path)
    mapping = tmp_path / "mapping.yaml"
    report = tmp_path / "review.json"
    report.write_text("keep", encoding="utf-8")

    result = run_cli(
        "review",
        str(suggestions),
        "--decisions",
        str(pack / "review.yaml"),
        "--source",
        str(pack / "source.schema.json"),
        "--target",
        str(pack / "target.schema.json"),
        "--out",
        str(mapping),
        "--review-report-out",
        str(report),
    )

    assert result.returncode == 2
    assert not mapping.exists()
    assert report.read_text(encoding="utf-8") == "keep"


def test_review_help_shows_exact_automation_safe_syntax() -> None:
    result = run_cli("review", "--help")

    assert result.returncode == 0
    assert "SUGGESTIONS" in result.stdout
    assert "--decisions" in result.stdout
    assert "DECISIONS" not in result.stdout.split("Options", 1)[0]
