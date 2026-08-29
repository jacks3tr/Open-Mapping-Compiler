"""Semantic candidate evidence beyond literal field spelling."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.candidates import generate_candidates
from open_mapping.matching.profiles import profile_samples
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.semantics import semantic_fields_conflict
from open_mapping.model.suggestions import SuggestionDisposition


def test_typed_business_concepts_resolve_different_industry_names() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["part_no", "legacy_part_no", "vendor_material_ref"],
            "properties": {
                "part_no": {
                    "type": "string",
                    "description": "Current internal identifier assigned to the item.",
                },
                "legacy_part_no": {
                    "type": "string",
                    "description": "Superseded item identifier for historical lookup.",
                },
                "vendor_material_ref": {
                    "type": "string",
                    "description": "Supplier catalog identifier for the item.",
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["materialMaster"],
            "properties": {
                "materialMaster": {
                    "type": "string",
                    "description": "Primary identifier used as the canonical material record key.",
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )

    candidate_set = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
    )[0]
    report = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(candidate_set,),
        hints=None,
    )

    assert candidate_set.candidates[0].source_path == "/part_no"
    assert candidate_set.candidates[0].signals.type_compatibility == 1.0
    assert candidate_set.candidates[0].signals.description_similarity >= 0.75
    assert report.suggestions[0].selected_source_path == "/part_no"
    assert report.suggestions[0].disposition == SuggestionDisposition.REVIEW_REQUIRED


def test_privacy_safe_value_profile_ranks_opaque_email_field() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {
                "alpha": {"type": "string"},
                "beta": {"type": "string"},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "title": "Contact Email",
                    "description": "Email address used for notifications.",
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    profiles = profile_samples(
        source,
        (
            {"alpha": "person@example.com", "beta": "2026-08-29"},
            {"alpha": "team@example.org", "beta": "2026-08-30"},
        ),
    )

    candidate_set = generate_candidates(
        source,
        target,
        source_profiles=profiles,
        target_profiles=(),
    )[0]

    assert candidate_set.candidates[0].source_path == "/alpha"
    assert candidate_set.candidates[0].signals.sample_profile == 1.0
    assert candidate_set.candidates[1].signals.sample_profile == 0.0


def test_standard_identifier_aliases_resolve_without_vendor_mapping_pairs() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["gtin", "internal_item_id"],
            "properties": {
                "gtin": {
                    "type": "string",
                    "description": "Global Trade Item Number printed as a retail barcode.",
                },
                "internal_item_id": {
                    "type": "string",
                    "description": "Private identifier assigned to the material record.",
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["barcodeEan"],
            "properties": {
                "barcodeEan": {
                    "type": "string",
                    "description": "Global retail barcode value.",
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )

    candidate_set = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
    )[0]
    report = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(candidate_set,),
        hints=None,
    )

    assert candidate_set.candidates[0].source_path == "/gtin"
    assert report.suggestions[0].selected_source_path == "/gtin"


def test_semantic_conflict_prevents_days_from_equating_unrelated_durations() -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {
                "lead_time_days": {
                    "type": "integer",
                    "description": "Days between replenishment request and availability.",
                }
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "properties": {
                "shelfLifeDays": {
                    "type": "integer",
                    "description": "Maximum usable life before expiration, in days.",
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    candidate_set = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
    )[0]
    report = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(candidate_set,),
        hints=None,
    )

    assert semantic_fields_conflict(source.fields[0], target.fields[0])
    assert report.suggestions[0].disposition == SuggestionDisposition.NO_MATCH
