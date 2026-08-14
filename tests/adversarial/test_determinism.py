"""Ordering and atomic CLI boundaries remain deterministic under contention."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.cli import common
from open_mapping.model.json_types import JsonValue

ROOT = Path(__file__).resolve().parents[2]


def test_shuffled_source_keys_produce_identical_schema() -> None:
    first: JsonValue = {
        "$id": "source",
        "type": "object",
        "properties": {"z": {"type": "string"}, "a": {"type": "integer"}},
    }
    second: JsonValue = {
        "properties": {"a": {"type": "integer"}, "z": {"type": "string"}},
        "type": "object",
        "$id": "source",
    }
    left = parse_json_schema(first, schema_id=None, source_uri="source.json")
    right = parse_json_schema(second, schema_id=None, source_uri="source.json")
    assert left == right


def test_concurrent_independent_cli_processes_read_same_file() -> None:
    schema = ROOT / "examples/erp-mes/source.schema.json"

    def inspect() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "open_mapping.cli.app", "inspect", str(schema)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: inspect(), range(4)))
    assert {result.returncode for result in results} == {0}
    assert len({result.stdout for result in results}) == 1


def test_existing_cli_output_requires_force(tmp_path: Path) -> None:
    output = tmp_path / "suggestions.json"
    output.write_text("sentinel", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "open_mapping.cli.app",
            "suggest",
            str(ROOT / "examples/erp-mes/source.schema.json"),
            str(ROOT / "examples/erp-mes/target.schema.json"),
            "--suggestions-out",
            str(output),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 2
    assert output.read_text(encoding="utf-8") == "sentinel"


def test_interrupted_atomic_output_set_restores_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    real_replace = os.replace
    replacements = 0

    def interrupt_on_second_commit(source: str | Path, destination: str | Path) -> None:
        nonlocal replacements
        if str(source).endswith(".tmp"):
            replacements += 1
            if replacements == 2:
                raise OSError("simulated interrupted atomic write")
        real_replace(source, destination)

    monkeypatch.setattr(common, "replace", interrupt_on_second_commit)
    with pytest.raises(OSError, match="interrupted"):
        common.write_outputs({first: "new-first", second: "new-second"}, force=True)
    assert first.read_text(encoding="utf-8") == "old-first"
    assert second.read_text(encoding="utf-8") == "old-second"
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob(".*.bak"))
