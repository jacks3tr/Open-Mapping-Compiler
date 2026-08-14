"""Provider-neutral model mapping protocol tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from open_mapping.model.model_config import ContextMode
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelProposalAction,
    ModelTargetProposal,
    ModelTargetRequest,
    mapping_context_sha256,
    validate_model_mapping_response,
)


def _field(
    pointer: str,
    *,
    types: tuple[str, ...] = ("string",),
    constraints: dict[str, Any] | None = None,
) -> ModelFieldSummary:
    return ModelFieldSummary(
        pointer=pointer,
        types=types,
        required=True,
        title=None,
        description=None,
        enum_values=(),
        item_types=(),
        constraints={} if constraints is None else constraints,
    )


def _candidate(source_path: str, raw_score: float) -> ModelCandidateSummary:
    return ModelCandidateSummary(
        source_path=source_path,
        raw_score=raw_score,
        evidence=("schema names are similar",),
    )


def _package(*, distance_constraints: dict[str, Any] | None = None) -> MappingContextPackage:
    return MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id="batch-001",
        context_mode=ContextMode.TARGETED,
        source_schema_id="source",
        source_schema_version="1",
        target_schema_id="target",
        target_schema_version="1",
        source_fields=(
            _field("/first_name"),
            _field("/last_name"),
            _field("/status"),
            _field("/timestamp"),
            _field(
                "/distance",
                types=("number",),
                constraints={"minimum": 0, "maximum": 100000}
                if distance_constraints is None
                else distance_constraints,
            ),
            _field("/unit"),
        ),
        target_requests=(
            ModelTargetRequest(
                target=_field("/direct"),
                candidates=(_candidate("/first_name", 0.98),),
            ),
            ModelTargetRequest(
                target=_field("/lookup"),
                candidates=(_candidate("/status", 0.91),),
            ),
            ModelTargetRequest(target=_field("/constant"), candidates=()),
            ModelTargetRequest(
                target=_field("/date"),
                candidates=(_candidate("/timestamp", 0.9),),
            ),
            ModelTargetRequest(
                target=_field("/distance_m", types=("integer",)),
                candidates=(
                    _candidate("/distance", 0.96),
                    _candidate("/unit", 0.9),
                ),
            ),
            ModelTargetRequest(
                target=_field("/full_name"),
                candidates=(
                    _candidate("/first_name", 0.89),
                    _candidate("/last_name", 0.89),
                ),
            ),
            ModelTargetRequest(target=_field("/unmapped"), candidates=()),
        ),
        sample_profiles=(),
        business_instructions=("Use metric distance units.",),
        expression_operations=(
            "get",
            "literal",
            "lookup",
            "parse_date",
            "format_date",
            "multiply",
            "cast",
            "concat",
        ),
        allowed_source_paths=(
            "/first_name",
            "/last_name",
            "/status",
            "/timestamp",
            "/distance",
            "/unit",
        ),
        raw_samples=None,
    )


def _abstain(target_path: str) -> ModelTargetProposal:
    return ModelTargetProposal(
        target_path=target_path,
        action=ModelProposalAction.ABSTAIN,
        selected_source_paths=(),
        expression=None,
        reason="The available context is insufficient.",
        evidence=(),
    )


def _proposal(
    target_path: str,
    *,
    expression: dict[str, Any] | None,
    selected_source_paths: tuple[str, ...] = (),
    reason: str = "The expression follows the requested field semantics.",
    evidence: tuple[str, ...] = ("field names and types agree",),
) -> ModelTargetProposal:
    return ModelTargetProposal(
        target_path=target_path,
        action=ModelProposalAction.PROPOSE,
        selected_source_paths=selected_source_paths,
        expression=expression,
        reason=reason,
        evidence=evidence,
    )


def _response(
    package: MappingContextPackage,
    replacements: dict[str, ModelTargetProposal] | None = None,
) -> ModelMappingResponse:
    replacement_by_target = {} if replacements is None else replacements
    return ModelMappingResponse(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        context_sha256=mapping_context_sha256(package),
        batch_id=package.batch_id,
        proposals=tuple(
            replacement_by_target.get(request.target.pointer, _abstain(request.target.pointer))
            for request in package.target_requests
        ),
    )


@pytest.mark.parametrize(
    ("target_path", "selected_source_paths", "expression"),
    (
        (
            "/direct",
            ("/first_name",),
            {"op": "get", "path": "/first_name"},
        ),
        (
            "/lookup",
            ("/status",),
            {
                "op": "lookup",
                "key": {"op": "get", "path": "/status"},
                "values": {"A": "active", "I": "inactive"},
            },
        ),
        (
            "/constant",
            (),
            {"op": "literal", "value": "imported"},
        ),
        (
            "/date",
            ("/timestamp",),
            {
                "op": "format_date",
                "value": {
                    "op": "parse_date",
                    "value": {"op": "get", "path": "/timestamp"},
                },
                "pattern": "YYYY-MM-DD",
            },
        ),
        (
            "/distance_m",
            ("/distance", "/unit"),
            {
                "op": "cast",
                "target_type": "integer",
                "value": {
                    "op": "multiply",
                    "left": {"op": "get", "path": "/distance"},
                    "right": {
                        "op": "lookup",
                        "key": {"op": "get", "path": "/unit"},
                        "values": {"km": 1000, "m": 1},
                    },
                },
            },
        ),
        (
            "/full_name",
            ("/first_name", "/last_name"),
            {
                "op": "concat",
                "operands": [
                    {"op": "get", "path": "/first_name"},
                    {"op": "get", "path": "/last_name"},
                ],
                "separator": " ",
            },
        ),
    ),
    ids=("direct", "lookup", "constant", "date", "unit-conversion", "multi-source"),
)
def test_validate_accepts_typed_mapping_proposals(
    target_path: str,
    selected_source_paths: tuple[str, ...],
    expression: dict[str, Any],
) -> None:
    package = _package()
    response = _response(
        package,
        {
            target_path: _proposal(
                target_path, expression=expression, selected_source_paths=selected_source_paths
            )
        },
    )

    assert validate_model_mapping_response(response, package=package) == ()


def test_validate_accepts_an_exactly_covered_abstaining_response() -> None:
    package = _package()

    assert validate_model_mapping_response(_response(package), package=package) == ()


def test_propose_requires_an_expression() -> None:
    with pytest.raises(ValidationError, match="requires an expression"):
        _proposal("/direct", expression=None, selected_source_paths=("/first_name",))


def test_nonconstant_propose_requires_a_selected_source_path() -> None:
    with pytest.raises(ValidationError, match="requires at least one selected source path"):
        _proposal("/direct", expression={"op": "get", "path": "/first_name"})


def test_pure_constant_propose_cannot_claim_a_source_path() -> None:
    with pytest.raises(ValidationError, match="pure constant"):
        _proposal(
            "/constant",
            expression={"op": "literal", "value": "imported"},
            selected_source_paths=("/first_name",),
        )


def test_recursive_pure_constant_expression_needs_no_selected_source_path() -> None:
    package = _package()
    response = _response(
        package,
        {
            "/constant": _proposal(
                "/constant",
                expression={
                    "op": "concat",
                    "operands": [
                        {"op": "literal", "value": "import"},
                        {"op": "literal", "value": "ed"},
                    ],
                },
            )
        },
    )

    assert validate_model_mapping_response(response, package=package) == ()


def test_recursive_pure_constant_cannot_claim_an_unrelated_source_path() -> None:
    with pytest.raises(ValidationError, match="pure constant"):
        _proposal(
            "/constant",
            expression={
                "op": "concat",
                "operands": [
                    {"op": "literal", "value": "import"},
                    {"op": "literal", "value": "ed"},
                ],
            },
            selected_source_paths=("/first_name",),
        )


def test_abstention_cannot_include_an_expression_or_selected_source_path() -> None:
    with pytest.raises(ValidationError, match="abstain"):
        ModelTargetProposal(
            target_path="/direct",
            action=ModelProposalAction.ABSTAIN,
            selected_source_paths=("/first_name",),
            expression={"op": "get", "path": "/first_name"},
            reason="unclear",
            evidence=(),
        )


@pytest.mark.parametrize(
    ("replacement", "expected_message"),
    (
        (
            _proposal(
                "/direct",
                expression={"op": "get", "path": "/first_name"},
                selected_source_paths=("/outside",),
            ),
            "selected source path is not allowed",
        ),
        (
            _proposal(
                "/direct",
                expression={"op": "get", "path": "/outside"},
                selected_source_paths=("/first_name",),
            ),
            "expression reads a source path that is not allowed",
        ),
    ),
    ids=("selected-source", "get-expression"),
)
def test_validate_rejects_source_paths_outside_the_context_allowlist(
    replacement: ModelTargetProposal, expected_message: str
) -> None:
    package = _package()
    response = _response(package, {"/direct": replacement})

    issues = validate_model_mapping_response(response, package=package)

    assert any(issue.message == expected_message for issue in issues)
    assert all(issue.code.value == "PROVIDER_RESPONSE_INVALID" for issue in issues)


@pytest.mark.parametrize("document", ("current", "output"))
def test_validate_rejects_gets_from_noninput_documents(document: str) -> None:
    package = _package()
    response = _response(
        package,
        {
            "/direct": _proposal(
                "/direct",
                expression={"op": "get", "path": "/first_name", "document": document},
                selected_source_paths=("/first_name",),
            )
        },
    )

    issues = validate_model_mapping_response(response, package=package)

    assert any(issue.message == "expression get must use the input document" for issue in issues)


def test_validate_rejects_an_operation_omitted_from_the_context_package() -> None:
    package = _package().model_copy(update={"expression_operations": ("get", "literal")})
    response = _response(
        package,
        {
            "/lookup": _proposal(
                "/lookup",
                expression={
                    "op": "lookup",
                    "key": {"op": "get", "path": "/status"},
                    "values": {"A": "active"},
                },
                selected_source_paths=("/status",),
            )
        },
    )

    issues = validate_model_mapping_response(response, package=package)

    assert any(
        issue.message == "expression operation is not allowed by the context" for issue in issues
    )


def test_validate_rejects_a_selected_source_path_not_read_by_the_expression() -> None:
    package = _package()
    response = _response(
        package,
        {
            "/direct": _proposal(
                "/direct",
                expression={"op": "get", "path": "/first_name"},
                selected_source_paths=("/first_name", "/last_name"),
            )
        },
    )

    issues = validate_model_mapping_response(response, package=package)

    assert any(
        issue.message == "selected source path is not read by the expression" for issue in issues
    )


def test_response_rejects_unknown_expression_operations() -> None:
    package = _package()
    payload = _response(package).model_dump(mode="json")
    payload["proposals"][0] = {
        "target_path": "/direct",
        "action": "propose",
        "selected_source_paths": ["/first_name"],
        "expression": {"op": "shell", "command": "whoami"},
        "reason": "run this",
        "evidence": [],
    }

    with pytest.raises(ValidationError):
        ModelMappingResponse.model_validate(payload)


def test_response_rejects_executable_code_fields_inside_expressions() -> None:
    package = _package()
    payload = _response(package).model_dump(mode="json")
    payload["proposals"][0] = {
        "target_path": "/direct",
        "action": "propose",
        "selected_source_paths": [],
        "expression": {
            "op": "literal",
            "value": "imported",
            "code": "__import__('os').system('whoami')",
        },
        "reason": "run this",
        "evidence": [],
    }

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ModelMappingResponse.model_validate(payload)


def test_code_like_literal_remains_typed_inert_data() -> None:
    package = _package()
    code_like_literal = "__import__('os').system('whoami')"
    response = _response(
        package,
        {
            "/constant": _proposal(
                "/constant",
                expression={"op": "literal", "value": code_like_literal},
            )
        },
    )

    assert validate_model_mapping_response(response, package=package) == ()
    assert response.proposals[2].expression is not None
    assert response.proposals[2].expression.model_dump(mode="json") == {
        "op": "literal",
        "value": code_like_literal,
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("confidence", 0.99),
        ("score", 0.99),
        ("disposition", "suggested"),
        ("approval", "approved"),
        ("review", "accepted"),
        ("verification", "passed"),
        ("verified", True),
        ("code", "return mapped_value"),
    ),
)
def test_response_rejects_model_authority_and_unknown_fields(
    field_name: str, value: object
) -> None:
    package = _package()
    payload = _response(package).model_dump(mode="json")
    payload["proposals"][0][field_name] = value

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ModelMappingResponse.model_validate(payload)


def test_response_rejects_unknown_top_level_fields() -> None:
    package = _package()
    payload = _response(package).model_dump(mode="json")
    payload["confidence"] = 1.0

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ModelMappingResponse.model_validate(payload)


def test_response_rejects_reason_longer_than_the_protocol_bound() -> None:
    with pytest.raises(ValidationError, match="1000"):
        _proposal(
            "/direct",
            expression={"op": "get", "path": "/first_name"},
            selected_source_paths=("/first_name",),
            reason="r" * 1001,
        )


@pytest.mark.parametrize(
    "evidence",
    (
        tuple("e" for _ in range(9)),
        ("e" * 301,),
    ),
    ids=("too-many", "entry-too-long"),
)
def test_response_rejects_evidence_outside_protocol_bounds(evidence: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _proposal(
            "/direct",
            expression={"op": "get", "path": "/first_name"},
            selected_source_paths=("/first_name",),
            evidence=evidence,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected_message"),
    (
        ("batch_id", "other-batch", "response batch_id does not match the request"),
        (
            "prompt_version",
            "mapping-agent-v2",
            "response prompt_version does not match the request",
        ),
        (
            "context_sha256",
            "0" * 64,
            "response context_sha256 does not match the request",
        ),
    ),
)
def test_validate_rejects_response_metadata_that_does_not_match_the_request(
    field_name: str, replacement: str, expected_message: str
) -> None:
    package = _package()
    response = _response(package).model_copy(update={field_name: replacement})

    issues = validate_model_mapping_response(response, package=package)

    assert any(issue.message == expected_message for issue in issues)


@pytest.mark.parametrize(
    ("proposals", "expected_message"),
    (
        (lambda response: response.proposals[:-1], "missing requested target proposal"),
        (
            lambda response: (
                response.proposals[0],
                response.proposals[0],
                *response.proposals[2:],
            ),
            "duplicate target proposal",
        ),
        (
            lambda response: response.proposals + (_abstain("/extra"),),
            "unknown target proposal",
        ),
        (
            lambda response: tuple(reversed(response.proposals)),
            "target proposals are not in request order",
        ),
    ),
    ids=("missing", "duplicate", "extra", "reordered"),
)
def test_validate_requires_exact_ordered_target_coverage(
    proposals: Any, expected_message: str
) -> None:
    package = _package()
    response = _response(package)
    malformed = response.model_copy(update={"proposals": proposals(response)})

    issues = validate_model_mapping_response(malformed, package=package)

    assert any(issue.message == expected_message for issue in issues)


def test_validate_rejects_an_unknown_target_path() -> None:
    package = _package()
    response = _response(package)
    malformed = response.model_copy(
        update={"proposals": (_abstain("/unknown-target"), *response.proposals[1:])}
    )

    issues = validate_model_mapping_response(malformed, package=package)

    assert any(issue.message == "unknown target proposal" for issue in issues)


def test_context_rejects_duplicate_requested_targets() -> None:
    package = _package()
    payload = package.model_dump()
    payload["target_requests"] = (package.target_requests[0], *package.target_requests)

    with pytest.raises(ValidationError, match="duplicate target request"):
        MappingContextPackage.model_validate(payload)


def test_mapping_context_hash_is_canonical_and_stable() -> None:
    package = _package()
    reordered_constraints = _package(distance_constraints={"maximum": 100000, "minimum": 0})

    assert (
        mapping_context_sha256(package)
        == "6adeaf6f445993dbe48508d6f2e562ca96b8c9461d70f1f06641c91a60fa7019"
    )
    assert mapping_context_sha256(package) == mapping_context_sha256(reordered_constraints)


def test_response_schema_enforces_propose_and_abstain_shapes() -> None:
    package = _package()
    validator = Draft202012Validator(
        json.loads(Path("schemas/model-mapping-response.schema.json").read_text(encoding="utf-8"))
    )
    abstain_payload = _response(package).model_dump(mode="json")
    abstain_payload["proposals"][0]["selected_source_paths"] = ["/first_name"]
    propose_payload = _response(
        package,
        {
            "/direct": _proposal(
                "/direct",
                expression={"op": "get", "path": "/first_name"},
                selected_source_paths=("/first_name",),
            )
        },
    ).model_dump(mode="json")
    propose_payload["proposals"][0]["expression"] = None

    assert list(validator.iter_errors(abstain_payload))
    assert list(validator.iter_errors(propose_payload))


def test_response_schema_requires_selected_paths_unless_a_propose_is_recursively_constant() -> None:
    package = _package()
    validator = Draft202012Validator(
        json.loads(Path("schemas/model-mapping-response.schema.json").read_text(encoding="utf-8"))
    )
    source_dependent_payload = _response(
        package,
        {
            "/direct": _proposal(
                "/direct",
                expression={"op": "get", "path": "/first_name"},
                selected_source_paths=("/first_name",),
            )
        },
    ).model_dump(mode="json")
    source_dependent_payload["proposals"][0]["selected_source_paths"] = []
    pure_constant_payload = _response(
        package,
        {
            "/constant": _proposal(
                "/constant",
                expression={
                    "op": "concat",
                    "operands": [
                        {"op": "literal", "value": "import"},
                        {"op": "literal", "value": "ed"},
                    ],
                },
            )
        },
    ).model_dump(mode="json")
    pure_constant_with_path_payload = json.loads(json.dumps(pure_constant_payload))
    pure_constant_with_path_payload["proposals"][2]["selected_source_paths"] = ["/first_name"]

    assert list(validator.iter_errors(source_dependent_payload))
    assert not list(validator.iter_errors(pure_constant_payload))
    assert list(validator.iter_errors(pure_constant_with_path_payload))


@pytest.mark.parametrize(
    ("filename", "model"),
    (
        ("model-mapping-context.schema.json", MappingContextPackage),
        ("model-mapping-response.schema.json", ModelMappingResponse),
    ),
)
def test_committed_model_protocol_schema_matches_the_pydantic_contract(
    filename: str, model: type[Any]
) -> None:
    committed = json.loads((Path("schemas") / filename).read_text(encoding="utf-8"))
    generated = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **TypeAdapter(model).json_schema(),
    }

    assert committed == generated
