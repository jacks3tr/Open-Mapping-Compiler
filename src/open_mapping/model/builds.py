"""High-level compiler build results."""

from __future__ import annotations

from enum import StrEnum

from open_mapping.errors import OpenMappingError
from open_mapping.model.bundles import MappingBundle
from open_mapping.model.drafts import BuildDraft
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import VerificationReport


class BuildStatus(StrEnum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"


class BuildResult(OpenMappingModel):
    status: BuildStatus
    mapping_id: str
    bundle: MappingBundle | None
    suggestion_report: SuggestionReport
    review_document: SuggestionReviewDocument | None
    verification_report: VerificationReport | None
    issues: tuple[Issue, ...]
    draft: BuildDraft | None = None

    @property
    def ready(self) -> bool:
        return self.status is BuildStatus.READY

    @property
    def needs_review(self) -> bool:
        return self.status is BuildStatus.NEEDS_REVIEW

    def require_bundle(self) -> MappingBundle:
        if self.bundle is not None:
            return self.bundle
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.REVIEW_REQUIRED,
                    severity=Severity.ERROR,
                    component="compiler",
                    message=f"mapping {self.mapping_id!r} requires review before it can be bundled",
                    correction="Complete the generated review document and resume the saved draft.",
                    mapping_id=self.mapping_id,
                ),
            )
        )


__all__ = ["BuildResult", "BuildStatus"]
