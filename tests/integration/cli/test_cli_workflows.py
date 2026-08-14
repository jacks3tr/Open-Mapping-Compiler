"""CLI workflow integration tests."""

from __future__ import annotations

import json
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
        timeout=120,
    )


def _write_sample(tmp_path: Path) -> Path:
    source = (ROOT / "benchmarks/erp-mes/samples.jsonl").read_text(encoding="utf-8").splitlines()[0]
    sample = json.loads(source)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(sample["input"]), encoding="utf-8")
    return path


def test_review_verify_run_compile(tmp_path: Path) -> None:
    root = ROOT / "benchmarks/erp-mes"
    suggestions = tmp_path / "suggestions.json"
    review_out = tmp_path / "mapping.yaml"
    suggest = _run(
        "suggest",
        str(root / "source.schema.json"),
        str(root / "target.schema.json"),
        "--hints",
        str(root / "hints.yaml"),
        "--suggestions-out",
        str(suggestions),
        "--report-format",
        "json",
    )
    assert suggest.returncode == 0, suggest.stderr

    result = _run(
        "review",
        str(suggestions),
        "--decisions",
        str(root / "review.yaml"),
        "--source",
        str(root / "source.schema.json"),
        "--target",
        str(root / "target.schema.json"),
        "--out",
        str(review_out),
        "--require-complete-review",
        "--force",
    )
    assert result.returncode == 0, result.stderr

    verify = _run(
        "verify",
        str(review_out),
        "--source",
        str(root / "source.schema.json"),
        "--target",
        str(root / "target.schema.json"),
        "--samples",
        str(root / "samples.jsonl"),
    )
    assert verify.returncode == 0, verify.stderr

    input_path = _write_sample(tmp_path)
    output_path = tmp_path / "output.json"
    run_result = _run(
        "run",
        str(review_out),
        "--source-schema",
        str(root / "source.schema.json"),
        "--target-schema",
        str(root / "target.schema.json"),
        "--input",
        str(input_path),
        "--out",
        str(output_path),
        "--force",
    )
    assert run_result.returncode == 0, run_result.stderr

    for language in ("python", "typescript"):
        generated = tmp_path / f"generated.{'py' if language == 'python' else 'ts'}"
        compile_result = _run(
            "compile",
            str(review_out),
            "--source",
            str(root / "source.schema.json"),
            "--target",
            str(root / "target.schema.json"),
            "--target-language",
            language,
            "--out",
            str(generated),
            "--force",
        )
        assert compile_result.returncode == 0, compile_result.stderr
        assert generated.exists()
