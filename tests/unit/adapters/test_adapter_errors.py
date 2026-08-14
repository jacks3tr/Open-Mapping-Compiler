"""Adapter error handling tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import load_json_schema
from open_mapping.adapters.openapi import (
    OpenApiSelector,
    OpenApiSelectorKind,
    load_openapi_schema,
    load_schema,
)
from open_mapping.errors import OpenMappingError


def test_json_schema_cycles_and_allof(tmp_path: Path) -> None:
    cycle = tmp_path / "cycle.json"
    cycle.write_text(
        '{"$id":"c","type":"object","properties":{"child":{"$ref":"#/$defs/node"}},"$defs":{"node":{"$ref":"#"}}}',
        encoding="utf-8",
    )
    with pytest.raises(OpenMappingError):
        load_json_schema(cycle, schema_id=None)
    allof = tmp_path / "allof.json"
    allof.write_text(
        '{"$id":"a","allOf":[{"type":"object","properties":{"x":{"type":"string"}}},{"required":["x"]}]}',
        encoding="utf-8",
    )
    doc = load_json_schema(allof, schema_id=None)
    assert doc.field("/x") is not None


def _openapi(content: str) -> Path:
    path = Path("benchmarks/erp-mes") / "unused.yaml"
    path = Path(__file__).resolve().parent / "fixture.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_openapi_request_component_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "api.yaml"
    path.write_text(
        """openapi: 3.1.0
info: {title: x, version: "1"}
paths:
  /x:
    post:
      operationId: createX
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/X'}
      responses:
        "200":
          content:
            application/json:
              schema: {$ref: '#/components/schemas/X'}
components:
  schemas:
    X: {type: object, properties: {id: {type: string}}}
""",
        encoding="utf-8",
    )
    req = load_openapi_schema(
        path,
        selector=OpenApiSelector(kind=OpenApiSelectorKind.REQUEST, operation_id="createX"),
        schema_id=None,
    )
    assert req.field("/id") is not None
    component = load_openapi_schema(
        path,
        selector=OpenApiSelector(kind=OpenApiSelectorKind.COMPONENT, component_name="X"),
        schema_id=None,
    )
    assert component.schema_id == "X"
    with pytest.raises(OpenMappingError):
        load_schema(path, format_name="openapi", selector=None, schema_id=None)


def test_openapi_30_rejected(tmp_path: Path) -> None:
    path = tmp_path / "old.yaml"
    path.write_text('openapi: 3.0.0\ninfo: {title: x, version: "1"}\npaths: {}\n', encoding="utf-8")
    with pytest.raises(OpenMappingError):
        load_openapi_schema(
            path,
            selector=OpenApiSelector(kind=OpenApiSelectorKind.COMPONENT, component_name="X"),
            schema_id=None,
        )
