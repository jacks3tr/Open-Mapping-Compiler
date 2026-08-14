"""Verification report models."""

from enum import StrEnum

from open_mapping.model.issues import Issue, has_errors
from open_mapping.model.json_types import JsonValue, OpenMappingModel


class StaticVerificationResult(OpenMappingModel):
    issues: tuple[Issue, ...]
    mapped_target_paths: tuple[str, ...]
    mapping_sha256: str

    @property
    def valid(self) -> bool:
        return not has_errors(self.issues)


class SampleVerificationResult(OpenMappingModel):
    sample_id: str
    output: JsonValue | None
    issues: tuple[Issue, ...]

    @property
    def valid(self) -> bool:
        return not has_errors(self.issues)


class VerificationReport(OpenMappingModel):
    mapping_id: str
    static: StaticVerificationResult
    samples: tuple[SampleVerificationResult, ...]

    @property
    def valid(self) -> bool:
        return self.static.valid and all(sample.valid for sample in self.samples)


class SortMode(StrEnum):
    ISSUE = "issue"
    SAMPLE = "sample"
