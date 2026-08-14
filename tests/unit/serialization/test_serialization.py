"""Serialization tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.mappings import dump_mapping, load_mapping, mapping_sha256
from open_mapping.serialization.yaml_loader import DuplicateKeySafeLoader


def _mapping() -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="1",
        target_schema="t",
        target_schema_version="1",
        rules=(
            {
                "target": "/name",
                "expression": {"op": "get", "path": "/name", "document": "input"},
            },
        ),
    )


def test_safe_yaml_rejects_duplicate_keys_and_objects() -> None:
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("a: 1\na: 2", Loader=DuplicateKeySafeLoader)
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("!!python/object/apply:os.system []", Loader=DuplicateKeySafeLoader)


def test_mapping_round_trip(tmp_path: Path) -> None:
    mapping = _mapping()
    path = tmp_path / "mapping.yaml"
    dump_mapping(mapping, path)
    loaded = load_mapping(path)
    assert loaded == mapping
    assert mapping_sha256(loaded) == mapping_sha256(mapping)


def test_mapping_json_round_trip(tmp_path: Path) -> None:
    mapping = _mapping()
    path = tmp_path / "mapping.json"
    dump_mapping(mapping, path)
    assert load_mapping(path) == mapping
