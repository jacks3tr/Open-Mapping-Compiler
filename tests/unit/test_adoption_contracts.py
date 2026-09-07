"""Public adoption contracts: no network on resume and no temporary schema files."""

from __future__ import annotations

import json
from typing import cast

import pytest

from open_mapping import Compiler, Mapper, OpenMappingError, map_schemas
from open_mapping.model.json_types import JsonValue
from open_mapping.model.reviews import ReviewAction
from open_mapping.verification.dynamic import VerificationSample
from tests.support.streamlined import source_schema, target_schema


def test_required_model_without_selection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPEN_MAPPING_MODEL", raising=False)
    with pytest.raises(OpenMappingError, match="model"):
        Compiler(require_model=True).build(source=source_schema(), target=target_schema())


def test_compiler_uses_environment_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_MAPPING_MODEL", "openai:gpt-5-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(OpenMappingError, match="OPENAI_API_KEY"):
        Compiler().build(source=source_schema(), target=target_schema())


def test_offline_overrides_explicit_and_environment_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_MAPPING_MODEL", "invalid:model")
    assert (
        Compiler(model="invalid:model", offline=True)
        .build(source=source_schema(), target=target_schema())
        .ready
    )
    assert map_schemas(source_schema(), target_schema(), offline=True).suggestions
    with pytest.raises(OpenMappingError, match="offline"):
        Compiler(offline=True, require_model=True).build(
            source=source_schema(), target=target_schema()
        )


def test_in_memory_openapi_component_matches_file_adapter() -> None:
    raw = cast(JsonValue, json.loads(source_schema().canonical_source_json))
    document: JsonValue = {"openapi": "3.1.0", "components": {"schemas": {"Customer": raw}}}
    result = Compiler(offline=True).build(
        source=document,
        source_format="openapi",
        source_selector="component:Customer",
        target=target_schema(),
    )
    assert result.ready
    assert Mapper.from_bundle(result.require_bundle()).transform({"name": "Ada"}) == {"name": "Ada"}


def test_draft_roundtrip_resumes_without_suggestion_or_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from open_mapping import BuildDraft

    target = target_schema().model_copy(
        update={
            "fields": tuple(
                field.model_copy(update={"description": None}) for field in target_schema().fields
            )
        }
    )
    first = Compiler(offline=True).build(
        source=source_schema(),
        target=target,
        mapping_id="customer",
        samples=(VerificationSample(id="example", input={"name": "Ada"}),),
        require_samples=True,
    )
    assert first.needs_review and first.draft is not None and first.review_document is not None
    draft = BuildDraft.model_validate_json(first.draft.model_dump_json())
    review = first.review_document.model_copy(
        update={
            "decisions": tuple(
                decision.model_copy(
                    update={"action": ReviewAction.ACCEPT_SELECTED, "reason": "Contract checked."}
                )
                for decision in first.review_document.decisions
            )
        }
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("resume must not regenerate suggestions or resolve a model")

    monkeypatch.setattr(Compiler, "suggest", forbidden)
    monkeypatch.setattr(Compiler, "_resolve_model_selection", forbidden)
    result = Compiler().resume(draft, review=review)
    assert result.ready
    assert result.require_bundle().verification.sample_count == 1
    assert result.suggestion_report == first.suggestion_report
    assert (
        result.require_bundle().provenance.suggestion_report_sha256
        == review.suggestion_report_sha256
    )


def test_draft_tampering_is_rejected() -> None:
    from pydantic import ValidationError

    from open_mapping import BuildDraft

    result = Compiler(offline=True).build(source=source_schema(), target=target_schema())
    assert result.draft is not None
    raw = json.loads(result.draft.model_dump_json())
    raw["content"]["mapping_id"] = "changed"
    with pytest.raises(ValidationError, match="hash"):
        BuildDraft.model_validate(raw)


def test_build_with_draft_rejects_changed_contract() -> None:
    result = Compiler(offline=True).build(source=source_schema(), target=target_schema())
    assert result.draft is not None
    changed = target_schema().model_copy(update={"schema_id": "different"})
    with pytest.raises(OpenMappingError, match="changed"):
        Compiler(offline=True).build(source=source_schema(), target=changed, draft=result.draft)


def test_resuming_draft_cannot_silently_change_review_policy() -> None:
    result = Compiler(offline=True).build(source=source_schema(), target=target_schema())
    assert result.draft is not None
    with pytest.raises(OpenMappingError, match="policy"):
        Compiler().build(
            source=source_schema(),
            target=target_schema(),
            draft=result.draft,
            require_complete_review=True,
        )


def test_public_compiler_uses_the_supplied_transport_factory() -> None:
    from open_mapping.model.model_config import ProviderKind, ResolvedModel
    from open_mapping.providers.protocol import ModelTransport
    from tests.unit.providers.test_model_orchestrator import _resolved_model

    selected = _resolved_model()
    seen: list[ResolvedModel] = []

    def factory(model: ResolvedModel) -> ModelTransport:
        seen.append(model)
        raise RuntimeError("intentional host gateway failure")

    with pytest.raises(OpenMappingError):
        Compiler(
            model=selected,
            require_model=True,
            transport_registry={ProviderKind.OPENAI_COMPATIBLE: factory},
        ).build(source=source_schema(), target=target_schema())
    assert seen == [selected]


def test_batch_results_continue_after_invalid_record() -> None:
    mapper = Mapper.from_bundle(
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )
    results = tuple(mapper.iter_results([{"name": "Ada"}, {"name": 3}, {"name": "Grace"}]))
    assert [result.index for result in results] == [0, 1, 2]
    assert [result.success for result in results] == [True, False, True]
    assert results[1].issues and results[1].output is None
    assert results[2].output == {"name": "Grace"}
    assert mapper.validate_source({"name": "Ada"}) == ()
    assert mapper.validate_source({"name": 3})
