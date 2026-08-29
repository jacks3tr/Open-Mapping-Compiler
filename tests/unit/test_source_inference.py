"""Deterministic schema inference from JSON source records."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from open_mapping import OpenMappingError, infer_source_schema
from open_mapping.model.schema import JsonType
from open_mapping.source_inference import infer_source_data, load_source_data


def test_inference_merges_records_without_value_specific_constraints() -> None:
    inference = infer_source_data(
        [
            {
                "active": True,
                "count": 1,
                "name": "Ada",
                "optional": "first-only",
                "readings": [{"value": 1}, {"value": 1.5}],
            },
            {
                "active": False,
                "count": 2.0,
                "name": "Grace",
                "readings": [{"value": 2}],
            },
        ],
        source_uri="records.json",
    )

    schema = inference.schema
    assert schema.field("/active").types == frozenset({JsonType.BOOLEAN})  # type: ignore[union-attr]
    assert schema.field("/count").types == frozenset({JsonType.INTEGER})  # type: ignore[union-attr]
    assert schema.field("/name").required is True  # type: ignore[union-attr]
    assert schema.field("/optional").required is False  # type: ignore[union-attr]
    assert schema.field("/readings/items/value").types == frozenset(  # type: ignore[union-attr]
        {JsonType.NUMBER}
    )
    document = json.loads(schema.canonical_source_json)
    assert "enum" not in document["properties"]["name"]
    assert "examples" not in document["properties"]["name"]
    assert "additionalProperties" not in document
    assert inference.records[0]["name"] == "Ada"


def test_inference_is_stable_across_record_and_key_order() -> None:
    first = infer_source_schema([{"b": 2, "a": "x"}, {"a": "y", "b": 3}])
    second = infer_source_schema([{"b": 3, "a": "y"}, {"a": "x", "b": 2}])

    assert first == second
    assert first.schema_id.startswith("urn:open-mapping:inferred-source:")


def test_inference_reports_empty_array_item_shapes() -> None:
    inference = infer_source_data({"items": []})

    assert inference.schema.field("/items") is not None
    assert inference.schema.field("/items/items") is None
    assert [issue.severity.value for issue in inference.issues] == ["warning", "info"]
    assert inference.issues[0].source_path == "/items"


@pytest.mark.parametrize(
    "data",
    [None, "record", 1, [], [{"ok": True}, "bad"], {"value": math.inf}],
)
def test_inference_rejects_inputs_that_cannot_define_record_mappings(data: object) -> None:
    with pytest.raises(OpenMappingError, match="INVALID_INPUT"):
        infer_source_schema(data)  # type: ignore[arg-type]


def test_inference_rejects_non_json_objects_and_record_limits() -> None:
    with pytest.raises(OpenMappingError, match="non-string object key"):
        infer_source_schema({1: "bad"})  # type: ignore[dict-item]
    with pytest.raises(OpenMappingError, match="unsupported value type"):
        infer_source_schema({"value": object()})
    with pytest.raises(OpenMappingError, match="too many records"):
        infer_source_schema([{}] * 10_001)


def test_source_data_file_loader_rejects_non_finite_json(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    path.write_text('{"value":NaN}', encoding="utf-8")

    with pytest.raises(OpenMappingError, match="invalid JSON in source data file"):
        load_source_data(path)
