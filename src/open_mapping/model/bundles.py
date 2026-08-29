"""Self-contained, verified mapping bundle models."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.providers import ModelRunDisclosure, ProviderDisclosure
from open_mapping.model.schema import SchemaDocument


class VerificationLevel(StrEnum):
    STATIC = "static"
    SAMPLES = "samples"


class BundleVerification(OpenMappingModel):
    level: VerificationLevel
    valid: Literal[True]
    sample_count: int = Field(ge=0)
    mapping_sha256: str = Field(pattern=r"^(?:[0-9a-f]{64})?$")
    verification_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_sample_level(self) -> BundleVerification:
        if self.level is VerificationLevel.STATIC and self.sample_count != 0:
            raise ValueError("static verification must have sample_count 0")
        if self.level is VerificationLevel.SAMPLES and self.sample_count < 1:
            raise ValueError("sample verification requires at least one sample")
        return self


class BundleProvenance(OpenMappingModel):
    suggestion_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    review_document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model_used: bool = False
    model_alias: str | None = None
    provider_disclosure: ProviderDisclosure | ModelRunDisclosure | None = None

    @model_validator(mode="after")
    def _validate_model_provenance(self) -> BundleProvenance:
        if not self.model_used and (
            self.model_alias is not None or self.provider_disclosure is not None
        ):
            raise ValueError("model provenance requires model_used=true")
        return self


class MappingBundle(OpenMappingModel):
    bundle_version: Literal["0.1"]
    compiler_version: str
    mapping: MappingDocument
    source_schema: SchemaDocument
    target_schema: SchemaDocument
    mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification: BundleVerification
    provenance: BundleProvenance


__all__ = [
    "BundleProvenance",
    "BundleVerification",
    "MappingBundle",
    "VerificationLevel",
]
