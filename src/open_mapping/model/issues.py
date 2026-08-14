"""Stable issue models used across the compiler."""

from collections.abc import Sequence
from enum import StrEnum

from open_mapping.model.json_types import OpenMappingModel


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_MAPPING_VERSION = "UNSUPPORTED_MAPPING_VERSION"
    SOURCE_PATH_NOT_FOUND = "SOURCE_PATH_NOT_FOUND"
    TARGET_PATH_NOT_FOUND = "TARGET_PATH_NOT_FOUND"
    DUPLICATE_TARGET_ASSIGNMENT = "DUPLICATE_TARGET_ASSIGNMENT"
    OVERLAPPING_TARGET_ASSIGNMENT = "OVERLAPPING_TARGET_ASSIGNMENT"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    LOSSY_CAST = "LOSSY_CAST"
    NUMERIC_PRECISION_RISK = "NUMERIC_PRECISION_RISK"
    REQUIRED_TARGET_UNMAPPED = "REQUIRED_TARGET_UNMAPPED"
    AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
    NO_MATCH = "NO_MATCH"
    SUGGESTION_TARGET_MISSING = "SUGGESTION_TARGET_MISSING"
    SUGGESTION_TARGET_DUPLICATE = "SUGGESTION_TARGET_DUPLICATE"
    STALE_SUGGESTION_REPORT = "STALE_SUGGESTION_REPORT"
    INVALID_REVIEW_DECISION = "INVALID_REVIEW_DECISION"
    REVIEW_TARGET_NOT_FOUND = "REVIEW_TARGET_NOT_FOUND"
    REVIEW_CANDIDATE_NOT_FOUND = "REVIEW_CANDIDATE_NOT_FOUND"
    INVALID_EXPRESSION = "INVALID_EXPRESSION"
    EVALUATION_LIMIT_EXCEEDED = "EVALUATION_LIMIT_EXCEEDED"
    DIVIDE_BY_ZERO = "DIVIDE_BY_ZERO"
    INVALID_DATE = "INVALID_DATE"
    REMOTE_REF_DISABLED = "REMOTE_REF_DISABLED"
    CYCLIC_REF = "CYCLIC_REF"
    UNSUPPORTED_SCHEMA_FEATURE = "UNSUPPORTED_SCHEMA_FEATURE"
    SOURCE_SCHEMA_VALIDATION = "SOURCE_SCHEMA_VALIDATION"
    TARGET_SCHEMA_VALIDATION = "TARGET_SCHEMA_VALIDATION"
    INVARIANT_FAILED = "INVARIANT_FAILED"
    GOLDEN_OUTPUT_MISMATCH = "GOLDEN_OUTPUT_MISMATCH"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    MODEL_CONTEXT_TOO_LARGE = "MODEL_CONTEXT_TOO_LARGE"
    CODEGEN_BLOCKED = "CODEGEN_BLOCKED"
    CODEGEN_SEMANTIC_MISMATCH = "CODEGEN_SEMANTIC_MISMATCH"
    BENCHMARK_GATE_FAILED = "BENCHMARK_GATE_FAILED"


class Issue(OpenMappingModel):
    code: IssueCode
    severity: Severity
    component: str
    message: str
    correction: str
    schema_id: str | None = None
    mapping_id: str | None = None
    rule_index: int | None = None
    sample_id: str | None = None
    source_path: str | None = None
    target_path: str | None = None


_SEVERITY_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def sort_issues(issues: Sequence[Issue]) -> tuple[Issue, ...]:
    """Return issues in a deterministic, input-order-independent order."""
    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                _SEVERITY_RANK[issue.severity],
                issue.code.value,
                issue.component,
                issue.mapping_id or "",
                issue.schema_id or "",
                issue.rule_index if issue.rule_index is not None else -1,
                issue.sample_id or "",
                issue.target_path or "",
                issue.source_path or "",
                issue.message,
            ),
        )
    )


def has_errors(issues: Sequence[Issue]) -> bool:
    return any(issue.severity == Severity.ERROR for issue in issues)
