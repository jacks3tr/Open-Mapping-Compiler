"""Public runtime entry point."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.evaluation.mappings import _evaluate_mapping_document
from open_mapping.model.issues import Issue
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.dynamic import _source_issues, _source_issues_with_validator
from open_mapping.verification.static import require_static_valid
from open_mapping.verification.target_schema import (
    _target_issues_with_validator,
    validate_target_document,
)


def run_mapping(
    mapping: MappingDocument,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    source: JsonValue,
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    diagnostic_values: bool = False,
) -> JsonValue:
    require_static_valid(mapping, source_schema=source_schema, target_schema=target_schema)
    return _transform_prepared(
        mapping,
        source_schema=source_schema,
        target_schema=target_schema,
        source=source,
        limits=limits,
        diagnostic_values=diagnostic_values,
    )


def _transform_prepared(
    mapping: MappingDocument,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    source: JsonValue,
    limits: EvaluationLimits,
    diagnostic_values: bool,
    source_validator: Draft202012Validator | None = None,
    target_validator: Draft202012Validator | None = None,
) -> JsonValue:
    """Execute a mapping whose static contract was already verified."""

    source_issues = (
        _source_issues(
            source_schema,
            source,
            "runtime",
            diagnostic_values=diagnostic_values,
        )
        if source_validator is None
        else _source_issues_with_validator(
            source_validator,
            schema_id=source_schema.schema_id,
            document=source,
            sample_id="runtime",
            diagnostic_values=diagnostic_values,
        )
    )
    if source_issues:
        raise OpenMappingError(source_issues)
    output = _evaluate_mapping_document(mapping, source, limits)
    target_issues = (
        validate_target_document(
            target_schema,
            output,
            sample_id="runtime",
            diagnostic_values=diagnostic_values,
        )
        if target_validator is None
        else _target_issues_with_validator(
            target_validator,
            schema_id=target_schema.schema_id,
            document=output,
            sample_id="runtime",
            diagnostic_values=diagnostic_values,
        )
    )
    if target_issues:
        raise OpenMappingError(target_issues)
    invariant_issues: list[Issue] = []
    for invariant in mapping.invariants:
        issues = evaluate_invariant(
            invariant, input_document=source, output_document=output, limits=limits
        )
        if issues:
            invariant_issues.extend(issues)
    if invariant_issues:
        raise OpenMappingError(invariant_issues)
    return output


__all__ = ["run_mapping"]
