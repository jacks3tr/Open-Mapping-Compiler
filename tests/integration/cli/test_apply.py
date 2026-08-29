"""One-command bundle application contract."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from open_mapping.cli.app import app
from tests.support.streamlined import source_schema, target_schema


def test_apply_reads_stdin_and_keeps_stdout_machine_clean(tmp_path: Path) -> None:
    from open_mapping import Compiler
    from open_mapping.serialization.bundles import dump_bundle

    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    path = tmp_path / "mapping.omc"
    dump_bundle(bundle, path)

    result = CliRunner().invoke(app, ["apply", str(path)], input='{"name":"Ada"}')

    assert result.exit_code == 0, result.output
    assert result.stdout == '{"name":"Ada"}\n'


def test_apply_rejects_duplicate_json_keys_without_a_traceback(tmp_path: Path) -> None:
    from open_mapping import Compiler
    from open_mapping.serialization.bundles import dump_bundle

    path = tmp_path / "mapping.omc"
    dump_bundle(
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle(),
        path,
    )
    result = CliRunner().invoke(app, ["apply", str(path)], input='{"name":"Ada","name":"x"}')

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "INVALID_INPUT" in result.stderr
    assert "Traceback" not in result.stderr
