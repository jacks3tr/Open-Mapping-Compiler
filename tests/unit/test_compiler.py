"""High-level in-memory compiler contract."""

from __future__ import annotations

import hashlib

import pytest


def test_compiler_builds_a_deterministic_identity_bundle_without_files() -> None:
    from open_mapping import BuildStatus, Compiler
    from open_mapping.serialization.bundles import dumps_bundle
    from tests.support.streamlined import source_schema, target_schema

    result = Compiler().build(
        source=source_schema(),
        target=target_schema(),
        mapping_id="customer",
    )

    assert result.status is BuildStatus.READY
    assert result.ready
    assert result.require_bundle().mapping.id == "customer"
    assert result.require_bundle().verification.sample_count == 0
    repeated = Compiler().build(
        source=source_schema(), target=target_schema(), mapping_id="customer"
    )
    assert dumps_bundle(result.require_bundle()) == dumps_bundle(repeated.require_bundle())


def test_compiler_returns_hash_bound_review_for_unresolved_required_target() -> None:
    from open_mapping import BuildStatus, Compiler
    from tests.support.streamlined import source_schema, target_schema

    target = target_schema().model_copy(
        update={
            "fields": tuple(
                field.model_copy(update={"description": None}) for field in target_schema().fields
            )
        }
    )
    result = Compiler().build(source=source_schema(), target=target, mapping_id="customer")

    assert result.status is BuildStatus.NEEDS_REVIEW
    assert result.review_document is not None
    assert result.review_document.suggestion_report_sha256
    assert result.review_document.decisions[0].action.value == "undecided"


def test_compiler_records_the_supplied_review_document_hash() -> None:
    from open_mapping import Compiler
    from open_mapping.model.reviews import ReviewAction
    from open_mapping.serialization.canonical_json import canonical_json_bytes
    from tests.support.streamlined import source_schema, target_schema

    compiler = Compiler()
    target = target_schema().model_copy(
        update={
            "fields": tuple(
                field.model_copy(update={"description": None}) for field in target_schema().fields
            )
        }
    )
    first = compiler.build(source=source_schema(), target=target, mapping_id="customer")
    assert first.review_document is not None
    review = first.review_document.model_copy(
        update={
            "decisions": tuple(
                decision.model_copy(
                    update={
                        "action": ReviewAction.ACCEPT_SELECTED,
                        "reason": "Reviewed against the source contract.",
                    }
                )
                for decision in first.review_document.decisions
            )
        }
    )
    result = compiler.build(
        source=source_schema(), target=target, mapping_id="customer", review=review
    )

    assert (
        result.require_bundle().provenance.review_document_sha256
        == hashlib.sha256(canonical_json_bytes(review.model_dump(mode="json"))).hexdigest()
    )


def test_compiler_uses_shared_model_shorthand_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from open_mapping import Compiler, OpenMappingError
    from tests.support.streamlined import source_schema, target_schema

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(OpenMappingError, match="OPENAI_API_KEY"):
        Compiler(model="openai:gpt-5-mini", require_model=True).build(
            source=source_schema(), target=target_schema(), mapping_id="customer"
        )


def test_compiler_reports_optional_unmapped_targets_as_warnings() -> None:
    from open_mapping import BuildStatus, Compiler
    from open_mapping.model.schema import JsonType, SchemaField
    from tests.support.streamlined import source_schema, target_schema

    target = target_schema()
    target = target.model_copy(
        update={
            "fields": (
                *target.fields,
                SchemaField(
                    pointer="/nickname",
                    types=frozenset({JsonType.STRING}),
                    required=False,
                    source_location="target.schema.json#/properties/nickname",
                ),
            )
        }
    )
    result = Compiler().build(source=source_schema(), target=target, mapping_id="customer")

    assert result.status is BuildStatus.READY
    assert any(
        issue.severity.value == "warning" and issue.target_path == "/nickname"
        for issue in result.issues
    )


def test_compiler_rejects_invalid_samples_before_suggestion_or_model_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from open_mapping import Compiler, OpenMappingError
    from open_mapping.verification.dynamic import VerificationSample
    from tests.support.streamlined import source_schema, target_schema

    def forbidden_suggest(*args: object, **kwargs: object) -> object:
        raise AssertionError("suggestion work must not start for an invalid sample")

    monkeypatch.setattr(Compiler, "suggest", forbidden_suggest)
    with pytest.raises(OpenMappingError, match="SOURCE_SCHEMA_VALIDATION"):
        Compiler().build(
            source=source_schema(),
            target=target_schema(),
            samples=(VerificationSample(id="bad", input={"name": 3}),),
        )


def test_compiler_builds_and_sample_verifies_from_json_data() -> None:
    from open_mapping import BuildStatus, Compiler, Mapper
    from open_mapping.model.issues import IssueCode
    from tests.support.streamlined import target_schema

    result = Compiler().build(
        source=[{"name": "Ada"}, {"name": "Grace"}],
        target=target_schema(),
        source_format="json-data",
        mapping_id="customer",
        require_samples=True,
    )

    assert result.status is BuildStatus.READY
    bundle = result.require_bundle()
    assert bundle.verification.level.value == "samples"
    assert bundle.verification.sample_count == 2
    assert Mapper.from_bundle(bundle).transform({"name": "Katherine"}) == {"name": "Katherine"}
    assert any(issue.code is IssueCode.SOURCE_SCHEMA_INFERRED for issue in result.issues)
