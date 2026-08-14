"""Code generation shared models."""

from __future__ import annotations

from typing import Literal

from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.mappings import mapping_sha256


class GeneratedArtifact(OpenMappingModel):
    language: Literal["python", "typescript"]
    mapping_id: str
    mapping_sha256: str
    source: str


def artifact_metadata(
    mapping: MappingDocument, language: Literal["python", "typescript"]
) -> tuple[str, str]:
    return mapping.id, mapping_sha256(mapping)
