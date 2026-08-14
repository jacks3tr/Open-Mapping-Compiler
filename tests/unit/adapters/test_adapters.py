"""Adapter tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import load_json_schema, parse_json_schema
from open_mapping.adapters.openapi import (
    OpenApiSelector,
    OpenApiSelectorKind,
    load_openapi_schema,
    parse_openapi_selector,
)
from open_mapping.errors import OpenMappingError


def _schema_doc() -> dict[str, object]:
    return {
        "$id": "demo",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }


def test_json_schema_parse() -> None:
    doc = parse_json_schema(_schema_doc(), schema_id=None, source_uri="demo")
    assert doc.schema_id == "demo"
    assert doc.field("/name") is not None
    assert doc.field("/name").required  # type: ignore[union-attr]


def test_json_schema_rejects_remote_ref(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text('{"$id":"s","$ref":"https://example.com/x"}', encoding="utf-8")
    with pytest.raises(OpenMappingError):
        load_json_schema(path, schema_id=None)


def test_json_schema_rejects_nullable(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text(
        '{"$id":"s","type":"object","properties":{"x":{"type":"string","nullable":true}}}',
        encoding="utf-8",
    )
    with pytest.raises(OpenMappingError):
        load_json_schema(path, schema_id=None)


def test_openapi_selector_parse() -> None:
    selector = parse_openapi_selector("response:getX:200")
    assert selector.kind == OpenApiSelectorKind.RESPONSE
    assert selector.operation_id == "getX"
    with pytest.raises(OpenMappingError):
        parse_openapi_selector("bad")


def test_openapi_load(tmp_path: Path) -> None:
    path = tmp_path / "api.yaml"
    path.write_text(
        """openapi: 3.1.0
info: {title: x, version: "1"}
paths:
  /orders:
    get:
      operationId: getOrders
      responses:
        "200":
          content:
            application/json:
              schema:
                $id: order
                type: object
                properties:
                  id: {type: string}
""",
        encoding="utf-8",
    )
    doc = load_openapi_schema(
        path,
        selector=OpenApiSelector(
            kind=OpenApiSelectorKind.RESPONSE,
            operation_id="getOrders",
            status_code="200",
        ),
        schema_id=None,
    )
    assert doc.schema_id == "order"
