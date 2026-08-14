"""Generated programs quote every mapping-controlled string as inert data."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.codegen.python import generate_python
from open_mapping.codegen.typescript import generate_typescript
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument

ROOT = Path(__file__).resolve().parents[2]


def _fixture() -> tuple[SchemaDocument, SchemaDocument, MappingDocument, str, str]:
    field = 'quote" newline\n slash\\ snowman-☃'
    pointer = "/" + field.replace("~", "~0").replace("/", "~1")
    payload = (
        "__import__('pathlib').Path('OWNED').write_text('x');\n`touch OWNED` ${process.env.TOKEN}"
    )
    source = parse_json_schema(
        {"$id": "source", "type": "object"}, schema_id=None, source_uri="source.json"
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": [field],
            "properties": {field: {"type": "string"}},
        },
        schema_id=None,
        source_uri="target.json",
    )
    mapping = MappingDocument(
        mapping_version="0.1",
        id='mapping"\n\\☃',
        source_schema="source",
        source_schema_version="unversioned",
        target_schema="target",
        target_schema_version="unversioned",
        rules=({"target": pointer, "expression": {"op": "literal", "value": payload}},),
    )
    return source, target, mapping, field, payload


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_generated_source_injection_remains_inert(language: str, tmp_path: Path) -> None:
    source, target, mapping, field, payload = _fixture()
    if language == "python":
        artifact = generate_python(mapping, source_schema=source, target_schema=target)
        generated = tmp_path / "generated.py"
        runner = [
            sys.executable,
            str((ROOT / "tools/run_generated_python.py").resolve()),
            str(generated),
        ]
    else:
        artifact = generate_typescript(mapping, source_schema=source, target_schema=target)
        generated = tmp_path / "generated.ts"
        runner = [
            "node",
            str((ROOT / "tools/run_generated_typescript.mjs").resolve()),
            str(generated),
        ]
    generated.write_text(artifact.source, encoding="utf-8")
    completed = subprocess.run(
        runner,
        cwd=tmp_path,
        input="{}",
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {field: payload}
    for directory in (tmp_path, ROOT):
        assert not (directory / "OWNED").exists()


def test_generated_source_injection_uses_only_absolute_paths_in_isolated_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _source, _target, _mapping, field, payload = _fixture()
    observed_args: list[str] = []
    observed_cwd: Path | None = None

    def controlled_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal observed_args, observed_cwd
        observed_args = args
        observed_cwd = Path(str(kwargs["cwd"]))
        return subprocess.CompletedProcess(args, 0, json.dumps({field: payload}), "")

    monkeypatch.setattr(subprocess, "run", controlled_run)

    test_generated_source_injection_remains_inert("python", tmp_path)

    assert observed_cwd == tmp_path
    assert all(Path(argument).is_absolute() for argument in observed_args[:3])


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_generated_program_runner_preserves_isolated_cwd(language: str, tmp_path: Path) -> None:
    if language == "python":
        generated = tmp_path / "cwd.py"
        generated.write_text(
            "import os\ndef transform(_source: object) -> object:\n    return os.getcwd()\n",
            encoding="utf-8",
        )
        command = [
            sys.executable,
            str((ROOT / "tools/run_generated_python.py").resolve()),
            str(generated),
        ]
    else:
        generated = tmp_path / "cwd.ts"
        generated.write_text(
            "export function transform(_source: unknown): unknown { return process.cwd(); }\n",
            encoding="utf-8",
        )
        command = [
            "node",
            str((ROOT / "tools/run_generated_typescript.mjs").resolve()),
            str(generated),
        ]

    completed = subprocess.run(
        command,
        cwd=tmp_path,
        input="{}",
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert Path(json.loads(completed.stdout)).resolve() == tmp_path.resolve()
