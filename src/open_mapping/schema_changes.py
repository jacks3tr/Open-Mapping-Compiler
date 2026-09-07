"""Conservative contract-change analysis; never migrates bundles or reuses approvals."""

from __future__ import annotations

import json
from functools import cache
from typing import Literal, cast

from open_mapping.matching.candidates import iter_target_mapping_units
from open_mapping.model.bundles import MappingBundle
from open_mapping.model.expressions import analyze_expression
from open_mapping.model.issues import Issue, Severity
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.schema import SchemaDocument
from open_mapping.pointers import split_pointer
from open_mapping.serialization.bundles import validate_bundle
from open_mapping.serialization.canonical_json import canonical_json
from open_mapping.verification.static import verify_static


class RuleImpact(OpenMappingModel):
    target_path: str
    status: Literal["unchanged", "review_required", "invalid"]
    changed_source_paths: tuple[str, ...] = ()
    target_changed: bool = False
    issues: tuple[Issue, ...] = ()


class SchemaChangeReport(OpenMappingModel):
    mapping_id: str
    source_changed: bool
    target_changed: bool
    requires_review: bool
    static_valid: bool
    rules: tuple[RuleImpact, ...]
    added_required_targets: tuple[str, ...]
    removed_source_paths: tuple[str, ...]
    invariant_review_required: bool
    issues: tuple[Issue, ...]


def _document_signature(schema: SchemaDocument) -> str:
    return canonical_json(
        {
            "id": schema.schema_id,
            "version": schema.schema_version,
            "contract": json.loads(schema.canonical_source_json),
            "fields": [
                field.model_dump(mode="json", exclude={"source_location"})
                for field in sorted(schema.fields, key=lambda item: item.pointer)
            ],
        }
    )


def _path_signature(schema: SchemaDocument, pointer: str, *, raw: JsonValue, fallback: str) -> str:
    """Include ancestor constraints and the whole selected branch, excluding siblings.

    Unresolved reference/array paths fall back to the complete contract rather
    than risk classifying a changed dependency as unaffected.
    """
    current = raw
    parts: list[object] = []
    for token in split_pointer(pointer):
        if not isinstance(current, dict):
            return fallback
        required = current.get("required", [])
        parts.append(
            {
                "ancestor": {
                    key: value
                    for key, value in current.items()
                    if key not in {"properties", "required"}
                },
                "required": token in required if isinstance(required, list) else True,
            }
        )
        properties = current.get("properties")
        if not isinstance(properties, dict) or token not in properties:
            return fallback
        current = properties[token]
    parts.append(current)
    field = schema.topology.field(pointer)
    parts.append(
        field.model_dump(mode="json", exclude={"source_location"}) if field is not None else None
    )
    return canonical_json(parts)


def _related(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def analyze_schema_changes(
    bundle: MappingBundle,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> SchemaChangeReport:
    validate_bundle(bundle)
    snapshots = tuple(
        (
            schema,
            cast(JsonValue, json.loads(schema.canonical_source_json)),
            _document_signature(schema),
        )
        for schema in (bundle.source_schema, source_schema, bundle.target_schema, target_schema)
    )

    @cache
    def signature(index: int, pointer: str) -> str:
        schema, raw, fallback = snapshots[index]
        return _path_signature(schema, pointer, raw=raw, fallback=fallback)

    source_changed = snapshots[0][2] != snapshots[1][2]
    target_changed = snapshots[2][2] != snapshots[3][2]
    candidate = bundle.mapping.model_copy(
        update={
            "source_schema": source_schema.schema_id,
            "source_schema_version": source_schema.schema_version,
            "target_schema": target_schema.schema_id,
            "target_schema_version": target_schema.schema_version,
        }
    )
    verification = verify_static(
        candidate, source_schema=source_schema, target_schema=target_schema
    )
    impacts: list[RuleImpact] = []
    for rule in sorted(candidate.rules, key=lambda item: split_pointer(item.target)):
        dependencies = analyze_expression(rule.expression).input_paths
        changed_sources = tuple(
            sorted(path for path in dependencies if signature(0, path) != signature(1, path))
        )
        changed_target = signature(2, rule.target) != signature(3, rule.target)
        issues = tuple(
            issue
            for issue in verification.issues
            if issue.severity is Severity.ERROR
            and (
                (issue.target_path is None and issue.source_path is None)
                or (issue.target_path is not None and _related(issue.target_path, rule.target))
                or (
                    issue.source_path is not None
                    and any(_related(issue.source_path, path) for path in dependencies)
                )
            )
        )
        impacts.append(
            RuleImpact(
                target_path=rule.target,
                status="invalid"
                if issues
                else "review_required"
                if changed_sources or changed_target
                else "unchanged",
                changed_source_paths=changed_sources,
                target_changed=changed_target,
                issues=issues,
            )
        )
    old_required = {
        field.pointer for field in iter_target_mapping_units(bundle.target_schema) if field.required
    }
    new_required = {
        field.pointer for field in iter_target_mapping_units(target_schema) if field.required
    }
    removed = {field.pointer for field in bundle.source_schema.fields} - {
        field.pointer for field in source_schema.fields
    }
    return SchemaChangeReport(
        mapping_id=bundle.mapping.id,
        source_changed=source_changed,
        target_changed=target_changed,
        requires_review=source_changed or target_changed,
        static_valid=verification.valid,
        rules=tuple(impacts),
        added_required_targets=tuple(sorted(new_required - old_required)),
        removed_source_paths=tuple(sorted(removed)),
        invariant_review_required=bool(bundle.mapping.invariants)
        and (source_changed or target_changed),
        issues=verification.issues,
    )


__all__ = ["RuleImpact", "SchemaChangeReport", "analyze_schema_changes"]
