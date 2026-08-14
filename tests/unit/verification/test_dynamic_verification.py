"""Public verification diagnostics must not disclose instance values."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.dynamic import VerificationSample, verify_samples
from open_mapping.verification.target_schema import validate_target_document


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["quantity"],
            "properties": {"quantity": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["quantity"],
            "properties": {"quantity": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


def _mapping() -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="diagnostics",
        source_schema="source",
        source_schema_version="unversioned",
        target_schema="target",
        target_schema_version="unversioned",
        rules=(
            {
                "target": "/quantity",
                "expression": {"op": "get", "path": "/quantity", "document": "input"},
            },
        ),
    )


def test_source_validation_diagnostic_has_category_path_and_no_raw_value() -> None:
    source, target = _schemas()
    report = verify_samples(
        _mapping(),
        source_schema=source,
        target_schema=target,
        samples=(VerificationSample(id="sample-1", input={"quantity": "secret-raw-value"}),),
    )
    message = report.samples[0].issues[0].message
    assert message == "source sample has incompatible type at /quantity"
    assert "secret-raw-value" not in message


def test_target_validation_diagnostic_has_category_path_and_no_raw_value() -> None:
    _source, target = _schemas()
    issue = validate_target_document(target, {"quantity": "secret-raw-value"})[0]
    assert issue.message == "target document has incompatible type at /quantity"
    assert "secret-raw-value" not in issue.message


def test_diagnostic_value_summary_requires_explicit_opt_in_and_is_redacted() -> None:
    source, target = _schemas()
    report = verify_samples(
        _mapping(),
        source_schema=source,
        target_schema=target,
        samples=(VerificationSample(id="sample-1", input={"quantity": "secret-raw-value"}),),
        diagnostic_values=True,
    )
    source_message = report.samples[0].issues[0].message
    target_message = validate_target_document(
        target, {"quantity": "secret-raw-value"}, diagnostic_values=True
    )[0].message
    assert "observed string(length=16)" in source_message
    assert "observed string(length=16)" in target_message
    assert "secret-raw-value" not in source_message
    assert "secret-raw-value" not in target_message


def test_schema_diagnostics_redact_required_enum_and_pattern_values() -> None:
    target = parse_json_schema(
        {
            "$id": "target-redaction",
            "type": "object",
            "required": ["customer"],
            "properties": {
                "customer": {"type": "string"},
                "status": {"type": "string", "enum": ["A"]},
                "account": {"type": "string", "pattern": "^[0-9]+$"},
            },
        },
        schema_id=None,
        source_uri="target-redaction",
    )
    issues = validate_target_document(
        target, {"status": "secret-status", "account": "secret-account"}
    )
    messages = {issue.message for issue in issues}
    assert messages == {
        "target document violates required-property constraint at /customer",
        "target document value is outside the allowed enum at /status",
        "target document string violates the required pattern at /account",
    }
    assert "secret-status" not in "\n".join(messages)
    assert "secret-account" not in "\n".join(messages)
