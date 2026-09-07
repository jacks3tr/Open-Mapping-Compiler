"""Deterministic candidate generation."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from heapq import nsmallest
from typing import NamedTuple

from pydantic import model_validator
from rapidfuzz import fuzz

from open_mapping.matching.compatibility import type_compatibility
from open_mapping.matching.names import canonical_name, normalized_name_text
from open_mapping.matching.profiles import FieldProfile
from open_mapping.matching.semantics import (
    FieldSemantics,
    field_semantics,
    profile_support_for_target,
    semantic_field_similarity,
    semantic_fields_conflict,
)
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonScalar, OpenMappingModel
from open_mapping.model.mappings import Evidence, EvidenceKind
from open_mapping.model.schema import JsonType, SchemaDocument, SchemaField
from open_mapping.model.suggestions import (
    CandidateSignals,
    MatchCandidate,
    SuggestionReport,
    TargetCandidateSet,
)
from open_mapping.pointers import split_pointer


class CandidateWeights(OpenMappingModel):
    exact_name: float = 0.35
    name_similarity: float = 0.20
    description_similarity: float = 0.15
    type_compatibility: float = 0.15
    enum_overlap: float = 0.05
    structural_context: float = 0.05
    sample_profile: float = 0.05

    @model_validator(mode="after")
    def _validate_sum(self) -> CandidateWeights:
        total = (
            self.exact_name
            + self.name_similarity
            + self.description_similarity
            + self.type_compatibility
            + self.enum_overlap
            + self.structural_context
            + self.sample_profile
        )
        if any(value < 0 for value in self.model_dump().values()):
            raise ValueError("candidate weights must be non-negative")
        if self.sample_profile > 0.15:
            raise ValueError("sample profile weight must not exceed 0.15")
        if abs(total - 1.0) > 1e-9:
            raise ValueError("candidate weights must sum to 1.0")
        return self


DEFAULT_CANDIDATE_WEIGHTS = CandidateWeights()


def iter_target_mapping_units(schema: SchemaDocument) -> tuple[SchemaField, ...]:
    """Return target fields in deterministic JSON Pointer order."""
    result: list[SchemaField] = []
    for field in schema.fields:
        if field.pointer == "":
            continue
        if schema.topology.is_within_array_items(field.pointer):
            continue
        has_children = bool(schema.topology.children(field.pointer))
        if JsonType.OBJECT in field.types and has_children:
            continue
        result.append(field)
    result.sort(key=lambda item: split_pointer(item.pointer))
    return tuple(result)


def validate_suggestion_coverage(
    report: SuggestionReport, target_schema: SchemaDocument
) -> tuple[Issue, ...]:
    expected = {field.pointer for field in iter_target_mapping_units(target_schema)}
    actual = [suggestion.target_path for suggestion in report.suggestions]
    issues: list[Issue] = []
    seen: set[str] = set()
    for target in actual:
        if target not in expected:
            issues.append(
                Issue(
                    code=IssueCode.SUGGESTION_TARGET_MISSING,
                    severity=Severity.ERROR,
                    component="matching.candidates",
                    message=f"suggestion report contains unexpected target {target!r}",
                    correction="Render exactly one outcome per target mapping unit.",
                    target_path=target,
                )
            )
        if target in seen:
            issues.append(
                Issue(
                    code=IssueCode.SUGGESTION_TARGET_DUPLICATE,
                    severity=Severity.ERROR,
                    component="matching.candidates",
                    message=f"suggestion report contains duplicate target {target!r}",
                    correction="Render each target mapping unit once.",
                    target_path=target,
                )
            )
        seen.add(target)
    for expected_target in sorted(expected):
        if expected_target not in actual:
            issues.append(
                Issue(
                    code=IssueCode.SUGGESTION_TARGET_MISSING,
                    severity=Severity.ERROR,
                    component="matching.candidates",
                    message=f"suggestion report omits target {expected_target!r}",
                    correction="Render one outcome for every target mapping unit.",
                    target_path=expected_target,
                )
            )
    return sort_issues(issues)


def _parent_tokens(pointer: str) -> set[str]:
    parts = split_pointer(pointer)
    result: set[str] = set()
    for part in parts[:-1]:
        result.update(canonical_name(part))
    return result


def _role_tokens(field: SchemaField) -> set[str]:
    result = _parent_tokens(field.pointer)
    result.update(canonical_name(field.pointer.rsplit("/", 1)[-1]))
    result.update(canonical_name(field.title or ""))
    result.update(canonical_name(field.description or ""))
    if "billing" in result or "bill" in result:
        result.add("bill")
    return result


@dataclass(frozen=True, slots=True)
class _FieldFeatures:
    field: SchemaField
    name_tokens: tuple[str, ...]
    title_tokens: tuple[str, ...]
    name_text: str
    title_text: str
    parents: frozenset[str]
    roles: frozenset[str]
    enums: frozenset[JsonScalar]
    semantics: FieldSemantics

    @classmethod
    def prepare(cls, field: SchemaField) -> _FieldFeatures:
        name = field.pointer.rsplit("/", 1)[-1]
        return cls(
            field=field,
            name_tokens=canonical_name(name),
            title_tokens=canonical_name(field.title or ""),
            name_text=normalized_name_text(name),
            title_text=normalized_name_text(field.title or ""),
            parents=frozenset(_parent_tokens(field.pointer)),
            roles=frozenset(_role_tokens(field)),
            enums=frozenset(field.enum_values),
            semantics=field_semantics(field),
        )


class _SignalValues(NamedTuple):
    exact_name: float
    name_similarity: float
    description_similarity: float
    type_compatibility: float
    enum_overlap: float
    structural_context: float
    sample_profile: float

    def validated(self) -> CandidateSignals:
        return CandidateSignals(**self._asdict())


class _ScoredCandidate(NamedTuple):
    raw_score: float
    source_path: str
    signals: _SignalValues


def _role_similarity(source: _FieldFeatures, target: _FieldFeatures) -> float | None:
    source_roles = source.roles
    target_roles = target.roles
    if "identifier" in target_roles and "identifier" not in source_roles:
        source_concepts = source.semantics.concepts
        if not source_concepts.intersection(
            {"code", "identifier", "material_identifier", "site_identifier"}
        ):
            return 0.0
    if "payer" in target_roles:
        return 1.0 if "payer" in source_roles else 0.0
    if "bill" in target_roles:
        return 1.0 if "bill" in source_roles else 0.0
    if "primary" in target_roles and "address" in target_roles:
        return 1.0 if source_roles.intersection({"primary", "ship", "sold"}) else 0.0
    if "business" in target_roles and "partner" in target_roles:
        if "payer" in source_roles:
            return 0.0
        return 1.0 if source_roles.intersection({"customer", "sold", "primary"}) else None
    return None


def _signal_values(
    source_features: _FieldFeatures,
    target_features: _FieldFeatures,
    source_profile: FieldProfile | None,
    target_profile: FieldProfile | None,
) -> _SignalValues:
    source, target = source_features.field, target_features.field
    source_tokens = source_features.name_tokens
    target_tokens = target_features.name_tokens
    source_title_tokens = source_features.title_tokens
    target_title_tokens = target_features.title_tokens
    name_match = (
        (source_tokens and target_tokens and source_tokens == target_tokens)
        or (source_tokens and target_title_tokens and source_tokens == target_title_tokens)
        or (source_title_tokens and target_tokens and source_title_tokens == target_tokens)
    )
    exact = 1.0 if name_match else 0.0
    name_sim = (
        1.0
        if name_match
        else max(
            fuzz.ratio(source_features.name_text, target_features.name_text) / 100.0,
            fuzz.ratio(source_features.name_text, target_features.title_text) / 100.0
            if target.title
            else 0.0,
            fuzz.ratio(source_features.title_text, target_features.name_text) / 100.0
            if source.title
            else 0.0,
        )
    )
    semantic_similarity = semantic_field_similarity(
        source,
        target,
        source_semantics=source_features.semantics,
        target_semantics=target_features.semantics,
    )
    if not name_match:
        name_sim = max(name_sim, semantic_similarity)
    source_desc = source.description or ""
    target_desc = target.description or ""
    desc_sim = fuzz.ratio(source_desc, target_desc) / 100.0 if source_desc and target_desc else 0.0
    role_similarity = _role_similarity(source_features, target_features)
    if role_similarity is not None:
        desc_sim = role_similarity
    elif not name_match:
        desc_sim = max(desc_sim, semantic_similarity)
    semantic_conflict = semantic_fields_conflict(
        source,
        target,
        source_semantics=source_features.semantics,
        target_semantics=target_features.semantics,
    )
    if semantic_conflict:
        name_sim = min(name_sim, 0.20)
        desc_sim = min(desc_sim, 0.20)
    type_score = type_compatibility(source, target) or 0.0
    source_enums = source_features.enums
    target_enums = target_features.enums
    if source_enums and target_enums:
        enum_overlap = len(source_enums.intersection(target_enums)) / len(
            source_enums.union(target_enums)
        )
    else:
        enum_overlap = 0.0
    source_parents = source_features.parents
    target_parents = target_features.parents
    if source_parents and target_parents:
        structural = len(source_parents.intersection(target_parents)) / len(
            source_parents.union(target_parents)
        )
    else:
        structural = 1.0 if not source_parents and not target_parents else 0.0
    if role_similarity is not None:
        structural = role_similarity
    sample_score = profile_support_for_target(
        source_profile, target, target_semantics=target_features.semantics
    )
    if source_profile is not None and target_profile is not None:
        overlap = set(source_profile.pattern_classes).intersection(target_profile.pattern_classes)
        sample_score = max(
            sample_score,
            len(overlap)
            / max(
                len(set(source_profile.pattern_classes).union(target_profile.pattern_classes)), 1
            ),
        )
    return _SignalValues(
        exact, name_sim, desc_sim, type_score, enum_overlap, structural, sample_score
    )


def _evidence(signals: CandidateSignals) -> tuple[Evidence, ...]:
    exact = signals.exact_name
    name_sim = signals.name_similarity
    desc_sim = signals.description_similarity
    type_score = signals.type_compatibility
    enum_overlap = signals.enum_overlap
    structural = signals.structural_context
    sample_score = signals.sample_profile
    evidence: list[Evidence] = []
    if exact:
        evidence.append(
            Evidence(kind=EvidenceKind.EXACT_NAME, detail="Normalized names match.", score=exact)
        )
    if name_sim:
        evidence.append(
            Evidence(
                kind=EvidenceKind.NAME_SIMILARITY,
                detail="Field name tokens are similar.",
                score=name_sim,
            )
        )
    if desc_sim:
        evidence.append(
            Evidence(
                kind=EvidenceKind.DESCRIPTION_SIMILARITY,
                detail="Descriptions or semantic field roles are similar.",
                score=desc_sim,
            )
        )
    if type_score:
        evidence.append(
            Evidence(
                kind=EvidenceKind.TYPE_COMPATIBILITY,
                detail="Types are compatible.",
                score=type_score,
            )
        )
    if enum_overlap:
        evidence.append(
            Evidence(
                kind=EvidenceKind.ENUM_COMPATIBILITY, detail="Enums overlap.", score=enum_overlap
            )
        )
    if structural:
        evidence.append(
            Evidence(
                kind=EvidenceKind.STRUCTURAL_CONTEXT,
                detail="Parent context is similar.",
                score=structural,
            )
        )
    if sample_score:
        evidence.append(
            Evidence(
                kind=EvidenceKind.SAMPLE_PROFILE,
                detail="Observed pattern classes overlap.",
                score=sample_score,
            )
        )
    return tuple(evidence)


def generate_candidates(
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    *,
    source_profiles: Sequence[FieldProfile],
    target_profiles: Sequence[FieldProfile],
    weights: CandidateWeights = DEFAULT_CANDIDATE_WEIGHTS,
    top_k: int = 10,
) -> tuple[TargetCandidateSet, ...]:
    source_profile_map = {profile.pointer: profile for profile in source_profiles}
    target_profile_map = {profile.pointer: profile for profile in target_profiles}
    sources = tuple(
        _FieldFeatures.prepare(field) for field in source_schema.fields if field.pointer
    )
    result: list[TargetCandidateSet] = []

    def scores(target_features: _FieldFeatures) -> Iterator[_ScoredCandidate]:
        target = target_features.field
        for source_features in sources:
            source = source_features.field
            if type_compatibility(source, target) is None:
                continue
            signals = _signal_values(
                source_features,
                target_features,
                source_profile_map.get(source.pointer),
                target_profile_map.get(target.pointer),
            )
            raw_score = (
                signals.exact_name * weights.exact_name
                + signals.name_similarity * weights.name_similarity
                + signals.description_similarity * weights.description_similarity
                + signals.type_compatibility * weights.type_compatibility
                + signals.enum_overlap * weights.enum_overlap
                + signals.structural_context * weights.structural_context
                + signals.sample_profile * weights.sample_profile
            )
            if (
                source_schema.schema_version == "inferred-v0.1"
                and source.pointer == target.pointer
                and signals.type_compatibility == 1.0
            ):
                raw_score = max(raw_score, 0.95)
            yield _ScoredCandidate(round(raw_score, 12), source.pointer, signals)

    for target in iter_target_mapping_units(target_schema):
        selected = nsmallest(
            top_k,
            scores(_FieldFeatures.prepare(target)),
            key=lambda item: (-item.raw_score, item.source_path),
        )
        candidates: list[MatchCandidate] = []
        for item in selected:
            signals = item.signals.validated()
            candidates.append(
                MatchCandidate(
                    source_path=item.source_path,
                    target_path=target.pointer,
                    raw_score=item.raw_score,
                    signals=signals,
                    evidence=_evidence(signals),
                )
            )
        result.append(TargetCandidateSet(target_path=target.pointer, candidates=tuple(candidates)))
    result.sort(key=lambda item: split_pointer(item.target_path))
    return tuple(result)


__all__ = [
    "CandidateWeights",
    "DEFAULT_CANDIDATE_WEIGHTS",
    "TargetCandidateSet",
    "iter_target_mapping_units",
    "validate_suggestion_coverage",
    "generate_candidates",
]
