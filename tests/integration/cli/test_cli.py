"""CLI integration smoke tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def test_help() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "suggest" in result.stdout


def test_inspect_erp_source() -> None:
    result = _run("inspect", "benchmarks/erp-mes/source.schema.json")
    assert result.returncode == 0
    assert "/manufacturingOrder" in result.stdout


def test_suggest_erp() -> None:
    result = _run(
        "suggest",
        "benchmarks/erp-mes/source.schema.json",
        "benchmarks/erp-mes/target.schema.json",
        "--hints",
        "benchmarks/erp-mes/hints.yaml",
        "--report-format",
        "json",
    )
    assert result.returncode == 0
    assert "/legacyCode" in result.stdout
