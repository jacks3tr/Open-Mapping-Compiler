"""Adversarial response, orchestration, and reconciliation tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import pytest
from pydantic import ValidationError

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.matching.proposals import (
    apply_model_mapping_responses,
    build_deterministic_suggestions,
)
from open_mapping.model.hints import ConstantHint, MappingHints
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ModelProviderConfig, ProviderKind, ResolvedModel
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelTargetProposal,
    ModelTargetRequest,
    mapping_context_sha256,
    validate_model_mapping_response,
)
from open_mapping.model.providers import ModelRunDisclosure, ModelUsage
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    MatchCandidate,
    SuggestionDisposition,
    TargetCandidateSet,
)
from open_mapping.providers.config import resolve_model
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.protocol import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResult,
    TransportFactory,
)
from open_mapping.providers.transports.base import (
    MAX_RESPONSE_BODY_BYTES,
    call_with_transient_retries,
    normalized_model_payload,
    read_bounded_response_body,
)
from open_mapping.reports.json_report import render_suggestions_json
from open_mapping.reports.markdown_report import render_suggestions_markdown
from open_mapping.reports.text_report import render_suggestions_text
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _package(
    batch_id: str = "batch-a",
    *,
    targets: tuple[str, ...] = ("/target",),
) -> MappingContextPackage:
    return MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id=batch_id,
        context_mode="targeted",
        source_schema_id="source",
        source_schema_version="1",
        target_schema_id="target",
        target_schema_version="1",
        source_fields=(ModelFieldSummary(pointer="/source", types=("string",), required=True),),
        target_requests=tuple(
            ModelTargetRequest(
                target=ModelFieldSummary(pointer=target, types=("string",), required=True),
                candidates=(
                    ModelCandidateSummary(
                        source_path="/source",
                        raw_score=0.9,
                        evidence=("same semantic name",),
                    ),
                ),
            )
            for target in targets
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=("get", "literal", "divide", "concat"),
        allowed_source_paths=("/source",),
        raw_samples=None,
    )


def _proposal(
    target: str = "/target",
    *,
    expression: object | None = None,
    paths: tuple[str, ...] = ("/source",),
) -> ModelTargetProposal:
    return ModelTargetProposal.model_validate(
        {
            "target_path": target,
            "action": "propose",
            "selected_source_paths": paths,
            "expression": expression or {"op": "get", "path": "/source"},
            "reason": "The fields have the same meaning.",
            "evidence": ["names and types agree"],
        }
    )


def _response(
    package: MappingContextPackage,
    proposals: Sequence[ModelTargetProposal] | None = None,
) -> ModelMappingResponse:
    selected = (
        tuple(_proposal(request.target.pointer) for request in package.target_requests)
        if proposals is None
        else tuple(proposals)
    )
    return ModelMappingResponse(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        context_sha256=mapping_context_sha256(package),
        batch_id=package.batch_id,
        proposals=selected,
    )


def _resolved_model() -> ResolvedModel:
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {
                "local": {
                    "kind": "openai-compatible",
                    "base_url": "http://127.0.0.1:8080/v1",
                }
            },
            "models": {"mapper": {"provider": "local", "model_id": "fake"}},
        }
    )
    return resolve_model(config, "mapper")


def _result(payload: JsonValue) -> ModelTransportResult:
    return ModelTransportResult(
        payload=payload,
        provider_request_id=None,
        usage=ModelUsage(input_tokens=1, output_tokens=1),
        latency_ms=1,
        response_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )


@dataclass
class _ScriptedTransport:
    script: list[ModelTransportResult | Exception]
    requests: list[ModelTransportRequest] = field(default_factory=list)

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _invoke(
    packages: Sequence[MappingContextPackage],
    transport: _ScriptedTransport,
) -> tuple[tuple[ModelMappingResponse, ...], ModelRunDisclosure, tuple[object, ...]]:
    resolved = _resolved_model()

    def factory(selected: ResolvedModel) -> ModelTransport:
        assert selected == resolved
        return transport

    registry: Mapping[ProviderKind, TransportFactory] = {ProviderKind.OPENAI_COMPATIBLE: factory}
    responses, disclosure, issues = invoke_model_mapping(
        packages=packages,
        resolved_model=resolved,
        config_sha256="c" * 64,
        registry=registry,
    )
    return responses, disclosure, cast(tuple[object, ...], issues)


@pytest.mark.adversarial
@pytest.mark.parametrize("mutation", ("omitted", "duplicated", "added"))
def test_target_proposals_must_cover_every_requested_target_exactly_once(mutation: str) -> None:
    package = _package(targets=("/first", "/second"))
    valid = _response(package)
    if mutation == "omitted":
        proposals = valid.proposals[:-1]
    elif mutation == "duplicated":
        proposals = (valid.proposals[0], valid.proposals[0])
    else:
        proposals = (*valid.proposals, _proposal("/added"))

    issues = validate_model_mapping_response(
        valid.model_copy(update={"proposals": proposals}),
        package=package,
    )

    assert issues
    assert any(
        phrase in issue.message
        for issue in issues
        for phrase in ("missing", "duplicate", "unknown")
    )


@pytest.mark.adversarial
@pytest.mark.parametrize(
    ("field_name", "value", "expected"),
    (
        ("batch_id", "batch-other", "batch_id"),
        ("context_sha256", "0" * 64, "context_sha256"),
    ),
)
def test_response_batch_and_context_hash_must_match_request(
    field_name: str,
    value: str,
    expected: str,
) -> None:
    package = _package()
    issues = validate_model_mapping_response(
        _response(package).model_copy(update={field_name: value}),
        package=package,
    )
    assert any(expected in issue.message for issue in issues)


@pytest.mark.adversarial
def test_unknown_sources_targets_and_expression_operations_are_rejected() -> None:
    package = _package()
    unauthorized = _response(
        package,
        (
            _proposal(
                expression={"op": "get", "path": "/outside"},
                paths=("/outside",),
            ),
        ),
    )
    messages = {
        issue.message for issue in validate_model_mapping_response(unauthorized, package=package)
    }
    assert messages == {
        "expression reads a source path that is not allowed",
        "selected source path is not allowed",
    }

    unknown_target = _response(package, (_proposal("/outside"),))
    assert any(
        issue.message == "unknown target proposal"
        for issue in validate_model_mapping_response(unknown_target, package=package)
    )

    payload = _response(package).model_dump(mode="json")
    cast(dict[str, object], cast(list[object], payload["proposals"])[0])["expression"] = {
        "op": "execute",
        "code": "open('secret')",
    }
    with pytest.raises(ValidationError):
        ModelMappingResponse.model_validate(payload)


@pytest.mark.adversarial
def test_code_like_strings_remain_inert_literals() -> None:
    package = _package()
    code = "__import__('os').system('not-executed')"
    response = _response(
        package,
        (_proposal(expression={"op": "literal", "value": code}, paths=()),),
    )

    assert validate_model_mapping_response(response, package=package) == ()
    assert response.proposals[0].expression is not None
    assert response.proposals[0].expression.model_dump(mode="json") == {
        "op": "literal",
        "value": code,
    }


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "authority_field",
    ("confidence", "disposition", "review", "verified", "verification_state"),
)
def test_model_cannot_set_confidence_disposition_review_or_verification(
    authority_field: str,
) -> None:
    payload = _response(_package()).model_dump(mode="json")
    cast(dict[str, object], cast(list[object], payload["proposals"])[0])[authority_field] = (
        "approved"
    )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelMappingResponse.model_validate(payload)


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["source"],
            "properties": {"source": {"type": "string"}},
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["target"],
            "properties": {"target": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


@pytest.mark.adversarial
def test_static_invalid_complex_expression_is_rejected_after_response_validation() -> None:
    source, target = _schemas()
    package = _package()
    candidate_sets = (
        TargetCandidateSet(
            target_path="/target",
            candidates=(
                MatchCandidate(source_path="/source", target_path="/target", raw_score=0.9),
            ),
        ),
    )
    baseline = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=candidate_sets,
        hints=None,
    )
    invalid = _response(
        package,
        (
            _proposal(
                expression={
                    "op": "divide",
                    "left": {"op": "literal", "value": 1},
                    "right": {"op": "literal", "value": 0},
                },
                paths=(),
            ),
        ),
    )
    assert validate_model_mapping_response(invalid, package=package) == ()

    disclosure = _invoke(
        (package,), _ScriptedTransport([_result(cast(JsonValue, invalid.model_dump(mode="json")))])
    )[1]
    result = apply_model_mapping_responses(
        baseline,
        source_schema=source,
        target_schema=target,
        packages=(package,),
        responses=(invalid,),
        disclosure=disclosure,
    )

    assert result.suggestions == baseline.suggestions
    assert any("failed static verification" in issue.message for issue in result.issues)
    text_report = render_suggestions_text(result)
    markdown_report = render_suggestions_markdown(result)
    assert "Model alias: mapper" in text_report
    assert "Model issues" in text_report
    assert "Model alias: `mapper`" in markdown_report
    assert "## Model Issues" in markdown_report
    assert render_suggestions_text(result.model_copy(deep=True)) == text_report
    assert render_suggestions_markdown(result.model_copy(deep=True)) == markdown_report


@pytest.mark.adversarial
def test_invalid_batch_metadata_warns_without_discarding_a_valid_response() -> None:
    source, target = _schemas()
    baseline = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(),
        hints=None,
    )
    package = _package("batch-a")
    second_package = _package("batch-b")
    response = _response(package)
    unknown = response.model_copy(update={"batch_id": "batch-unknown"})
    invalid_coverage = _response(second_package).model_copy(update={"proposals": ()})
    disclosure = _invoke(
        (package,), _ScriptedTransport([_result(cast(JsonValue, response.model_dump(mode="json")))])
    )[1]

    result = apply_model_mapping_responses(
        baseline,
        source_schema=source,
        target_schema=target,
        packages=(package, package, second_package),
        responses=(response, response, unknown, invalid_coverage),
        disclosure=disclosure,
    )

    assert len(result.suggestions) == 1
    assert result.suggestions[0].target_path == "/target"
    assert result.suggestions[0].disposition is SuggestionDisposition.REVIEW_REQUIRED
    messages = {issue.message for issue in result.issues}
    assert "duplicate model package 'batch-a'" in messages
    assert "duplicate model response 'batch-a'" in messages
    assert "model response has unknown batch 'batch-unknown'" in messages
    assert "model response 'batch-b' failed response coverage validation" in messages


@pytest.mark.adversarial
def test_duplicate_targets_across_valid_batches_are_not_applied() -> None:
    source, target = _schemas()
    baseline = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(),
        hints=None,
    )
    first_package = _package("batch-a")
    second_package = _package("batch-b")
    first_response = _response(first_package)
    second_response = _response(second_package)
    disclosure = _invoke(
        (first_package,),
        _ScriptedTransport([_result(cast(JsonValue, first_response.model_dump(mode="json")))]),
    )[1]

    result = apply_model_mapping_responses(
        baseline,
        source_schema=source,
        target_schema=target,
        packages=(first_package, second_package),
        responses=(first_response, second_response),
        disclosure=disclosure,
    )

    assert result.suggestions == baseline.suggestions
    assert any(
        issue.message == "model responses contain duplicate target proposals across batches"
        for issue in result.issues
    )


@pytest.mark.adversarial
def test_explicit_manual_hint_remains_authoritative_over_model_proposal() -> None:
    source, target = _schemas()
    hints = MappingHints(
        hints_version="0.1",
        id="manual-authority",
        constants=(ConstantHint(target="/target", value="manual", reason="Business-owned value."),),
    )
    baseline = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(),
        hints=hints,
    )
    package = _package()
    response = _response(package)
    disclosure = _invoke(
        (package,), _ScriptedTransport([_result(cast(JsonValue, response.model_dump(mode="json")))])
    )[1]

    result = apply_model_mapping_responses(
        baseline,
        source_schema=source,
        target_schema=target,
        packages=(package,),
        responses=(response,),
        disclosure=disclosure,
    )

    assert result.suggestions == baseline.suggestions
    assert result.suggestions[0].disposition is SuggestionDisposition.MANUAL


@pytest.mark.adversarial
def test_invalid_structured_output_followed_by_invalid_repair_stops_after_one_repair() -> None:
    package = _package()
    first = _response(package).model_dump(mode="json")
    cast(dict[str, object], cast(list[object], first["proposals"])[0]).pop("evidence")
    second = _response(package).model_dump(mode="json")
    cast(dict[str, object], cast(list[object], second["proposals"])[0]).pop("reason")
    transport = _ScriptedTransport(
        [_result(cast(JsonValue, first)), _result(cast(JsonValue, second))]
    )

    responses, disclosure, issues = _invoke((package,), transport)

    assert responses == ()
    assert len(issues) == 1
    assert len(transport.requests) == 2
    assert disclosure.batch_runs[0].attempts == 2
    assert disclosure.batch_runs[0].format_repairs == 1


@pytest.mark.adversarial
def test_partial_batch_failure_preserves_other_validated_batches() -> None:
    first = _package("batch-a")
    second = _package("batch-b")
    second_payload = cast(JsonValue, _response(second).model_dump(mode="json"))
    transport = _ScriptedTransport([TimeoutError("synthetic timeout"), _result(second_payload)])

    responses, disclosure, issues = _invoke((second, first), transport)

    assert responses == (_response(second),)
    assert len(issues) == 1
    assert [run.batch_id for run in disclosure.batch_runs] == ["batch-a", "batch-b"]
    assert disclosure.batch_runs[0].response is None
    assert disclosure.batch_runs[1].response == _response(second)


@pytest.mark.adversarial
def test_timeout_retry_exhaustion_and_oversized_response_are_bounded() -> None:
    attempts = 0

    def timeout() -> None:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("synthetic timeout")

    with pytest.raises(TimeoutError):
        call_with_transient_retries(
            timeout,
            max_retries=99,
            is_transient=lambda error: isinstance(error, TimeoutError),
        )
    assert attempts == 3

    with pytest.raises(OpenMappingError, match="exceeds 4 MiB"):
        read_bounded_response_body((b"x" * MAX_RESPONSE_BODY_BYTES, b"x"))


@pytest.mark.adversarial
def test_special_json_keys_are_preserved_without_object_semantics() -> None:
    payload = '{"__proto__":{"polluted":true},"constructor":"value","toString":"value"}'
    assert normalized_model_payload(payload, component="providers.fake") == {
        "__proto__": {"polluted": True},
        "constructor": "value",
        "toString": "value",
    }


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "payload",
    (
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        '{"value":1,"value":2}',
        '{"value":"\\ud800"}',
    ),
)
def test_nonfinite_duplicate_and_invalid_unicode_json_are_rejected(payload: str) -> None:
    with pytest.raises(OpenMappingError):
        normalized_model_payload(payload, component="providers.fake")


@pytest.mark.adversarial
def test_response_and_report_serialization_are_byte_deterministic() -> None:
    package = _package()
    response = _response(package)
    first_response = canonical_json_bytes(cast(JsonValue, response.model_dump(mode="json")))
    second_response = canonical_json_bytes(
        cast(JsonValue, response.model_copy(deep=True).model_dump(mode="json"))
    )
    assert first_response == second_response

    source, target = _schemas()
    report = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(),
        hints=None,
    )
    first_report = render_suggestions_json(report)
    second_report = render_suggestions_json(report.model_copy(deep=True))
    assert first_report == second_report
    assert json.loads(first_report) == json.loads(second_report)
