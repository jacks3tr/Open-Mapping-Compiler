"""Code generation tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.codegen.python import generate_python
from open_mapping.codegen.typescript import generate_typescript
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument


def _fixture() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "s",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name", "qty"],
            "properties": {"name": {"type": "string"}, "qty": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "quantity": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="t",
    )
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=(
            {"target": "/name", "expression": {"op": "get", "path": "/name"}},
            {"target": "/quantity", "expression": {"op": "get", "path": "/qty"}},
        ),
    )
    return source, target, mapping


def test_generate_deterministic() -> None:
    source, target, mapping = _fixture()
    py1 = generate_python(mapping, source_schema=source, target_schema=target)
    py2 = generate_python(mapping, source_schema=source, target_schema=target)
    ts1 = generate_typescript(mapping, source_schema=source, target_schema=target)
    ts2 = generate_typescript(mapping, source_schema=source, target_schema=target)
    assert py1.source == py2.source
    assert ts1.source == ts2.source


def test_generated_runtimes_execute() -> None:
    source, target, mapping = _fixture()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        py_path = root / "m.py"
        ts_path = root / "m.ts"
        py_path.write_text(
            generate_python(mapping, source_schema=source, target_schema=target).source,
            encoding="utf-8",
        )
        ts_path.write_text(
            generate_typescript(mapping, source_schema=source, target_schema=target).source,
            encoding="utf-8",
        )
        data = '{"name":"x","qty":1}'
        py = subprocess.run(
            [sys.executable, str(Path("tools/run_generated_python.py")), str(py_path)],
            input=data,
            text=True,
            capture_output=True,
            check=False,
        )
        ts = subprocess.run(
            ["node", str(Path("tools/run_generated_typescript.mjs")), str(ts_path)],
            input=data,
            text=True,
            capture_output=True,
            check=False,
        )
        assert py.returncode == 0
        assert ts.returncode == 0
        assert py.stdout.strip() == ts.stdout.strip()
