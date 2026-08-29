"""Authoritative catalog for committed public JSON Schema artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter

from open_mapping.model.benchmarks import BenchmarkManifest
from open_mapping.model.bundles import MappingBundle
from open_mapping.model.hints import MappingHints
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.model_config import ModelProviderConfig
from open_mapping.model.model_protocol import MappingContextPackage, ModelMappingResponse
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.model.suggestions import SuggestionReport


@dataclass(frozen=True, slots=True)
class SchemaTarget:
    filename: str
    model: type[BaseModel]


SCHEMA_TARGETS = (
    SchemaTarget("mapping-document.schema.json", MappingDocument),
    SchemaTarget("mapping-hints.schema.json", MappingHints),
    SchemaTarget("suggestion-report.schema.json", SuggestionReport),
    SchemaTarget("suggestion-review.schema.json", SuggestionReviewDocument),
    SchemaTarget("benchmark-manifest.schema.json", BenchmarkManifest),
    SchemaTarget("model-provider-config.schema.json", ModelProviderConfig),
    SchemaTarget("model-mapping-context.schema.json", MappingContextPackage),
    SchemaTarget("model-mapping-response.schema.json", ModelMappingResponse),
    SchemaTarget("mapping-bundle.schema.json", MappingBundle),
)


def render_schema(model: type[BaseModel]) -> str:
    model.model_rebuild()
    schema = TypeAdapter(model).json_schema()
    value = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


__all__ = ["SCHEMA_TARGETS", "SchemaTarget", "render_schema"]
