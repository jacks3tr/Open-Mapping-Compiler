"""Dynamic sample verification."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from pydantic import ConfigDict

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.evaluation.mappings import _evaluate_mapping_document
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.verification import (
    SampleVerificationResult,
    VerificationReport,
)
from open_mapping.verification.diagnostics import (
    validation_error_message,
    validation_error_sort_key,
)
from open_mapping.verification.static import verify_static
from open_mapping.verification.target_schema import validate_target_document


class _ExpectedMissing:
    """Unique marker distinguishing an omitted golden output from JSON null."""


_EXPECTED_MISSING = _ExpectedMissing()


class VerificationSample(OpenMappingModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    id: str
    input: JsonValue
    expected: JsonValue | _ExpectedMissing = _EXPECTED_MISSING


def load_verification_samples(path: Path) -> tuple[VerificationSample, ...]:
    samples: list[VerificationSample] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenMappingError(
                (
                    Issue(
                        code=IssueCode.INVALID_INPUT,
                        severity=Severity.ERROR,
                        component="verification.dynamic",
                        message=f"invalid JSONL sample at line {line_number}",
                        correction="Use one JSON object per line.",
                    ),
                )
            ) from exc
        samples.append(VerificationSample.model_validate(raw))
    return tuple(samples)


def _source_issues(
    schema: SchemaDocument,
    document: JsonValue,
    sample_id: str,
    *,
    diagnostic_values: bool = False,
) -> tuple[Issue, ...]:
    raw = json.loads(schema.canonical_source_json)
    validator = Draft202012Validator(raw)
    result: list[Issue] = []
    for error in sorted(validator.iter_errors(document), key=validation_error_sort_key):
        result.append(
            Issue(
                code=IssueCode.SOURCE_SCHEMA_VALIDATION,
                severity=Severity.ERROR,
                component="verification.dynamic",
                message=validation_error_message(
                    "source sample", error, diagnostic_values=diagnostic_values
                ),
                correction="Provide source samples that match the source schema.",
                schema_id=schema.schema_id,
                sample_id=sample_id,
            )
        )
    return tuple(result)


def verify_samples(
    mapping: MappingDocument,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    samples: Sequence[VerificationSample],
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    diagnostic_values: bool = False,
) -> VerificationReport:
    static = verify_static(mapping, source_schema=source_schema, target_schema=target_schema)
    if not static.valid:
        return VerificationReport(mapping_id=mapping.id, static=static, samples=())
    sample_results: list[SampleVerificationResult] = []
    for sample in samples:
        issues: list[Issue] = list(
            _source_issues(
                source_schema,
                sample.input,
                sample.id,
                diagnostic_values=diagnostic_values,
            )
        )
        output: JsonValue | None = None
        if not issues:
            try:
                output = _evaluate_mapping_document(mapping, sample.input, limits)
            except OpenMappingError as exc:
                issues.extend(exc.issues)
        if output is not None:
            issues.extend(
                validate_target_document(
                    target_schema,
                    output,
                    sample_id=sample.id,
                    diagnostic_values=diagnostic_values,
                )
            )
            for invariant in mapping.invariants:
                issues.extend(
                    evaluate_invariant(
                        invariant,
                        input_document=sample.input,
                        output_document=output,
                        limits=limits,
                    )
                )
            if sample.expected is not _EXPECTED_MISSING:
                expected = cast(JsonValue, sample.expected)
                try:
                    same = semantic_json_equal(output, expected)
                except ValueError:
                    same = False
                    issues.append(
                        Issue(
                            code=IssueCode.GOLDEN_OUTPUT_MISMATCH,
                            severity=Severity.ERROR,
                            component="verification.dynamic",
                            message="expected output contains non-finite numbers",
                            correction="Use finite JSON values.",
                            sample_id=sample.id,
                        )
                    )
                if not same:
                    issues.append(
                        Issue(
                            code=IssueCode.GOLDEN_OUTPUT_MISMATCH,
                            severity=Severity.ERROR,
                            component="verification.dynamic",
                            message="mapping output does not match expected output",
                            correction="Correct the mapping or expected output.",
                            sample_id=sample.id,
                        )
                    )
        sample_results.append(
            SampleVerificationResult(sample_id=sample.id, output=output, issues=tuple(issues))
        )
    return VerificationReport(mapping_id=mapping.id, static=static, samples=tuple(sample_results))
