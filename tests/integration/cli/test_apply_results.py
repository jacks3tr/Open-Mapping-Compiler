"""JSONL collection preserves every record outcome and atomic file output."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from open_mapping import Compiler
from open_mapping.cli.app import app
from open_mapping.serialization.bundles import dump_bundle
from tests.support.streamlined import source_schema, target_schema


def test_jsonl_collect_records_parse_and_validation_errors(tmp_path: Path) -> None:
    bundle = tmp_path / "mapping.omc"
    dump_bundle(
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle(),
        bundle,
    )
    out = tmp_path / "results.jsonl"
    result = CliRunner().invoke(
        app,
        ["apply", str(bundle), "--jsonl", "--on-error", "collect", "--out", str(out)],
        input='{"name":"Ada"}\n\nnot-json\n{"name":3}\n{"name":"Grace"}\n',
    )
    assert result.exit_code == 4, result.output
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [record["index"] for record in records] == [0, 1, 2, 3]
    assert [record["success"] for record in records] == [True, False, False, True]
    assert records[1]["issues"][0]["code"] == "INVALID_INPUT"
    assert records[2]["issues"][0]["code"] == "SOURCE_SCHEMA_VALIDATION"
    assert records[-1]["output"] == {"name": "Grace"}
    assert not list(tmp_path.glob("*.tmp"))


def test_apply_cannot_overwrite_the_bundle_even_with_force(tmp_path: Path) -> None:
    bundle = tmp_path / "mapping.omc"
    dump_bundle(
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle(),
        bundle,
    )
    before = bundle.read_bytes()
    result = CliRunner().invoke(
        app, ["apply", str(bundle), "--out", str(bundle), "--force"], input='{"name":"Ada"}'
    )
    assert result.exit_code == 2
    assert bundle.read_bytes() == before
