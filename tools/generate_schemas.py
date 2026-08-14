"""Generate committed JSON Schemas from Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from open_mapping.model.benchmarks import BenchmarkManifest
from open_mapping.model.hints import MappingHints
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.model_config import ModelProviderConfig
from open_mapping.model.model_protocol import MappingContextPackage, ModelMappingResponse
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.model.suggestions import SuggestionReport

MappingDocument.model_rebuild()
MappingHints.model_rebuild()
SuggestionReport.model_rebuild()
SuggestionReviewDocument.model_rebuild()
BenchmarkManifest.model_rebuild()
ModelProviderConfig.model_rebuild()
MappingContextPackage.model_rebuild()
ModelMappingResponse.model_rebuild()


def schema_for(model: type[Any]) -> dict[str, Any]:
    schema = TypeAdapter(model).json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas"
    root.mkdir(parents=True, exist_ok=True)
    targets = {
        "mapping-document.schema.json": MappingDocument,
        "mapping-hints.schema.json": MappingHints,
        "suggestion-report.schema.json": SuggestionReport,
        "suggestion-review.schema.json": SuggestionReviewDocument,
        "benchmark-manifest.schema.json": BenchmarkManifest,
        "model-provider-config.schema.json": ModelProviderConfig,
        "model-mapping-context.schema.json": MappingContextPackage,
        "model-mapping-response.schema.json": ModelMappingResponse,
    }
    for name, model in targets.items():
        (root / name).write_text(
            json.dumps(schema_for(model), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
