"""Shared fixtures for the stable CLI contract."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.mappings import dump_mapping

ROOT = Path(__file__).resolve().parents[3]


def run_cli(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run the real module entry point with captured output streams."""
    return subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


@dataclass(frozen=True)
class CliFiles:
    source: Path
    target: Path
    mapping: Path
    static_invalid_mapping: Path
    samples: Path
    dynamic_invalid_samples: Path
    input: Path
    dynamic_invalid_input: Path


@pytest.fixture
def cli_files(tmp_path: Path) -> CliFiles:
    source = tmp_path / "source.schema.json"
    target = tmp_path / "target.schema.json"
    mapping = tmp_path / "mapping.yaml"
    static_invalid_mapping = tmp_path / "static-invalid.yaml"
    samples = tmp_path / "samples.jsonl"
    dynamic_invalid_samples = tmp_path / "dynamic-invalid.jsonl"
    input_path = tmp_path / "input.json"
    dynamic_invalid_input = tmp_path / "dynamic-invalid.json"
    schema = {
        "$id": "contract-schema",
        "type": "object",
        "required": ["value"],
        "properties": {
            "value": {
                "type": "string",
                "enum": ["ready", "done"],
                "description": "A bounded status value.",
            }
        },
    }
    source.write_text(json.dumps(schema), encoding="utf-8")
    target.write_text(json.dumps(schema), encoding="utf-8")
    dump_mapping(
        MappingDocument(
            mapping_version="0.1",
            id="contract-mapping",
            source_schema="contract-schema",
            source_schema_version="unversioned",
            target_schema="contract-schema",
            target_schema_version="unversioned",
            rules=(
                {
                    "target": "/value",
                    "expression": {"op": "get", "path": "/value", "document": "input"},
                },
            ),
        ),
        mapping,
    )
    dump_mapping(
        MappingDocument(
            mapping_version="0.1",
            id="static-invalid",
            source_schema="contract-schema",
            source_schema_version="unversioned",
            target_schema="contract-schema",
            target_schema_version="unversioned",
            rules=(
                {
                    "target": "/value",
                    "expression": {"op": "get", "path": "/missing", "document": "input"},
                },
            ),
        ),
        static_invalid_mapping,
    )
    valid_input = {"value": "ready"}
    invalid_input = {"value": 42}
    samples.write_text(json.dumps({"id": "valid", "input": valid_input}) + "\n", encoding="utf-8")
    dynamic_invalid_samples.write_text(
        json.dumps({"id": "invalid", "input": invalid_input}) + "\n", encoding="utf-8"
    )
    input_path.write_text(json.dumps(valid_input), encoding="utf-8")
    dynamic_invalid_input.write_text(json.dumps(invalid_input), encoding="utf-8")
    return CliFiles(
        source=source,
        target=target,
        mapping=mapping,
        static_invalid_mapping=static_invalid_mapping,
        samples=samples,
        dynamic_invalid_samples=dynamic_invalid_samples,
        input=input_path,
        dynamic_invalid_input=dynamic_invalid_input,
    )
