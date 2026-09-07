"""Contract impact is machine-readable and does not rewrite the original bundle."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from open_mapping import Compiler
from open_mapping.cli.app import app
from open_mapping.serialization.bundles import dump_bundle
from tests.support.streamlined import source_schema, target_schema


def test_impact_command_returns_json_for_unchanged_contracts(tmp_path: Path) -> None:
    bundle = tmp_path / "mapping.omc"
    source, target = tmp_path / "source.json", tmp_path / "target.json"
    source.write_text(source_schema().canonical_source_json, encoding="utf-8")
    target.write_text(target_schema().canonical_source_json, encoding="utf-8")
    dump_bundle(
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle(),
        bundle,
    )
    before = bundle.read_bytes()
    result = CliRunner().invoke(app, ["impact", str(bundle), str(source), str(target)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert not report["requires_review"]
    assert report["rules"][0]["status"] == "unchanged"
    assert bundle.read_bytes() == before
