"""Compact, deterministic, privacy-aware model context construction."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import cast

from pydantic import Field

from open_mapping.errors import OpenMappingError
from open_mapping.matching.candidates import iter_target_mapping_units
from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.hints import MappingHints
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.model_config import ContextMode
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelTargetRequest,
)
from open_mapping.model.schema import JsonType, SchemaDocument, SchemaField
from open_mapping.model.suggestions import MatchCandidate, TargetCandidateSet
from open_mapping.pointers import normalize_pointer, split_pointer
from open_mapping.providers.redaction import redact_json_with_count
from open_mapping.serialization.canonical_json import canonical_json, canonical_json_bytes

_COMPONENT = "providers.context"
_DESCRIPTION_LIMIT = 512
_BUSINESS_INSTRUCTION_LIMIT = 1000
_EVIDENCE_LIMIT = 300
_RAW_SAMPLE_LIMIT = 10
_RAW_SAMPLE_BYTE_LIMIT = 256 * 1024
_BATCH_ID_PLACEHOLDER = "batch-abcd-abcdefghijklmnop"

_EXPRESSION_OPERATION_SEMANTICS: dict[str, str] = {
    "add": "Add two numeric values.",
    "and": "Require every boolean operand to be true.",
    "array": "Build an array from item expressions.",
    "cast": "Convert a value to a supported scalar type.",
    "coalesce": "Return the first non-null operand.",
    "concat": "Join string operands with an optional separator.",
    "divide": "Divide the left numeric value by the right.",
    "equals": "Compare two values for equality.",
    "format_date": "Format a parsed date with a declared pattern.",
    "get": "Read an allowlisted JSON Pointer from the input.",
    "if": "Choose between expressions using a boolean condition.",
    "literal": "Produce a JSON literal value.",
    "lookup": "Map a key through a finite value table.",
    "map": "Apply an expression to each collection item.",
    "multiply": "Multiply two numeric values.",
    "not": "Negate a boolean value.",
    "object": "Build an object from named expressions.",
    "or": "Require at least one boolean operand to be true.",
    "parse_date": "Parse a supported date string.",
    "round": "Round a numeric value to bounded digits.",
    "subtract": "Subtract the right numeric value from the left.",
}
_EXPRESSION_OPERATIONS = tuple(sorted(_EXPRESSION_OPERATION_SEMANTICS))


class ContextPackingOptions(OpenMappingModel):
    """Bounds and packing mode for provider-neutral model context."""

    mode: ContextMode
    input_token_budget: int = Field(gt=0)
    target_batch_size: int = Field(gt=0)
    candidate_limit_per_target: int = Field(gt=0)
    include_raw_samples: bool = False


def estimate_context_tokens(value: JsonValue) -> int:
    """Return ceil(len(canonical_json_bytes(value)) / 3)."""
    return (len(canonical_json_bytes(value)) + 2) // 3


def _pointer_key(pointer: str) -> tuple[str, ...]:
    return split_pointer(normalize_pointer(pointer))


def _sorted_fields(schema: SchemaDocument) -> tuple[SchemaField, ...]:
    return tuple(sorted(schema.fields, key=lambda field: _pointer_key(field.pointer)))


def _bounded(text: str, limit: int) -> str:
    return text[:limit]


def _field_summary(field: SchemaField) -> tuple[ModelFieldSummary, int, int]:
    description = field.description
    redaction_count = 0
    if description is not None:
        redacted_description, redaction_count = redact_json_with_count(description)
        description = cast(str, redacted_description)
    truncated = int(description is not None and len(description) > _DESCRIPTION_LIMIT)
    if description is not None:
        description = _bounded(description, _DESCRIPTION_LIMIT)
    constraints: dict[str, JsonValue] = {}
    if field.minimum is not None:
        constraints["minimum"] = field.minimum
    if field.maximum is not None:
        constraints["maximum"] = field.maximum
    if field.min_length is not None:
        constraints["min_length"] = field.min_length
    if field.max_length is not None:
        constraints["max_length"] = field.max_length
    if field.pattern is not None:
        constraints["pattern"] = field.pattern
    return (
        ModelFieldSummary(
            pointer=normalize_pointer(field.pointer),
            types=tuple(sorted(item.value for item in field.types)),
            required=field.required,
            title=field.title,
            description=description,
            enum_values=tuple(sorted(field.enum_values, key=canonical_json)),
            item_types=tuple(sorted(item.value for item in field.item_types)),
            constraints=constraints,
        ),
        truncated,
        redaction_count,
    )


def _evidence_text(candidate: MatchCandidate) -> tuple[str, ...]:
    evidence = sorted(
        candidate.evidence,
        key=lambda item: (
            item.kind.value,
            item.detail,
            item.score if item.score is not None else -1,
        ),
    )
    result: list[str] = []
    for item in evidence:
        rendered = f"{item.kind.value}: {item.detail}"
        if item.score is not None:
            rendered += f" (score={item.score:g})"
        result.append(_bounded(rendered, _EVIDENCE_LIMIT))
    return tuple(result)


def _candidate_summary(candidate: MatchCandidate) -> ModelCandidateSummary:
    return ModelCandidateSummary(
        source_path=normalize_pointer(candidate.source_path),
        raw_score=candidate.raw_score,
        evidence=_evidence_text(candidate),
    )


def _sorted_candidates(
    candidate_set: TargetCandidateSet | None, limit: int
) -> tuple[ModelCandidateSummary, ...]:
    if candidate_set is None:
        return ()
    candidates = sorted(
        candidate_set.candidates,
        key=lambda item: (
            -item.raw_score,
            _pointer_key(item.source_path),
            canonical_json(cast(JsonValue, item.model_dump(mode="json"))),
        ),
    )
    return tuple(_candidate_summary(candidate) for candidate in candidates[:limit])


def _candidate_sets_by_target(
    candidate_sets: Sequence[TargetCandidateSet],
) -> dict[str, TargetCandidateSet]:
    grouped: dict[str, list[MatchCandidate]] = {}
    for candidate_set in candidate_sets:
        target = normalize_pointer(candidate_set.target_path)
        grouped.setdefault(target, []).extend(candidate_set.candidates)
    return {
        target: TargetCandidateSet(target_path=target, candidates=tuple(candidates))
        for target, candidates in grouped.items()
    }


def _expression_source_paths(value: JsonValue) -> set[str]:
    result: set[str] = set()
    stack: list[JsonValue] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if (
                current.get("op") == "get"
                and current.get("document", "input") == "input"
                and isinstance(current.get("path"), str)
            ):
                result.add(normalize_pointer(cast(str, current["path"])))
            stack.extend(cast(JsonValue, item) for item in current.values())
        elif isinstance(current, list):
            stack.extend(cast(JsonValue, item) for item in current)
    return result


def _hint_records(hints: MappingHints | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if hints is None:
        return ()
    records: list[tuple[str, str, str, tuple[str, ...]]] = []
    for direct_hint in hints.direct:
        text = (
            f"Direct mapping: map {direct_hint.target} from {direct_hint.source}. "
            f"Reason: {direct_hint.reason}"
        )
        records.append(
            (
                "direct",
                direct_hint.target,
                text,
                (normalize_pointer(direct_hint.source),),
            )
        )
    for lookup_hint in hints.lookups:
        values = canonical_json(cast(JsonValue, lookup_hint.values))
        default = canonical_json(lookup_hint.default)
        text = (
            f"Lookup mapping: map {lookup_hint.target} from {lookup_hint.source} using "
            f"{values}; default {default}. Reason: {lookup_hint.reason}"
        )
        records.append(
            (
                "lookup",
                lookup_hint.target,
                text,
                (normalize_pointer(lookup_hint.source),),
            )
        )
    for unit_hint in hints.unit_conversions:
        factors = canonical_json(cast(JsonValue, unit_hint.factors))
        text = (
            f"Unit conversion: map {unit_hint.target} from {unit_hint.value_source} using unit "
            f"{unit_hint.unit_source} and factors {factors}. Reason: {unit_hint.reason}"
        )
        records.append(
            (
                "unit_conversion",
                unit_hint.target,
                text,
                (
                    normalize_pointer(unit_hint.value_source),
                    normalize_pointer(unit_hint.unit_source),
                ),
            )
        )
    for date_hint in hints.dates:
        text = (
            f"Date mapping: map {date_hint.target} from {date_hint.source} using pattern "
            f"{date_hint.pattern}. Reason: {date_hint.reason}"
        )
        records.append(("date", date_hint.target, text, (normalize_pointer(date_hint.source),)))
    for constant_hint in hints.constants:
        value = canonical_json(constant_hint.value)
        text = (
            f"Constant mapping: set {constant_hint.target} to {value}. "
            f"Reason: {constant_hint.reason}"
        )
        records.append(("constant", constant_hint.target, text, ()))
    for expression_hint in hints.expressions:
        expression = cast(JsonValue, expression_hint.expression.model_dump(mode="json"))
        text = (
            f"Expression mapping: map {expression_hint.target} with "
            f"{canonical_json(expression)}. Reason: {expression_hint.reason}"
        )
        records.append(
            (
                "expression",
                expression_hint.target,
                text,
                tuple(sorted(_expression_source_paths(expression), key=_pointer_key)),
            )
        )
    records.sort(key=lambda item: (item[0], _pointer_key(item[1]), item[2], item[3]))
    return tuple(
        (_bounded(text, _BUSINESS_INSTRUCTION_LIMIT), source_paths)
        for _kind, _target, text, source_paths in records
    )


def _business_instructions(
    hints: MappingHints | None, instruction: str | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    hint_records = _hint_records(hints)
    texts = [record[0] for record in hint_records]
    if instruction is not None and instruction != "":
        texts.append(_bounded(f"CLI instruction: {instruction}", _BUSINESS_INSTRUCTION_LIMIT))
    hint_paths = {path for _text, source_paths in hint_records for path in source_paths}
    return tuple(texts), tuple(sorted(hint_paths, key=_pointer_key))


def _redacted_raw_samples(
    raw_samples: Sequence[JsonValue], *, include: bool
) -> tuple[tuple[JsonValue, ...] | None, int]:
    if not include:
        return None, 0
    included: list[JsonValue] = []
    redaction_count = 0
    for sample in raw_samples[:_RAW_SAMPLE_LIMIT]:
        redacted, count = redact_json_with_count(sample)
        tentative = [*included, redacted]
        if len(canonical_json_bytes(cast(JsonValue, tentative))) > _RAW_SAMPLE_BYTE_LIMIT:
            break
        included.append(redacted)
        redaction_count += count
    return tuple(included), redaction_count


def _direct_siblings(pointer: str, fields: Sequence[SchemaField]) -> set[str]:
    parent = normalize_pointer(pointer).rsplit("/", 1)[0]
    return {
        field.pointer
        for field in fields
        if normalize_pointer(field.pointer).rsplit("/", 1)[0] == parent
    }


def _ancestors(pointer: str, existing: set[str]) -> set[str]:
    result: set[str] = set()
    parent = normalize_pointer(pointer).rsplit("/", 1)[0]
    while parent:
        if parent in existing:
            result.add(parent)
        parent = parent.rsplit("/", 1)[0]
    return result


def _targeted_source_paths(
    *,
    fields: tuple[SchemaField, ...],
    requests: Sequence[ModelTargetRequest],
    hint_paths: Sequence[str],
) -> set[str]:
    existing = {field.pointer for field in fields}
    candidate_paths = {
        candidate.source_path for request in requests for candidate in request.candidates
    }
    selected = {path for path in hint_paths if path in existing}
    selected.update(candidate_paths)
    for path in candidate_paths:
        selected.update(_ancestors(path, existing))
        selected.update(_direct_siblings(path, fields))

    array_paths = {
        field.pointer
        for field in fields
        if JsonType.ARRAY in field.types and field.pointer in selected
    }
    for array_path in array_paths:
        item_prefix = array_path.rstrip("/") + "/items"
        selected.update(
            field.pointer
            for field in fields
            if field.pointer == item_prefix or field.pointer.startswith(item_prefix + "/")
        )
    return selected.intersection(existing)


def _safe_profiles(
    profiles: Sequence[FieldProfile], included_paths: set[str]
) -> tuple[FieldProfile, ...]:
    return tuple(
        sorted(
            (profile for profile in profiles if profile.pointer in included_paths),
            key=lambda profile: _pointer_key(profile.pointer),
        )
    )


def _package_value(package: MappingContextPackage) -> JsonValue:
    return cast(JsonValue, package.model_dump(mode="json"))


def _finalize_package(
    package: MappingContextPackage,
    *,
    ordinal: int,
    raw_sample_redaction_count: int,
) -> MappingContextPackage:
    prior_redaction_count = package.redaction_count
    redacted, package_redaction_count = redact_json_with_count(_package_value(package))
    payload = cast(dict[str, object], redacted)
    payload["redaction_count"] = (
        prior_redaction_count + package_redaction_count + raw_sample_redaction_count
    )
    payload["batch_id"] = ""
    digest_value: JsonValue = {
        "batch_ordinal": ordinal,
        "package": payload,
    }
    digest = hashlib.sha256(canonical_json_bytes(digest_value)).hexdigest()
    payload["batch_id"] = f"batch-{ordinal:04d}-{digest[:16]}"
    return MappingContextPackage.model_validate(payload)


def _build_package(
    *,
    mode: ContextMode,
    target_fields: Sequence[SchemaField],
    source_fields: tuple[SchemaField, ...],
    candidates_by_target: dict[str, TargetCandidateSet],
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    source_profiles: Sequence[FieldProfile],
    business_instructions: tuple[str, ...],
    hint_paths: tuple[str, ...],
    raw_samples: tuple[JsonValue, ...] | None,
    raw_sample_redaction_count: int,
    candidate_limit: int,
    ordinal: int,
) -> MappingContextPackage:
    target_requests: list[ModelTargetRequest] = []
    truncation_count = 0
    redaction_count = 0
    for target_field in target_fields:
        target_summary, truncated, redacted = _field_summary(target_field)
        truncation_count += truncated
        redaction_count += redacted
        target_requests.append(
            ModelTargetRequest(
                target=target_summary,
                candidates=_sorted_candidates(
                    candidates_by_target.get(target_summary.pointer), candidate_limit
                ),
            )
        )

    if mode is ContextMode.FULL:
        included_source_fields = source_fields
    else:
        selected_paths = _targeted_source_paths(
            fields=source_fields,
            requests=target_requests,
            hint_paths=hint_paths,
        )
        included_source_fields = tuple(
            field for field in source_fields if field.pointer in selected_paths
        )
    source_summaries: list[ModelFieldSummary] = []
    for source_field in included_source_fields:
        summary, truncated, redacted = _field_summary(source_field)
        source_summaries.append(summary)
        truncation_count += truncated
        redaction_count += redacted
    included_paths = {summary.pointer for summary in source_summaries}
    package = MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id=_BATCH_ID_PLACEHOLDER,
        context_mode=mode,
        source_schema_id=source_schema.schema_id,
        source_schema_version=source_schema.schema_version,
        target_schema_id=target_schema.schema_id,
        target_schema_version=target_schema.schema_version,
        source_fields=tuple(source_summaries),
        target_requests=tuple(target_requests),
        sample_profiles=_safe_profiles(source_profiles, included_paths),
        business_instructions=business_instructions,
        expression_operations=_EXPRESSION_OPERATIONS,
        expression_operation_semantics=dict(_EXPRESSION_OPERATION_SEMANTICS),
        allowed_source_paths=tuple(summary.pointer for summary in source_summaries),
        raw_samples=raw_samples,
        truncation_count=truncation_count,
        redaction_count=redaction_count,
        raw_samples_included=raw_samples is not None,
    )
    return _finalize_package(
        package,
        ordinal=ordinal,
        raw_sample_redaction_count=raw_sample_redaction_count,
    )


def _too_large(
    target_path: str, mode: ContextMode, token_count: int, budget: int
) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.MODEL_CONTEXT_TOO_LARGE,
                severity=Severity.ERROR,
                component=_COMPONENT,
                message=(
                    f"model context for target {target_path!r} requires {token_count} estimated "
                    f"tokens in {mode.value} mode, exceeding the {budget} token budget"
                ),
                correction=(
                    "Increase the model input token budget or reduce the required schema context."
                ),
                target_path=target_path,
            ),
        )
    )


def _groups(target_fields: tuple[SchemaField, ...], size: int) -> list[tuple[SchemaField, ...]]:
    return [target_fields[index : index + size] for index in range(0, len(target_fields), size)]


def build_mapping_context_batches(
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    candidate_sets: Sequence[TargetCandidateSet],
    source_profiles: Sequence[FieldProfile],
    hints: MappingHints | None,
    instruction: str | None,
    raw_samples: Sequence[JsonValue],
    options: ContextPackingOptions,
) -> tuple[MappingContextPackage, ...]:
    """Build deterministic, budgeted context packages for model mapping requests."""
    source_fields = tuple(field for field in _sorted_fields(source_schema) if field.pointer != "")
    target_fields = tuple(iter_target_mapping_units(target_schema))
    candidates_by_target = _candidate_sets_by_target(candidate_sets)
    business_instructions, hint_paths = _business_instructions(hints, instruction)
    included_raw_samples, raw_redaction_count = _redacted_raw_samples(
        raw_samples,
        include=options.include_raw_samples,
    )

    def make_package(
        mode: ContextMode,
        group: tuple[SchemaField, ...],
        ordinal: int,
    ) -> MappingContextPackage:
        return _build_package(
            mode=mode,
            target_fields=group,
            source_fields=source_fields,
            candidates_by_target=candidates_by_target,
            source_schema=source_schema,
            target_schema=target_schema,
            source_profiles=source_profiles,
            business_instructions=business_instructions,
            hint_paths=hint_paths,
            raw_samples=included_raw_samples,
            raw_sample_redaction_count=raw_redaction_count,
            candidate_limit=options.candidate_limit_per_target,
            ordinal=ordinal,
        )

    initial_groups = _groups(target_fields, options.target_batch_size)
    if options.mode is ContextMode.AUTO:
        full = tuple(
            make_package(ContextMode.FULL, group, index)
            for index, group in enumerate(initial_groups, start=1)
        )
        if all(
            estimate_context_tokens(_package_value(package)) <= options.input_token_budget
            for package in full
        ):
            return full
        mode = ContextMode.TARGETED
    else:
        mode = options.mode

    fitting_groups: list[tuple[SchemaField, ...]] = []
    pending = list(initial_groups)
    while pending:
        group = pending.pop(0)
        provisional = make_package(mode, group, 1)
        token_count = estimate_context_tokens(_package_value(provisional))
        if token_count <= options.input_token_budget:
            fitting_groups.append(group)
            continue
        if len(group) == 1:
            raise _too_large(
                group[0].pointer,
                mode,
                token_count,
                options.input_token_budget,
            )
        midpoint = len(group) // 2
        pending[0:0] = [group[:midpoint], group[midpoint:]]

    return tuple(
        make_package(mode, group, index) for index, group in enumerate(fitting_groups, start=1)
    )


__all__ = [
    "ContextPackingOptions",
    "build_mapping_context_batches",
    "estimate_context_tokens",
]
