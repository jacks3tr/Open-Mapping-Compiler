"""Typed, source-to-target-agnostic semantic field comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass

from open_mapping.matching.names import name_tokens
from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.schema import JsonType, SchemaField

_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORDS = re.compile(r"[^\W_]+|\d+", re.UNICODE)

# These aliases describe concepts, never a source-to-target mapping. The small
# core intentionally covers common integration vocabulary; unknown words remain
# available to the model instead of being guessed locally.
_TOKEN_CONCEPTS: dict[str, tuple[str, ...]] = {
    "account": ("account",),
    "address": ("address",),
    "amount": ("money",),
    "assortment": ("group",),
    "barcode": ("barcode", "identifier"),
    "batch": ("batch",),
    "bill": ("billing",),
    "billing": ("billing",),
    "buffer": ("buffer_stock",),
    "buy": ("sourcing", "mode"),
    "canonical": ("authoritative",),
    "catalog": ("external", "identifier"),
    "category": ("classification",),
    "channel": ("distribution_channel",),
    "classification": ("classification",),
    "code": ("code",),
    "commercial": ("commercial",),
    "control": ("control",),
    "controller": ("planning", "controller"),
    "cost": ("money",),
    "currency": ("currency",),
    "current": ("authoritative",),
    "customer": ("customer",),
    "date": ("date",),
    "days": ("days",),
    "delivery": ("lead_time",),
    "description": ("description",),
    "describes": ("description",),
    "design": ("design",),
    "document": ("document",),
    "drawing": ("drawing",),
    "duration": ("duration",),
    "ean": ("barcode", "identifier"),
    "email": ("email",),
    "engineering": ("engineering",),
    "expiration": ("shelf_life",),
    "facility": ("site",),
    "family": ("group",),
    "flag": ("flag",),
    "gross": ("gross",),
    "gln": ("site", "identifier"),
    "group": ("group",),
    "gtin": ("barcode", "identifier"),
    "hazardous": ("hazard",),
    "historical": ("legacy",),
    "identifier": ("identifier",),
    "inspection": ("inspection",),
    "internal": ("authoritative",),
    "inventory": ("inventory",),
    "item": ("material",),
    "key": ("identifier",),
    "label": ("description",),
    "lead": ("lead_time",),
    "legacy": ("legacy",),
    "level": ("level",),
    "life": ("shelf_life",),
    "location": ("site",),
    "lot": ("batch",),
    "make": ("sourcing", "mode"),
    "managed": ("control",),
    "mass": ("weight",),
    "master": ("master_record",),
    "material": ("material",),
    "measure": ("unit",),
    "merchandise": ("material",),
    "minimum": ("minimum",),
    "mixed": ("sourcing", "mode"),
    "mode": ("mode",),
    "mrp": ("planning",),
    "name": ("description",),
    "narrative": ("description",),
    "net": ("net",),
    "number": ("identifier",),
    "order": ("order",),
    "organization": ("organization",),
    "owner": ("owner",),
    "owning": ("owner",),
    "part": ("material",),
    "payer": ("payer",),
    "person": ("person",),
    "planned": ("planned",),
    "planner": ("planning", "controller"),
    "planning": ("planning",),
    "plant": ("site",),
    "postal": ("postal_code",),
    "price": ("money",),
    "primary": ("authoritative",),
    "procure": ("sourcing",),
    "procurement": ("sourcing",),
    "product": ("material",),
    "purchased": ("sourcing", "mode"),
    "quality": ("quality",),
    "quantity": ("quantity",),
    "readable": ("description",),
    "record": ("record",),
    "reference": ("reference",),
    "reorder": ("reorder",),
    "reporting": ("reporting",),
    "required": ("required",),
    "reserve": ("buffer_stock",),
    "responsible": ("responsible",),
    "revision": ("revision",),
    "sales": ("sales",),
    "safety": ("buffer_stock",),
    "serial": ("serial",),
    "serialized": ("serial",),
    "shelf": ("shelf_life",),
    "site": ("site",),
    "sku": ("material", "identifier"),
    "sourcing": ("sourcing",),
    "standard": ("standard",),
    "stock": ("inventory",),
    "storage": ("storage",),
    "supplier": ("external",),
    "supplied": ("sourcing",),
    "tax": ("tax",),
    "team": ("team",),
    "technical": ("drawing",),
    "text": ("description",),
    "time": ("duration",),
    "timestamp": ("timestamp",),
    "traceability": ("tracking",),
    "traced": ("tracking",),
    "tracked": ("tracking",),
    "type": ("type",),
    "unit": ("unit",),
    "upc": ("barcode", "identifier"),
    "unique": ("identifier",),
    "valuation": ("valuation", "money"),
    "vendor": ("external",),
    "version": ("revision",),
    "warehouse": ("site",),
    "weight": ("weight",),
}

_ROLE_CONCEPTS = frozenset(
    {
        "barcode_identifier",
        "batch_tracking",
        "currency_code",
        "drawing_reference",
        "email",
        "engineering_revision",
        "gross_weight",
        "inventory_unit",
        "lead_time_days",
        "material_description",
        "material_group",
        "material_identifier",
        "net_weight",
        "planning_controller",
        "safety_stock_quantity",
        "serial_tracking",
        "site_identifier",
        "sourcing_mode",
        "standard_price",
        "weight_unit",
    }
)

_SCOPE_CONCEPTS = frozenset(
    {"account", "address", "customer", "inventory", "material", "order", "planning"}
)

_CONCEPT_WEIGHTS = {concept: 5.0 for concept in _ROLE_CONCEPTS}
_CONCEPT_WEIGHTS.update({concept: 0.5 for concept in _SCOPE_CONCEPTS})

_EXCLUSIVE_GROUPS = (
    frozenset({"authoritative", "external", "legacy"}),
    frozenset({"gross", "net"}),
    frozenset({"buffer_stock", "reorder"}),
    frozenset({"classification", "group"}),
    frozenset({"lead_time", "shelf_life"}),
)


@dataclass(frozen=True, slots=True)
class FieldSemantics:
    concepts: frozenset[str]


def _tokens(field: SchemaField) -> tuple[str, ...]:
    pointer_text = " ".join(part for part in field.pointer.split("/") if part)
    text = " ".join(
        part for part in (pointer_text, field.title or "", field.description or "") if part
    )
    words = _WORDS.findall(_CAMEL_SPLIT.sub(" ", text))
    return tuple(token for word in words for token in name_tokens(word))


def field_semantics(field: SchemaField) -> FieldSemantics:
    """Return a deterministic semantic signature derived from field metadata."""
    concepts: set[str] = set()
    for token in _tokens(field):
        concepts.update(_TOKEN_CONCEPTS.get(token, ()))

    specific_identifier_context = concepts.intersection(
        {"barcode", "currency", "drawing", "planning", "site", "unit"}
    )
    if (
        "material" in concepts
        and concepts.intersection({"authoritative", "identifier", "master_record", "record"})
        and ("master_record" in concepts or not specific_identifier_context)
    ):
        concepts.add("material_identifier")
    if "material" in concepts and "description" in concepts:
        concepts.add("material_description")
    if "unit" in concepts and "inventory" in concepts:
        concepts.add("inventory_unit")
    if "unit" in concepts and "weight" in concepts:
        concepts.add("weight_unit")
    if "site" in concepts and concepts.intersection({"code", "identifier", "owner"}):
        concepts.add("site_identifier")
    if "revision" in concepts and concepts.intersection(
        {"design", "engineering", "level", "planned"}
    ):
        concepts.add("engineering_revision")
    if "drawing" in concepts and concepts.intersection(
        {"design", "document", "identifier", "reference"}
    ):
        concepts.add("drawing_reference")
    if "batch" in concepts and "tracking" in concepts:
        concepts.add("batch_tracking")
    if "serial" in concepts and concepts.intersection({"control", "identifier", "tracking"}):
        concepts.add("serial_tracking")
    if "weight" in concepts and "net" in concepts:
        concepts.add("net_weight")
    if "weight" in concepts and "gross" in concepts:
        concepts.add("gross_weight")
    if "money" in concepts and concepts.intersection({"planned", "standard", "valuation"}):
        concepts.add("standard_price")
    if "currency" in concepts:
        concepts.add("currency_code")
    if "sourcing" in concepts and concepts.intersection({"mode", "type"}):
        concepts.add("sourcing_mode")
    if "lead_time" in concepts and "days" in concepts:
        concepts.add("lead_time_days")
    numeric_quantity = bool(set(field.types).intersection({JsonType.INTEGER, JsonType.NUMBER}))
    if (
        "buffer_stock" in concepts
        and "inventory" in concepts
        and ("quantity" in concepts or numeric_quantity)
    ):
        concepts.add("safety_stock_quantity")
    if "group" in concepts and concepts.intersection({"commercial", "material", "reporting"}):
        concepts.add("material_group")
    if "planning" in concepts and concepts.intersection(
        {"controller", "person", "responsible", "team"}
    ):
        concepts.add("planning_controller")
    if "barcode" in concepts and "identifier" in concepts:
        concepts.add("barcode_identifier")

    return FieldSemantics(concepts=frozenset(concepts))


def _weight(concept: str) -> float:
    return _CONCEPT_WEIGHTS.get(concept, 1.0)


def semantic_field_similarity(source: SchemaField, target: SchemaField) -> float:
    """Compare typed business concepts without encoding field-pair mappings."""
    source_concepts = field_semantics(source).concepts
    target_concepts = field_semantics(target).concepts
    overlap = source_concepts.intersection(target_concepts)
    if not overlap:
        return 0.0

    overlap_weight = sum(_weight(concept) for concept in overlap)
    source_weight = sum(_weight(concept) for concept in source_concepts)
    target_weight = sum(_weight(concept) for concept in target_concepts)
    precision = overlap_weight / source_weight
    recall = overlap_weight / target_weight
    score = 2.0 * precision * recall / (precision + recall)

    shared_roles = overlap.intersection(_ROLE_CONCEPTS)
    if not shared_roles and overlap.issubset(_SCOPE_CONCEPTS):
        score = min(score, 0.20)

    for group in _EXCLUSIVE_GROUPS:
        source_values = source_concepts.intersection(group)
        target_values = target_concepts.intersection(group)
        if source_values and target_values and source_values != target_values:
            score *= 0.20

    return min(max(score, 0.0), 1.0)


def semantic_fields_conflict(source: SchemaField, target: SchemaField) -> bool:
    """Return whether both fields declare mutually exclusive semantic roles."""
    source_concepts = field_semantics(source).concepts
    target_concepts = field_semantics(target).concepts
    source_roles = source_concepts.intersection(_ROLE_CONCEPTS)
    target_roles = target_concepts.intersection(_ROLE_CONCEPTS)
    if source_roles and target_roles and source_roles.isdisjoint(target_roles):
        return True
    if "legacy" in target_concepts and "legacy" not in source_concepts:
        return True
    for group in _EXCLUSIVE_GROUPS:
        source_values = source_concepts.intersection(group)
        target_values = target_concepts.intersection(group)
        if source_values and target_values and source_values != target_values:
            return True
    return False


def profile_support_for_target(
    source_profile: FieldProfile | None,
    target: SchemaField,
) -> float:
    """Score privacy-safe source observations against a target semantic type."""
    if source_profile is None or source_profile.sample_count == 0:
        return 0.0
    observed = set(source_profile.observed_types).difference({JsonType.NULL})
    target_types = set(target.types).difference({JsonType.NULL})
    if not observed or not observed.intersection(target_types):
        return 0.0

    concepts = field_semantics(target).concepts
    patterns = set(source_profile.pattern_classes)
    if "email" in concepts:
        return 1.0 if "email-like" in patterns else 0.0
    if "date" in concepts:
        return 1.0 if "iso-date" in patterns else 0.0
    if "timestamp" in concepts:
        return 1.0 if "rfc3339-date-time" in patterns else 0.0
    if "currency_code" in concepts:
        return (
            1.0
            if "uppercase-code" in patterns
            and source_profile.minimum_string_length == 3
            and source_profile.maximum_string_length == 3
            else 0.0
        )
    if concepts.intersection({"inventory_unit", "weight_unit"}):
        return (
            0.9
            if "uppercase-code" in patterns
            and source_profile.maximum_string_length is not None
            and source_profile.maximum_string_length <= 5
            else 0.0
        )
    if "description" in concepts:
        return 1.0 if "mixed-text" in patterns else 0.0
    if target_types == {JsonType.BOOLEAN}:
        return 1.0 if observed == {JsonType.BOOLEAN} else 0.0
    if target_types == {JsonType.INTEGER}:
        return 1.0 if observed == {JsonType.INTEGER} else 0.0
    if target_types == {JsonType.NUMBER}:
        return 0.8 if observed.issubset({JsonType.INTEGER, JsonType.NUMBER}) else 0.0
    if concepts.intersection({"code", "identifier"}):
        return 1.0 if patterns.intersection({"integer-string", "uppercase-code", "uuid"}) else 0.0
    if concepts.intersection(
        {
            "barcode_identifier",
            "material_group",
            "material_identifier",
            "planning_controller",
            "site_identifier",
            "sourcing_mode",
        }
    ):
        return 0.75 if patterns.intersection({"lowercase-word", "uppercase-code"}) else 0.0
    return 0.0


__all__ = [
    "FieldSemantics",
    "field_semantics",
    "profile_support_for_target",
    "semantic_field_similarity",
    "semantic_fields_conflict",
]
