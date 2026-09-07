"""Portable, hash-bound compiler drafts. No credentials or provider configuration."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from open_mapping.evaluation.limits import EvaluationLimits
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.serialization.canonical_json import canonical_json_bytes
from open_mapping.verification.dynamic import VerificationSample


class BuildDraftContent(OpenMappingModel):
    mapping_id: str
    source_schema: SchemaDocument
    target_schema: SchemaDocument
    suggestion_report: SuggestionReport
    samples: tuple[dict[str, JsonValue], ...] = ()
    require_samples: bool = False
    require_complete_review: bool = False
    limits: EvaluationLimits

    @model_validator(mode="after")
    def _validate_contracts(self) -> BuildDraftContent:
        report = self.suggestion_report
        if (report.source_schema_id, report.source_schema_version) != (
            self.source_schema.schema_id,
            self.source_schema.schema_version,
        ) or (report.target_schema_id, report.target_schema_version) != (
            self.target_schema.schema_id,
            self.target_schema.schema_version,
        ):
            raise ValueError("draft suggestions do not match the saved contracts")
        for sample in self.samples:
            VerificationSample.model_validate(sample)
        if self.require_samples and not self.samples:
            raise ValueError("draft requires verification samples")
        return self

    def sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.model_dump(mode="json"))).hexdigest()


class BuildDraft(OpenMappingModel):
    """A resumable snapshot; hashes detect changes, not authenticity."""

    draft_version: Literal["0.1"] = "0.1"
    content: BuildDraftContent
    content_sha256: str

    @model_validator(mode="after")
    def _validate_hash(self) -> BuildDraft:
        if self.content_sha256 != self.content.sha256():
            raise ValueError(
                "draft content hash mismatch; regenerate the draft rather than edit it"
            )
        return self

    @classmethod
    def seal(cls, content: BuildDraftContent) -> BuildDraft:
        # Snapshot caller-owned nested dictionaries, not just the frozen model shell.
        snapshot = BuildDraftContent.model_validate_json(content.model_dump_json())
        return cls(content=snapshot, content_sha256=snapshot.sha256())

    @classmethod
    def load(cls, path: Path | str) -> BuildDraft:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = ["BuildDraft", "BuildDraftContent"]
