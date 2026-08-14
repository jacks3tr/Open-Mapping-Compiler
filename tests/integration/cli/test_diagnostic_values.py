"""End-to-end privacy controls for verification diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.mappings import dump_mapping

ROOT = Path(__file__).resolve().parents[3]
_SECRET = "ultra-secret-value"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _write_diagnostic_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    source = tmp_path / "source.schema.json"
    target = tmp_path / "target.schema.json"
    mapping = tmp_path / "mapping.yaml"
    samples = tmp_path / "samples.jsonl"
    input_path = tmp_path / "input.json"
    schema = {
        "$id": "diagnostic-schema",
        "type": "object",
        "required": ["quantity"],
        "properties": {"quantity": {"type": "integer"}},
    }
    source.write_text(json.dumps(schema), encoding="utf-8")
    target.write_text(json.dumps(schema), encoding="utf-8")
    dump_mapping(
        MappingDocument(
            mapping_version="0.1",
            id="diagnostic-mapping",
            source_schema="diagnostic-schema",
            source_schema_version="unversioned",
            target_schema="diagnostic-schema",
            target_schema_version="unversioned",
            rules=(
                {
                    "target": "/quantity",
                    "expression": {"op": "get", "path": "/quantity", "document": "input"},
                },
            ),
        ),
        mapping,
    )
    invalid_input = {"quantity": _SECRET}
    samples.write_text(
        json.dumps({"id": "sample-1", "input": invalid_input}) + "\n", encoding="utf-8"
    )
    input_path.write_text(json.dumps(invalid_input), encoding="utf-8")
    return source, target, mapping, samples, input_path


@pytest.mark.parametrize(
    ("diagnostic_values", "expected_summary"),
    [(False, False), (True, True)],
)
def test_verify_diagnostic_values_are_opt_in_and_redacted(
    tmp_path: Path, diagnostic_values: bool, expected_summary: bool
) -> None:
    source, target, mapping, samples, _input_path = _write_diagnostic_fixture(tmp_path)
    args = [
        "verify",
        str(mapping),
        "--source",
        str(source),
        "--target",
        str(target),
        "--samples",
        str(samples),
    ]
    if diagnostic_values:
        args.append("--diagnostic-values")

    result = _run(*args)

    assert result.returncode == 4, result.stderr
    rendered = result.stdout + result.stderr
    assert "source sample has incompatible type at /quantity" in rendered
    assert _SECRET not in rendered
    assert ("observed string(length=18)" in rendered) is expected_summary


@pytest.mark.parametrize(
    ("diagnostic_values", "expected_summary"),
    [(False, False), (True, True)],
)
def test_run_diagnostic_values_are_opt_in_and_redacted(
    tmp_path: Path, diagnostic_values: bool, expected_summary: bool
) -> None:
    source, target, mapping, _samples, input_path = _write_diagnostic_fixture(tmp_path)
    output_path = tmp_path / "output.json"
    args = [
        "run",
        str(mapping),
        "--source-schema",
        str(source),
        "--target-schema",
        str(target),
        "--input",
        str(input_path),
        "--out",
        str(output_path),
    ]
    if diagnostic_values:
        args.append("--diagnostic-values")

    result = _run(*args)

    assert result.returncode == 4, result.stderr
    rendered = result.stdout + result.stderr
    assert "source sample has incompatible type at /quantity" in rendered
    assert _SECRET not in rendered
    assert ("observed string(length=18)" in rendered) is expected_summary
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("diagnostic_values", "expected_summary"),
    [(False, False), (True, True)],
)
def test_suggest_diagnostic_values_are_opt_in_and_redacted(
    tmp_path: Path, diagnostic_values: bool, expected_summary: bool
) -> None:
    source, target, _mapping, samples, _input_path = _write_diagnostic_fixture(tmp_path)
    args = ["suggest", str(source), str(target), "--samples", str(samples)]
    if diagnostic_values:
        args.append("--diagnostic-values")

    result = _run(*args)

    assert result.returncode == 2, result.stderr
    rendered = result.stdout + result.stderr
    assert "source sample has incompatible type at /quantity" in rendered
    assert _SECRET not in rendered
    assert ("observed string(length=18)" in rendered) is expected_summary
    assert "Traceback" not in rendered
