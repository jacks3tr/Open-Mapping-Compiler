"""Fixtures for the streamlined public workflow tests."""

from __future__ import annotations

import json
from pathlib import Path

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument


def source_schema() -> SchemaDocument:
    return parse_json_schema(
        {
            "$id": "source.customer",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Canonical customer name"}},
        },
        schema_id=None,
        source_uri="source.schema.json",
    )


def target_schema() -> SchemaDocument:
    return parse_json_schema(
        {
            "$id": "target.customer",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Canonical customer name"}},
        },
        schema_id=None,
        source_uri="target.schema.json",
    )


def identity_mapping() -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="customer",
        source_schema="source.customer",
        source_schema_version="unversioned",
        target_schema="target.customer",
        target_schema_version="unversioned",
        rules=(
            {
                "target": "/name",
                "expression": {"op": "get", "document": "input", "path": "/name"},
                "confidence": 1.0,
                "confidence_method": "manual",
            },
        ),
    )


def write_local_model_config(path: Path, base_url: str) -> None:
    path.write_text(
        json.dumps(
            {
                "config_version": "0.1",
                "providers": {
                    "local": {
                        "kind": "custom-http",
                        "base_url": base_url,
                        "max_retries": 0,
                    }
                },
                "models": {
                    "mapper": {
                        "provider": "local",
                        "model_id": "local-model",
                        "context_mode": "targeted",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def local_model_response(target_path: str) -> dict[str, object]:
    return {
        "protocol_version": "0.1",
        "proposals": [
            {
                "target_path": target_path,
                "abstain": False,
                "selected_source_paths": [],
                "expression": {"op": "literal", "value": "ready"},
                "reason": "Local model proposal.",
            }
        ],
    }
