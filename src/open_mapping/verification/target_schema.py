"""Target schema validation for generated outputs."""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.diagnostics import (
    validation_error_message,
    validation_error_pointer,
    validation_error_sort_key,
)


def validate_target_document(
    schema: SchemaDocument,
    document: JsonValue,
    *,
    sample_id: str | None = None,
    diagnostic_values: bool = False,
) -> tuple[Issue, ...]:
    raw = json.loads(schema.canonical_source_json)
    validator = Draft202012Validator(raw)
    errors: list[Issue] = []
    for error in sorted(validator.iter_errors(document), key=validation_error_sort_key):
        errors.append(
            Issue(
                code=IssueCode.TARGET_SCHEMA_VALIDATION,
                severity=Severity.ERROR,
                component="verification.target_schema",
                message=validation_error_message(
                    "target document", error, diagnostic_values=diagnostic_values
                ),
                correction="Adjust the mapping so generated output matches the target schema.",
                schema_id=schema.schema_id,
                sample_id=sample_id,
                target_path=validation_error_pointer(error),
            )
        )
    return tuple(errors)
