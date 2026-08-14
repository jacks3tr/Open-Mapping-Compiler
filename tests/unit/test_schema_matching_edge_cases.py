"""Schema matching and verification edge cases."""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.ambiguity import detect_ambiguity
from open_mapping.matching.candidates import iter_target_mapping_units
from open_mapping.matching.compatibility import type_compatibility
from open_mapping.matching.confidence import DEFAULT_CONFIDENCE_THRESHOLDS
from open_mapping.matching.profiles import profile_samples
from open_mapping.model.expressions import Expression
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.reviews import ReviewResult
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.model.suggestions import TargetCandidateSet
from open_mapping.reports.json_report import render_review_json
from open_mapping.reports.markdown_report import render_review_markdown
from open_mapping.verification.dynamic import load_verification_samples
from open_mapping.verification.static import verify_static
from open_mapping.verification.type_inference import infer_expression_type


def test_verification_dynamic_blank_and_static_root() -> None:
    path = Path("benchmarks/erp-mes/samples.jsonl")
    samples = load_verification_samples(path)
    assert samples
    target = parse_json_schema({"$id": "a", "type": "array"}, schema_id=None, source_uri="a")
    source = parse_json_schema({"$id": "s", "type": "object"}, schema_id=None, source_uri="s")
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="wrong",
        target_schema_version="unversioned",
        rules=(),
    )
    issues = verify_static(mapping, source_schema=source, target_schema=target).issues
    assert issues


def test_type_inference_map_non_array() -> None:
    source = parse_json_schema({"$id": "s", "type": "object"}, schema_id=None, source_uri="s")
    target = parse_json_schema({"$id": "t", "type": "object"}, schema_id=None, source_uri="t")
    inferred = infer_expression_type(
        TypeAdapter(Expression).validate_python(
            {
                "op": "map",
                "collection": {"op": "literal", "value": 1},
                "expression": {"op": "literal", "value": 1},
            }
        ),
        source_schema=source,
        target_schema=target,
        current_types=(),
        current_pointer=None,
    )
    assert not inferred


def test_ambiguity_role_paths() -> None:
    candidate_set = TargetCandidateSet.model_validate(
        {
            "target_path": "/line",
            "candidates": (
                {"target_path": "/line", "source_path": "/a/workCenter", "raw_score": 0.9},
                {"target_path": "/line", "source_path": "/b/productionLine", "raw_score": 0.84},
            ),
        }
    )
    assert detect_ambiguity(candidate_set, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS)


def test_compatibility_object_mixed_and_integer_number() -> None:
    mixed = SchemaField(
        pointer="/a", types=frozenset({JsonType.OBJECT, JsonType.STRING}), required=False
    )
    scalar = SchemaField(pointer="/b", types=frozenset({JsonType.STRING}), required=False)
    assert type_compatibility(mixed, scalar) is None
    integer = SchemaField(pointer="/i", types=frozenset({JsonType.INTEGER}), required=False)
    number = SchemaField(pointer="/n", types=frozenset({JsonType.NUMBER}), required=False)
    assert type_compatibility(integer, number) == 0.9


def test_target_units_skip_object_container() -> None:
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "properties": {"obj": {"type": "object", "properties": {"x": {"type": "string"}}}},
        },
        schema_id=None,
        source_uri="t",
    )
    pointers = [field.pointer for field in iter_target_mapping_units(target)]
    assert "/obj" not in pointers
    assert "/obj/x" in pointers


def test_profile_pattern_detection() -> None:
    schema = parse_json_schema(
        {
            "$id": "p",
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "m": {"type": "string"},
                "n": {"type": "integer"},
            },
        },
        schema_id=None,
        source_uri="p",
    )
    samples: list[JsonValue] = [
        {"s": "1.2", "m": "hello world", "n": 1},
        {"s": "2026-01-01T00:00:00Z", "m": "ABC123", "n": 2},
    ]
    profiles = profile_samples(schema, samples)
    assert profiles


def test_review_json_and_markdown_issues() -> None:
    result = ReviewResult(
        suggestion_report_sha256="x",
        mapping_id="m",
        issues=(),
        unresolved_targets=("/a",),
    )
    assert "x" in render_review_json(result)
    assert "/a" in render_review_markdown(result)
