"""Deterministic candidate generation."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import model_validator
from rapidfuzz import fuzz

from open_mapping.matching.compatibility import type_compatibility
from open_mapping.matching.names import canonical_name, normalized_name_text
from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import OpenMappingModel
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
    exact_name: float = 0.40
    name_similarity: float = 0.20
    description_similarity: float = 0.15
    type_compatibility: float = 0.15
    enum_overlap: float = 0.05
    structural_context: float = 0.05
    sample_profile: float = 0.00

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
        if "items" in split_pointer(field.pointer):
            continue
        has_children = any(
            other.pointer.startswith(field.pointer.rstrip("/") + "/")
            for other in schema.fields
            if other is not field
        )
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


def _role_similarity(source: SchemaField, target: SchemaField) -> float | None:
    source_roles = _role_tokens(source)
    target_roles = _role_tokens(target)
    if "identifier" in target_roles and "identifier" not in source_roles:
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


def _signal(
    source: SchemaField,
    target: SchemaField,
    source_profile: FieldProfile | None,
    target_profile: FieldProfile | None,
) -> tuple[CandidateSignals, list[Evidence]]:
    source_name = source.pointer.rsplit("/", 1)[-1]
    target_name = target.pointer.rsplit("/", 1)[-1]
    source_tokens = canonical_name(source_name)
    target_tokens = canonical_name(target_name)
    source_title_tokens = canonical_name(source.title or "")
    target_title_tokens = canonical_name(target.title or "")
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
            fuzz.ratio(normalized_name_text(source_name), normalized_name_text(target_name))
            / 100.0,
            fuzz.ratio(normalized_name_text(source_name), normalized_name_text(target.title or ""))
            / 100.0
            if target.title
            else 0.0,
            fuzz.ratio(normalized_name_text(source.title or ""), normalized_name_text(target_name))
            / 100.0
            if source.title
            else 0.0,
        )
    )
    source_desc = source.description or ""
    target_desc = target.description or ""
    desc_sim = fuzz.ratio(source_desc, target_desc) / 100.0 if source_desc and target_desc else 0.0
    role_similarity = _role_similarity(source, target)
    if role_similarity is not None:
        desc_sim = role_similarity
    type_score = type_compatibility(source, target) or 0.0
    source_enums = set(source.enum_values)
    target_enums = set(target.enum_values)
    if source_enums and target_enums:
        enum_overlap = len(source_enums.intersection(target_enums)) / len(
            source_enums.union(target_enums)
        )
    else:
        enum_overlap = 0.0
    source_parents = _parent_tokens(source.pointer)
    target_parents = _parent_tokens(target.pointer)
    if source_parents and target_parents:
        structural = len(source_parents.intersection(target_parents)) / len(
            source_parents.union(target_parents)
        )
    else:
        structural = 1.0 if not source_parents and not target_parents else 0.0
    if role_similarity is not None:
        structural = role_similarity
    sample_score = 0.0
    if source_profile is not None and target_profile is not None:
        overlap = set(source_profile.pattern_classes).intersection(target_profile.pattern_classes)
        sample_score = len(overlap) / max(
            len(set(source_profile.pattern_classes).union(target_profile.pattern_classes)), 1
        )
    signals = CandidateSignals(
        exact_name=exact,
        name_similarity=name_sim,
        description_similarity=desc_sim,
        type_compatibility=type_score,
        enum_overlap=enum_overlap,
        structural_context=structural,
        sample_profile=sample_score,
    )
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
                detail="Descriptions are similar.",
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
    return signals, evidence


def generate_candidates(
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    *,
    source_profiles: Sequence[FieldProfile],
    target_profiles: Sequence[FieldProfile],
    weights: CandidateWeights = DEFAULT_CANDIDATE_WEIGHTS,
    top_k: int = 10,
) -> tuple[TargetCandidateSet, ...]:
    profile_map = {profile.pointer: profile for profile in (*source_profiles, *target_profiles)}
    result: list[TargetCandidateSet] = []
    for target in iter_target_mapping_units(target_schema):
        candidates: list[MatchCandidate] = []
        for source in source_schema.fields:
            if source.pointer == "":
                continue
            if type_compatibility(source, target) is None:
                continue
            signals, evidence = _signal(
                source,
                target,
                profile_map.get(source.pointer),
                profile_map.get(target.pointer),
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
            candidates.append(
                MatchCandidate(
                    source_path=source.pointer,
                    target_path=target.pointer,
                    raw_score=round(raw_score, 12),
                    signals=signals,
                    evidence=tuple(evidence),
                )
            )
        candidates.sort(key=lambda item: (-item.raw_score, item.source_path))
        result.append(
            TargetCandidateSet(target_path=target.pointer, candidates=tuple(candidates[:top_k]))
        )
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
