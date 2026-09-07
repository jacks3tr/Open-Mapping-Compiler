"""Schema drift reports are conservative and never mutate or reapprove a bundle."""

from __future__ import annotations

import json
from typing import cast

from open_mapping import Compiler
from open_mapping.model.json_types import JsonValue
from tests.support.streamlined import source_schema, target_schema


def test_added_required_target_is_reported_without_invalidating_unchanged_rule() -> None:
    bundle = (
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )
    before = bundle.model_dump_json()
    target = json.loads(target_schema().canonical_source_json)
    target["properties"]["nickname"] = {"type": "string"}
    target["required"].append("nickname")
    report = Compiler(offline=True).analyze_changes(
        bundle, source=source_schema(), target=cast(JsonValue, target)
    )
    assert report.added_required_targets == ("/nickname",)
    assert report.rules[0].status == "unchanged"
    assert not report.static_valid
    assert report.requires_review
    assert bundle.model_dump_json() == before


def test_removed_source_path_requires_review_and_reports_static_failure() -> None:
    bundle = (
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )
    source: JsonValue = {"$id": "source.customer", "type": "object", "properties": {}}
    report = Compiler(offline=True).analyze_changes(bundle, source=source, target=target_schema())
    assert report.removed_source_paths == ("/name",)
    assert report.rules[0].status == "invalid"
    assert report.rules[0].changed_source_paths == ("/name",)
    assert report.requires_review


def test_tighter_target_constraint_is_never_reused_as_unchanged() -> None:
    bundle = (
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )
    target = json.loads(target_schema().canonical_source_json)
    target["properties"]["name"]["maxLength"] = 3
    report = Compiler().analyze_changes(
        bundle, source=source_schema(), target=cast(JsonValue, target)
    )
    assert report.rules[0].status != "unchanged"
    assert report.target_changed


def test_identical_contracts_require_no_new_review() -> None:
    bundle = (
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )
    report = Compiler().analyze_changes(bundle, source=source_schema(), target=target_schema())
    assert not report.requires_review
    assert report.static_valid
    assert report.rules[0].status == "unchanged"
