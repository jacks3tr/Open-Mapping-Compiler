"""Streaming bundle application contracts."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from open_mapping import Compiler
from open_mapping.cli.app import app
from open_mapping.serialization.bundles import dump_bundle
from tests.support.streamlined import source_schema, target_schema


def _bundle(tmp_path: Path) -> Path:
    path = tmp_path / "mapping.omc"
    dump_bundle(
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle(),
        path,
    )
    return path


def test_apply_jsonl_streams_compact_outputs(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["apply", str(_bundle(tmp_path)), "--jsonl"],
        input='{"name":"Ada"}\n\n{"name":"Grace"}\n',
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == '{"name":"Ada"}\n{"name":"Grace"}\n'


def test_apply_jsonl_reports_first_invalid_line_without_output_for_that_line(
    tmp_path: Path,
) -> None:
    result = CliRunner().invoke(
        app,
        ["apply", str(_bundle(tmp_path)), "--jsonl"],
        input='{"name":"Ada"}\n{"name":3}\n{"name":"never"}\n',
    )

    assert result.exit_code == 4
    assert result.stdout == '{"name":"Ada"}\n'
    assert "input line: 2" in result.stderr


def test_apply_rejects_pretty_jsonl_before_loading_bundle(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["apply", str(tmp_path / "missing.omc"), "--jsonl", "--pretty"],
    )

    assert result.exit_code == 2
    assert "--pretty cannot be used with --jsonl" in result.stderr
