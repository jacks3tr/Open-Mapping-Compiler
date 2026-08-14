"""Shared interpreter/generated-Python/generated-TypeScript conformance corpus."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.codegen.python import generate_python
from open_mapping.codegen.typescript import generate_typescript
from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.mappings import _evaluate_mapping_document
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument

ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT / "tests" / "golden" / "codegen" / "full" / "cases.jsonl"
ERROR_CODE = re.compile(
    r"(SOURCE_PATH_NOT_FOUND|TYPE_MISMATCH|NUMERIC_PRECISION_RISK|DIVIDE_BY_ZERO|INVALID_DATE|INVALID_EXPRESSION|EVALUATION_LIMIT_EXCEEDED|OVERLAPPING_TARGET_ASSIGNMENT)"
)


def _load_cases() -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line
    )


CASES = _load_cases()


def _source_schema() -> SchemaDocument:
    source = parse_json_schema(
        {
            "$id": "conformance-source",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": [
                "text",
                "number",
                "divisor",
                "boolean",
                "nullable",
                "missing",
                "date",
                "items",
            ],
            "properties": {
                "text": {"type": "string"},
                "number": {"type": "number"},
                "divisor": {"type": "number"},
                "boolean": {"type": "boolean"},
                "nullable": {"type": ["string", "null"]},
                "missing": {"type": "string"},
                "date": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["value", "inner"],
                        "properties": {
                            "value": {"type": "integer"},
                            "inner": {"type": "array", "items": {"type": "integer"}},
                        },
                    },
                },
            },
        },
        schema_id=None,
        source_uri="conformance-source",
    )
    return source


def _schema_for_value(value: object) -> dict[str, object]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        item_schemas = [_schema_for_value(item) for item in value]
        return {"type": "array", "items": item_schemas[0] if item_schemas else {}}
    assert isinstance(value, dict)
    return {
        "type": "object",
        "properties": {str(key): _schema_for_value(item) for key, item in value.items()},
    }


def _target_schema(case: dict[str, Any]) -> SchemaDocument:
    if "expected" in case:
        result_schema = _schema_for_value(case["expected"]["result"])
        if case["expression"]["op"] in {"add", "subtract", "multiply", "divide", "round"} or (
            case["expression"]["op"] == "cast" and case["expression"].get("target_type") == "number"
        ):
            result_schema = {"type": "number"}
    elif case["id"] in {
        "numeric_string_empty",
        "numeric_string_whitespace",
        "numeric_string_hex",
        "numeric_string_infinity",
        "numeric_string_underscore",
        "divide_by_zero",
        "unsafe_integer_string",
        "huge_integer_arithmetic",
        "huge_integer_cast_number",
    }:
        result_schema = {"type": "number"}
    elif case["id"] == "huge_integer_semantic_equality":
        result_schema = {"type": "boolean"}
    else:
        result_schema = {"type": "string"}
    return parse_json_schema(
        {
            "$id": "conformance-target",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["result"],
            "properties": {"result": result_schema},
        },
        schema_id=None,
        source_uri="conformance-target",
    )


def _mapping(case: dict[str, Any]) -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id=f"conformance-{case['id']}",
        source_schema="conformance-source",
        source_schema_version="unversioned",
        target_schema="conformance-target",
        target_schema_version="unversioned",
        rules=({"target": "/result", "expression": case["expression"]},),
    )


def _interpreter(mapping: MappingDocument, source: JsonValue) -> tuple[object | None, str | None]:
    try:
        return _evaluate_mapping_document(mapping, source), None
    except OpenMappingError as error:
        return None, error.issues[0].code.value


def _generated(command: list[str], source: JsonValue) -> tuple[object | None, str | None]:
    completed = subprocess.run(
        command,
        input=json.dumps(source, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode == 0:
        return json.loads(completed.stdout), None
    match = ERROR_CODE.search(completed.stderr)
    assert match is not None, completed.stderr
    return None, match.group(1)


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_full_cross_runtime_conformance(case: dict[str, Any], tmp_path: Path) -> None:
    source_schema = _source_schema()
    target_schema = _target_schema(case)
    mapping = _mapping(case)
    python_path = tmp_path / "mapping.py"
    typescript_path = tmp_path / "mapping.ts"
    python_path.write_text(
        generate_python(mapping, source_schema=source_schema, target_schema=target_schema).source,
        encoding="utf-8",
    )
    typescript_path.write_text(
        generate_typescript(
            mapping, source_schema=source_schema, target_schema=target_schema
        ).source,
        encoding="utf-8",
    )
    node = shutil.which("node")
    assert node is not None
    typecheck = subprocess.run(
        [
            node,
            str(ROOT / "tools" / "run_generated_typescript.mjs"),
            "--typecheck",
            str(typescript_path),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert typecheck.returncode == 0, typecheck.stderr

    outcomes = (
        _interpreter(mapping, case["input"]),
        _generated(
            [sys.executable, str(ROOT / "tools" / "run_generated_python.py"), str(python_path)],
            case["input"],
        ),
        _generated(
            [node, str(ROOT / "tools" / "run_generated_typescript.mjs"), str(typescript_path)],
            case["input"],
        ),
    )
    if "expected_error" in case:
        assert [error for _, error in outcomes] == [case["expected_error"]] * 3
    else:
        assert all(error is None for _, error in outcomes), outcomes
        assert all(semantic_json_equal(output, case["expected"]) for output, _ in outcomes)


def test_conformance_corpus_covers_every_v01_operation_and_required_error_code() -> None:
    operations: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("op"), str):
                operations.add(value["op"])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for case in CASES:
        visit(case["expression"])
    assert operations == {
        "get",
        "literal",
        "object",
        "array",
        "map",
        "coalesce",
        "concat",
        "cast",
        "if",
        "equals",
        "not",
        "and",
        "or",
        "lookup",
        "add",
        "subtract",
        "multiply",
        "divide",
        "round",
        "parse_date",
        "format_date",
    }
    assert {case.get("expected_error") for case in CASES} >= {
        "SOURCE_PATH_NOT_FOUND",
        "TYPE_MISMATCH",
        "NUMERIC_PRECISION_RISK",
        "DIVIDE_BY_ZERO",
        "INVALID_DATE",
    }
