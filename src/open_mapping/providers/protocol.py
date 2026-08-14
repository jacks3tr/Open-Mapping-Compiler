"""Optional model-provider protocol."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Literal, Protocol, TypeAlias, runtime_checkable

from pydantic import Field, model_validator

from open_mapping.errors import OpenMappingError
from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.expressions import Expression
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.mappings import Evidence
from open_mapping.model.model_config import ResolvedModel
from open_mapping.model.providers import ModelUsage as ModelUsage
from open_mapping.model.providers import ProviderDisclosure
from open_mapping.model.schema import SchemaField
from open_mapping.model.suggestions import MatchCandidate
from open_mapping.providers.prompt import ModelPrompt
from open_mapping.serialization.canonical_json import canonical_json_bytes


class ModelTransportRequest(OpenMappingModel):
    """One provider-neutral synchronous model invocation."""

    resolved_model: ResolvedModel
    prompt: ModelPrompt


class ModelTransportResult(OpenMappingModel):
    """Parsed structured payload and bounded invocation metadata."""

    payload: JsonValue
    provider_request_id: str | None
    usage: ModelUsage
    latency_ms: int
    response_sha256: str


@runtime_checkable
class ModelTransport(Protocol):
    """The only synchronous interface used to call a model provider."""

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        """Invoke one fully resolved model request."""
        ...


TransportFactory: TypeAlias = Callable[[ResolvedModel], ModelTransport]


class ProviderRequest(OpenMappingModel):
    protocol_version: Literal["0.1"]
    task: Literal["rerank-and-propose"]
    source_schema_id: str
    target_schema_id: str
    target_path: str
    candidates: tuple[MatchCandidate, ...]
    source_field_metadata: tuple[SchemaField, ...]
    target_field_metadata: SchemaField
    sample_profiles: tuple[FieldProfile, ...]
    instruction_text: str | None = None
    raw_samples: tuple[JsonValue, ...] | None = None
    model_prompt: ModelPrompt | None = Field(default=None, exclude_if=lambda value: value is None)


class ProviderProposal(OpenMappingModel):
    target_path: str
    abstain: bool
    selected_source_paths: tuple[str, ...] = ()
    expression: Expression | None = None
    evidence: tuple[Evidence, ...] = ()
    reason: str = ""

    @model_validator(mode="after")
    def _validate_abstention(self) -> ProviderProposal:
        if self.abstain and (self.selected_source_paths or self.expression is not None):
            raise ValueError("abstain proposals cannot include selected paths or an expression")
        return self


class ProviderResponse(OpenMappingModel):
    protocol_version: Literal["0.1"]
    proposals: tuple[ProviderProposal, ...]


class ProviderCallResult(OpenMappingModel):
    response: ProviderResponse
    disclosure: ProviderDisclosure


@runtime_checkable
class ProposalProvider(Protocol):
    def propose(self, request: ProviderRequest) -> ProviderCallResult:
        """Return a validated provider result for a bounded request."""
        ...


def _invalid_response(message: str) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.PROVIDER_RESPONSE_INVALID,
                severity=Severity.ERROR,
                component="providers.protocol",
                message=message,
                correction="Return one bounded proposal for the requested target.",
            ),
        )
    )


def provider_expression_input_paths(expression: object) -> set[str]:
    paths: set[str] = set()
    stack = [expression]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("op") == "get" and node.get("document", "input") == "input":
            paths.add(str(node.get("path")))
        for value in node.values():
            if isinstance(value, dict):
                stack.append(value)
            elif isinstance(value, list):
                stack.extend(item for item in value if isinstance(item, dict))
    return paths


def validate_provider_response(response: ProviderResponse, request: ProviderRequest) -> None:
    candidate_paths = {candidate.source_path for candidate in request.candidates}
    for proposal in response.proposals:
        if proposal.target_path != request.target_path:
            raise _invalid_response("provider proposal targets a different target path")
        if not set(proposal.selected_source_paths).issubset(candidate_paths):
            raise _invalid_response("provider selected path is outside the candidate set")
        if proposal.expression is not None:
            get_paths = provider_expression_input_paths(proposal.expression.model_dump(mode="json"))
            if not get_paths.issubset(candidate_paths):
                raise _invalid_response(
                    "provider expression reads a path outside the candidate set"
                )


def aggregate_provider_disclosure(
    *,
    endpoint_origin: str,
    raw_samples_included: bool,
    requests: Sequence[tuple[ProviderRequest, int]],
) -> ProviderDisclosure:
    ordered = sorted(requests, key=lambda item: item[0].target_path)
    bundle: list[object] = [request.model_dump(mode="json") for request, _ in ordered]
    source_paths = {
        field.pointer for request, _ in ordered for field in request.source_field_metadata
    }
    return ProviderDisclosure(
        endpoint_origin=endpoint_origin,
        raw_samples_included=raw_samples_included,
        source_field_count=len(source_paths),
        candidate_count=sum(len(request.candidates) for request, _ in ordered),
        sample_profile_count=sum(len(request.sample_profiles) for request, _ in ordered),
        redaction_count=sum(count for _, count in ordered),
        request_sha256=hashlib.sha256(canonical_json_bytes(bundle)).hexdigest(),
    )
