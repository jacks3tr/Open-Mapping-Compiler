"""Complete-request provider redaction tests."""

from __future__ import annotations

import hashlib

from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.mappings import Evidence, EvidenceKind
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.model.suggestions import MatchCandidate
from open_mapping.providers import redaction
from open_mapping.providers.protocol import ProviderRequest, aggregate_provider_disclosure
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _request() -> ProviderRequest:
    return ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="source",
        target_schema_id="target",
        target_path="/email",
        candidates=(
            MatchCandidate(
                source_path="/contact",
                target_path="/email",
                raw_score=0.7,
                evidence=(
                    Evidence(
                        kind=EvidenceKind.DESCRIPTION_SIMILARITY,
                        detail="Bearer candidate-secret-token-abcdefghijklmnopqrstuvwxyz",
                    ),
                ),
            ),
        ),
        source_field_metadata=(
            SchemaField(
                pointer="/contact",
                types=frozenset({JsonType.STRING}),
                required=True,
                title="Contact 123456789012",
                description="Reach alice@example.com using api_key=super-secret-value",
            ),
        ),
        target_field_metadata=SchemaField(
            pointer="/email",
            types=frozenset({JsonType.STRING}),
            required=True,
            description="Authorization: bearer-secret-abcdefghijklmnopqrstuvwxyz",
        ),
        sample_profiles=(
            FieldProfile(
                pointer="/contact",
                observed_types=frozenset({JsonType.STRING}),
                sample_count=1,
                missing_count=0,
                null_count=0,
                distinct_count=1,
                pattern_classes=("email-like",),
            ),
        ),
        instruction_text="Prefer alice@example.com; token=abcdefghijklmnopqrstuvwxyz0123456789",
        raw_samples=({"contact": "alice@example.com", "pin": "123456789012"},),
    )


def test_sanitize_request_omits_raw_samples_and_redacts_all_free_text() -> None:
    sanitized, count = redaction.sanitize_provider_request(_request(), allow_raw_samples=False)

    rendered = str(sanitized.model_dump(mode="json"))
    assert sanitized.raw_samples is None
    assert "alice" not in rendered
    assert "super-secret-value" not in rendered
    assert "candidate-secret" not in rendered
    assert "123456789012" not in rendered
    assert count == 7


def test_sanitize_request_redacts_opted_in_raw_samples_and_counts_them() -> None:
    sanitized, count = redaction.sanitize_provider_request(_request(), allow_raw_samples=True)

    assert sanitized.raw_samples == ({"contact": "[REDACTED]@example.com", "pin": "[REDACTED]"},)
    assert count == 9


def test_redaction_is_recursive_and_leaves_non_text_values_unchanged() -> None:
    value = {"nested": ["bob@example.com", {"token": "api_key=hidden"}], "ok": 7}

    redacted, count = redaction.redact_json_with_count(value)

    assert redacted == {
        "nested": ["[REDACTED]@example.com", {"token": "api_key: [REDACTED]"}],
        "ok": 7,
    }
    assert count == 2


def test_recursive_redaction_redacts_keys_without_dropping_colliding_values() -> None:
    first = "Bearer one"
    second = "Bearer two"
    value: dict[str, object] = {
        first: "first value",
        second: "second value",
        "Bearer [REDACTED]": "literal collision",
        "nested": {"token=key-secret": "Bearer three"},
    }

    redacted, count = redaction.redact_json_with_count(value)

    assert redacted == {
        "Bearer [REDACTED]": "literal collision",
        "Bearer [REDACTED]#2": "first value",
        "Bearer [REDACTED]#3": "second value",
        "nested": {"token: [REDACTED]": "Bearer [REDACTED]"},
    }
    assert count == 4
    assert first not in str(redacted)
    assert second not in str(redacted)


def test_standard_short_bearer_is_redacted_across_complete_request_and_hash() -> None:
    request = _request().model_copy(
        update={
            "source_field_metadata": (
                _request()
                .source_field_metadata[0]
                .model_copy(
                    update={
                        "title": "Bearer schema-secret",
                        "description": "Bearer description-secret",
                    }
                ),
            ),
            "instruction_text": "Use Bearer instruction-secret",
            "raw_samples": (
                {
                    "Bearer key-secret": "Bearer sample-secret",
                    "safe": "value",
                },
            ),
        }
    )

    sanitized, count = redaction.sanitize_provider_request(request, allow_raw_samples=True)
    disclosure = aggregate_provider_disclosure(
        endpoint_origin="provider.example",
        raw_samples_included=True,
        requests=((sanitized, count),),
    )
    rendered = str(sanitized.model_dump(mode="json"))
    expected_bundle: list[object] = [sanitized.model_dump(mode="json")]

    assert "schema-secret" not in rendered
    assert "description-secret" not in rendered
    assert "instruction-secret" not in rendered
    assert "key-secret" not in rendered
    assert "sample-secret" not in rendered
    assert sanitized.raw_samples == ({"Bearer [REDACTED]": "Bearer [REDACTED]", "safe": "value"},)
    assert count == 7
    assert disclosure.redaction_count == 7
    assert (
        disclosure.request_sha256
        == hashlib.sha256(canonical_json_bytes(expected_bundle)).hexdigest()
    )
