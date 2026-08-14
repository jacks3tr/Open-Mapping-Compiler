"""Provider-neutral mapping context and typed model response contract."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal, Self, cast

from pydantic import ConfigDict, Field, model_validator
from pydantic import JsonValue as PydanticJsonValue

from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.expressions import (
    ArrayExpression,
    BooleanExpression,
    CastExpression,
    CoalesceExpression,
    ConcatExpression,
    EqualsExpression,
    Expression,
    FormatDateExpression,
    GetExpression,
    IfExpression,
    LiteralExpression,
    LookupExpression,
    MapExpression,
    NotExpression,
    NumericExpression,
    ObjectExpression,
    ParseDateExpression,
    RoundExpression,
)
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonScalar, JsonValue, OpenMappingModel
from open_mapping.model.model_config import ContextMode
from open_mapping.serialization.canonical_json import canonical_json_bytes

_RESPONSE_COMPONENT = "model.model_protocol"
_RESPONSE_CORRECTION = "Return a typed response that exactly matches the mapping context."
BoundedEvidenceText = Annotated[str, Field(max_length=300)]


def _pure_constant_expression_json_schema(anchor: str) -> dict[str, PydanticJsonValue]:
    """Build a recursive JSON Schema for expression ASTs with no ``get`` node."""

    def reference() -> dict[str, object]:
        return {"$dynamicRef": f"#{anchor}"}

    def operation(
        op: str | list[str], properties: dict[str, object], required: list[str]
    ) -> dict[str, object]:
        operation_properties: dict[str, object] = {
            "op": {"const": op} if isinstance(op, str) else {"enum": op}
        }
        operation_properties.update(properties)
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": operation_properties,
            "required": ["op", *required],
        }

    return cast(
        dict[str, PydanticJsonValue],
        {
            "$dynamicAnchor": anchor,
            "oneOf": [
                operation("literal", {"value": {}}, ["value"]),
                operation(
                    "object",
                    {
                        "fields": {
                            "type": "object",
                            "additionalProperties": reference(),
                        }
                    },
                    ["fields"],
                ),
                operation(
                    "array",
                    {"items": {"type": "array", "items": reference()}},
                    ["items"],
                ),
                operation(
                    "map",
                    {"collection": reference(), "expression": reference()},
                    ["collection", "expression"],
                ),
                operation(
                    "coalesce",
                    {
                        "operands": {
                            "type": "array",
                            "minItems": 1,
                            "items": reference(),
                        }
                    },
                    ["operands"],
                ),
                operation(
                    "concat",
                    {
                        "operands": {"type": "array", "items": reference()},
                        "separator": {"type": "string"},
                    },
                    ["operands"],
                ),
                operation(
                    "cast",
                    {
                        "value": reference(),
                        "target_type": {
                            "enum": ["string", "integer", "number", "boolean"],
                            "type": "string",
                        },
                    },
                    ["value", "target_type"],
                ),
                operation(
                    "if",
                    {
                        "condition": reference(),
                        "then": reference(),
                        "otherwise": reference(),
                    },
                    ["condition", "then", "otherwise"],
                ),
                operation(
                    "equals",
                    {"left": reference(), "right": reference()},
                    ["left", "right"],
                ),
                operation("not", {"value": reference()}, ["value"]),
                operation(
                    ["and", "or"],
                    {
                        "operands": {
                            "type": "array",
                            "minItems": 2,
                            "items": reference(),
                        }
                    },
                    ["operands"],
                ),
                operation(
                    "lookup",
                    {
                        "key": reference(),
                        "values": {"type": "object", "additionalProperties": {}},
                        "default": {
                            "anyOf": [reference(), {"type": "null"}],
                        },
                    },
                    ["key", "values"],
                ),
                operation(
                    ["add", "subtract", "multiply", "divide"],
                    {"left": reference(), "right": reference()},
                    ["left", "right"],
                ),
                operation(
                    "round",
                    {
                        "value": reference(),
                        "digits": {"type": "integer", "minimum": 0, "maximum": 12},
                    },
                    ["value"],
                ),
                operation("parse_date", {"value": reference()}, ["value"]),
                operation(
                    "format_date",
                    {"value": reference(), "pattern": {"type": "string"}},
                    ["value", "pattern"],
                ),
            ],
        },
    )


_PURE_CONSTANT_EXPRESSION_JSON_SCHEMA = _pure_constant_expression_json_schema(
    "pureConstantExpression"
)
_PURE_CONSTANT_EXPRESSION_WITH_SELECTED_PATHS_JSON_SCHEMA = _pure_constant_expression_json_schema(
    "pureConstantExpressionWithSelectedPaths"
)
_PROPOSAL_ACTION_JSON_SCHEMA: dict[str, PydanticJsonValue] = {
    "allOf": [
        {
            "if": {
                "properties": {"action": {"const": "abstain"}},
                "required": ["action"],
            },
            "then": {
                "properties": {
                    "selected_source_paths": {"maxItems": 0},
                    "expression": {"type": "null"},
                },
                "required": ["selected_source_paths", "expression"],
            },
        },
        {
            "if": {
                "properties": {"action": {"const": "propose"}},
                "required": ["action"],
            },
            "then": {
                "oneOf": [
                    {
                        "properties": {
                            "selected_source_paths": {"minItems": 1},
                            "expression": {
                                "allOf": [
                                    {"not": {"type": "null"}},
                                    {
                                        "not": _PURE_CONSTANT_EXPRESSION_WITH_SELECTED_PATHS_JSON_SCHEMA
                                    },
                                ]
                            },
                        },
                        "required": ["selected_source_paths", "expression"],
                    },
                    {
                        "properties": {
                            "selected_source_paths": {"maxItems": 0},
                            "expression": _PURE_CONSTANT_EXPRESSION_JSON_SCHEMA,
                        },
                        "required": ["selected_source_paths", "expression"],
                    },
                ]
            },
        },
    ]
}


class ModelFieldSummary(OpenMappingModel):
    """Compact, provider-neutral summary of one schema field."""

    pointer: str
    types: tuple[str, ...]
    required: bool
    title: str | None = Field(default=None, exclude_if=lambda value: value is None)
    description: str | None = Field(default=None, exclude_if=lambda value: value is None)
    enum_values: tuple[JsonScalar, ...] = Field(default=(), exclude_if=lambda value: not value)
    item_types: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    constraints: dict[str, JsonValue] = Field(
        default_factory=dict,
        exclude_if=lambda value: not value,
    )


class ModelCandidateSummary(OpenMappingModel):
    """One deterministic source-field candidate for a target field."""

    source_path: str
    raw_score: float
    evidence: tuple[str, ...]


class ModelTargetRequest(OpenMappingModel):
    """The target field and bounded candidates for one model proposal."""

    target: ModelFieldSummary
    candidates: tuple[ModelCandidateSummary, ...]


class MappingContextPackage(OpenMappingModel):
    """The versioned request contract shared by all model providers."""

    protocol_version: Literal["0.1"]
    prompt_version: Literal["mapping-agent-v1"]
    batch_id: str
    context_mode: ContextMode
    source_schema_id: str
    source_schema_version: str
    target_schema_id: str
    target_schema_version: str
    source_fields: tuple[ModelFieldSummary, ...]
    target_requests: tuple[ModelTargetRequest, ...]
    sample_profiles: tuple[FieldProfile, ...]
    business_instructions: tuple[str, ...]
    expression_operations: tuple[str, ...]
    expression_operation_semantics: dict[str, str] = Field(default_factory=dict)
    allowed_source_paths: tuple[str, ...]
    raw_samples: tuple[JsonValue, ...] | None
    truncation_count: int = Field(default=0, ge=0)
    redaction_count: int = Field(default=0, ge=0)
    raw_samples_included: bool = False

    @model_validator(mode="after")
    def validate_unique_target_requests(self) -> Self:
        target_paths = tuple(request.target.pointer for request in self.target_requests)
        if len(target_paths) != len(set(target_paths)):
            raise ValueError("mapping context contains a duplicate target request")
        return self


class ModelProposalAction(StrEnum):
    """The only actions a model may return for a requested target."""

    PROPOSE = "propose"
    ABSTAIN = "abstain"


class ModelTargetProposal(OpenMappingModel):
    """A typed proposal or abstention for exactly one requested target."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra=_PROPOSAL_ACTION_JSON_SCHEMA,
    )

    target_path: str
    action: ModelProposalAction
    selected_source_paths: tuple[str, ...]
    expression: Expression | None
    reason: Annotated[str, Field(max_length=1000)]
    evidence: Annotated[tuple[BoundedEvidenceText, ...], Field(max_length=8)]

    @model_validator(mode="after")
    def validate_action_shape(self) -> Self:
        if self.action is ModelProposalAction.ABSTAIN:
            if self.selected_source_paths or self.expression is not None:
                raise ValueError(
                    "abstain action cannot include selected source paths or an expression"
                )
            return self
        if self.expression is None:
            raise ValueError("propose action requires an expression")
        if _is_pure_constant(self.expression):
            if self.selected_source_paths:
                raise ValueError(
                    "pure constant propose action cannot include selected source paths"
                )
        elif not self.selected_source_paths:
            raise ValueError(
                "nonconstant propose action requires at least one selected source path"
            )
        return self


class ModelMappingResponse(OpenMappingModel):
    """The response contract every model provider must return unchanged."""

    protocol_version: Literal["0.1"]
    prompt_version: Literal["mapping-agent-v1"]
    context_sha256: str
    batch_id: str
    proposals: tuple[ModelTargetProposal, ...]


def _canonical_context_payload(package: MappingContextPackage) -> JsonValue:
    """Return the package's public deterministic JSON representation."""
    return cast(JsonValue, package.model_dump(mode="json"))


def mapping_context_sha256(package: MappingContextPackage) -> str:
    """Return the SHA-256 digest of the package's canonical JSON representation."""
    return hashlib.sha256(canonical_json_bytes(_canonical_context_payload(package))).hexdigest()


def _analyze_expression(expression: Expression) -> tuple[set[str], set[str], set[str]]:
    """Return input paths, non-input documents, and operation names used by an expression."""
    input_paths: set[str] = set()
    non_input_documents: set[str] = set()
    operation_names: set[str] = set()
    stack: list[Expression] = [expression]
    while stack:
        node = stack.pop()
        operation_names.add(node.op)
        if isinstance(node, GetExpression):
            if node.document == "input":
                input_paths.add(node.path)
            else:
                non_input_documents.add(node.document)
        elif isinstance(node, LiteralExpression):
            continue
        elif isinstance(node, ObjectExpression):
            stack.extend(node.fields.values())
        elif isinstance(node, ArrayExpression):
            stack.extend(node.items)
        elif isinstance(node, MapExpression):
            stack.extend((node.collection, node.expression))
        elif isinstance(node, (CoalesceExpression, ConcatExpression, BooleanExpression)):
            stack.extend(node.operands)
        elif isinstance(node, CastExpression):
            stack.append(node.value)
        elif isinstance(node, IfExpression):
            stack.extend((node.condition, node.then, node.otherwise))
        elif isinstance(node, EqualsExpression):
            stack.extend((node.left, node.right))
        elif isinstance(node, NotExpression):
            stack.append(node.value)
        elif isinstance(node, LookupExpression):
            stack.append(node.key)
            if node.default is not None:
                stack.append(node.default)
        elif isinstance(node, NumericExpression):
            stack.extend((node.left, node.right))
        elif isinstance(node, RoundExpression):
            stack.append(node.value)
        elif isinstance(node, ParseDateExpression):
            stack.append(node.value)
        elif isinstance(node, FormatDateExpression):
            stack.append(node.value)
        else:
            raise TypeError(f"unsupported typed expression {type(node)!r}")
    return input_paths, non_input_documents, operation_names


def _is_pure_constant(expression: Expression) -> bool:
    input_paths, non_input_documents, _operation_names = _analyze_expression(expression)
    return not input_paths and not non_input_documents


def _invalid_response_issue(
    message: str,
    *,
    source_path: str | None = None,
    target_path: str | None = None,
) -> Issue:
    return Issue(
        code=IssueCode.PROVIDER_RESPONSE_INVALID,
        severity=Severity.ERROR,
        component=_RESPONSE_COMPONENT,
        message=message,
        correction=_RESPONSE_CORRECTION,
        source_path=source_path,
        target_path=target_path,
    )


def validate_model_mapping_response(
    response: ModelMappingResponse,
    *,
    package: MappingContextPackage,
) -> tuple[Issue, ...]:
    """Return deterministic issues for response data that exceeds its context authority."""
    issues: list[Issue] = []
    if response.protocol_version != package.protocol_version:
        issues.append(
            _invalid_response_issue("response protocol_version does not match the request")
        )
    if response.prompt_version != package.prompt_version:
        issues.append(_invalid_response_issue("response prompt_version does not match the request"))
    if response.batch_id != package.batch_id:
        issues.append(_invalid_response_issue("response batch_id does not match the request"))
    if response.context_sha256 != mapping_context_sha256(package):
        issues.append(_invalid_response_issue("response context_sha256 does not match the request"))

    expected_targets = tuple(request.target.pointer for request in package.target_requests)
    expected_target_set = set(expected_targets)
    actual_targets = tuple(proposal.target_path for proposal in response.proposals)
    target_counts = {target: actual_targets.count(target) for target in set(actual_targets)}
    for target_path in actual_targets:
        if target_path not in expected_target_set:
            issues.append(
                _invalid_response_issue("unknown target proposal", target_path=target_path)
            )
    for target_path in sorted(target_counts):
        if target_counts[target_path] > 1:
            issues.append(
                _invalid_response_issue("duplicate target proposal", target_path=target_path)
            )
    for target_path in expected_targets:
        if target_counts.get(target_path, 0) == 0:
            issues.append(
                _invalid_response_issue(
                    "missing requested target proposal", target_path=target_path
                )
            )
    coverage_is_exact = (
        len(actual_targets) == len(expected_targets)
        and set(actual_targets) == expected_target_set
        and all(count == 1 for count in target_counts.values())
    )
    if coverage_is_exact and actual_targets != expected_targets:
        issues.append(_invalid_response_issue("target proposals are not in request order"))

    allowed_source_paths = set(package.allowed_source_paths)
    for proposal in response.proposals:
        for source_path in proposal.selected_source_paths:
            if source_path not in allowed_source_paths:
                issues.append(
                    _invalid_response_issue(
                        "selected source path is not allowed",
                        source_path=source_path,
                        target_path=proposal.target_path,
                    )
                )
        if proposal.expression is None:
            continue
        input_paths, non_input_documents, operation_names = _analyze_expression(proposal.expression)
        for document in sorted(non_input_documents):
            issues.append(
                _invalid_response_issue(
                    "expression get must use the input document",
                    source_path=document,
                    target_path=proposal.target_path,
                )
            )
        for operation in sorted(operation_names.difference(package.expression_operations)):
            issues.append(
                _invalid_response_issue(
                    "expression operation is not allowed by the context",
                    source_path=operation,
                    target_path=proposal.target_path,
                )
            )
        for source_path in sorted(input_paths):
            if source_path not in allowed_source_paths:
                issues.append(
                    _invalid_response_issue(
                        "expression reads a source path that is not allowed",
                        source_path=source_path,
                        target_path=proposal.target_path,
                    )
                )
        selected_source_paths = set(proposal.selected_source_paths)
        for source_path in sorted(selected_source_paths.difference(input_paths)):
            issues.append(
                _invalid_response_issue(
                    "selected source path is not read by the expression",
                    source_path=source_path,
                    target_path=proposal.target_path,
                )
            )
        for source_path in sorted(input_paths.difference(selected_source_paths)):
            issues.append(
                _invalid_response_issue(
                    "expression source path is not selected",
                    source_path=source_path,
                    target_path=proposal.target_path,
                )
            )
    return sort_issues(issues)


__all__ = [
    "MappingContextPackage",
    "ModelCandidateSummary",
    "ModelFieldSummary",
    "ModelMappingResponse",
    "ModelProposalAction",
    "ModelTargetProposal",
    "ModelTargetRequest",
    "mapping_context_sha256",
    "validate_model_mapping_response",
]
