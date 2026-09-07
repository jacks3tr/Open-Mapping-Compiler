"""Simple public entry point for local or model-assisted schema mapping."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from open_mapping.adapters.openapi import OpenApiSelector
from open_mapping.compiler import Compiler
from open_mapping.model.hints import MappingHints
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ProviderKind, ResolvedModel
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.providers.transports.base import TransportFactory
from open_mapping.verification.dynamic import VerificationSample


def map_schemas(
    source: Path | str | JsonValue | SchemaDocument,
    target: Path | str | JsonValue | SchemaDocument,
    *,
    source_format: Literal["json-schema", "openapi", "json-data"] = "json-schema",
    source_selector: str | OpenApiSelector | None = None,
    target_format: Literal["json-schema", "openapi"] = "json-schema",
    target_selector: str | OpenApiSelector | None = None,
    model: str | ResolvedModel | None = None,
    models_config: Path | None = None,
    samples: Path | Sequence[VerificationSample] | None = None,
    hints: Path | MappingHints | None = None,
    instruction: str | None = None,
    allow_raw_samples: bool = False,
    require_model: bool = False,
    offline: bool = False,
    model_concurrency: int = 1,
    transport_registry: Mapping[ProviderKind, TransportFactory] | None = None,
) -> SuggestionReport:
    """Return one structured mapping result, using a model only when requested."""

    return Compiler(
        model=model,
        offline=offline,
        model_concurrency=model_concurrency,
        transport_registry=transport_registry,
        models_config=models_config,
        allow_raw_samples=allow_raw_samples,
        require_model=require_model,
    ).map(
        source=source,
        target=target,
        source_format=source_format,
        source_selector=source_selector,
        target_format=target_format,
        target_selector=target_selector,
        samples=samples,
        hints=hints,
        instruction=instruction,
    )


__all__ = ["map_schemas"]
