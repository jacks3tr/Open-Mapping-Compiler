"""Complete benchmark pack loading and pre-run validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from open_mapping.adapters.json_schema import load_json_schema
from open_mapping.matching.candidates import iter_target_mapping_units
from open_mapping.model.benchmarks import BenchmarkManifest, BenchmarkMetrics, BenchmarkSample
from open_mapping.model.hints import MappingHints
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.pointers import split_pointer
from open_mapping.serialization.hints import load_mapping_hints
from open_mapping.serialization.mappings import load_mapping
from open_mapping.serialization.reviews import load_suggestion_review
from open_mapping.serialization.yaml_loader import load_safe_yaml
from open_mapping.verification.static import verify_static


@dataclass(frozen=True)
class BenchmarkPack:
    directory: Path
    manifest: BenchmarkManifest
    source_schema: SchemaDocument
    target_schema: SchemaDocument
    samples: tuple[BenchmarkSample, ...]
    expected_mapping: MappingDocument
    hints: MappingHints | None
    review: SuggestionReviewDocument
    target_units: tuple[str, ...]


def load_benchmark_manifest(path: Path) -> BenchmarkManifest:
    content = path.read_text(encoding="utf-8")
    raw = json.loads(content) if path.suffix.lower() == ".json" else load_safe_yaml(content)
    return BenchmarkManifest.model_validate(raw)


def _asset(pack_dir: Path, relative: str | None, label: str) -> Path:
    if not relative:
        raise ValueError(f"benchmark manifest requires {label}")
    path = (pack_dir / relative).resolve()
    if not path.is_relative_to(pack_dir.resolve()):
        raise ValueError(f"benchmark {label} must remain inside the pack")
    if not path.is_file():
        raise ValueError(f"benchmark {label} does not exist: {relative}")
    return path


def _load_samples(path: Path) -> tuple[BenchmarkSample, ...]:
    samples: list[BenchmarkSample] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            samples.append(BenchmarkSample.model_validate(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid benchmark sample at line {line_number}: {exc}") from exc
    if not samples:
        raise ValueError("benchmark samples must not be empty")
    ids = [sample.id for sample in samples]
    duplicate_ids = sorted({sample_id for sample_id in ids if ids.count(sample_id) > 1})
    if duplicate_ids:
        raise ValueError(f"duplicate sample ID: {duplicate_ids[0]}")
    return tuple(samples)


def load_benchmark_pack(path: Path) -> BenchmarkPack:
    pack_dir = path.resolve()
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.is_file():
        manifest_path = pack_dir / "manifest.json"
    manifest = load_benchmark_manifest(manifest_path)
    source_schema = load_json_schema(
        _asset(pack_dir, manifest.source_schema, "source_schema"), schema_id=None
    )
    target_schema = load_json_schema(
        _asset(pack_dir, manifest.target_schema, "target_schema"), schema_id=None
    )
    samples = _load_samples(_asset(pack_dir, manifest.samples, "samples"))
    expected_mapping = load_mapping(_asset(pack_dir, manifest.expected_mapping, "expected_mapping"))
    hints = (
        load_mapping_hints(_asset(pack_dir, manifest.hints, "hints")) if manifest.hints else None
    )
    review = load_suggestion_review(_asset(pack_dir, manifest.review, "review"))
    target_units = tuple(field.pointer for field in iter_target_mapping_units(target_schema))
    target_set = set(target_units)
    expected_targets = [rule.target for rule in expected_mapping.rules]
    duplicates = sorted(
        {target for target in expected_targets if expected_targets.count(target) > 1}
    )
    if duplicates:
        raise ValueError(f"expected mapping contains duplicate target: {duplicates[0]}")
    unknown_ground_truth = sorted(set(expected_targets).difference(target_set), key=split_pointer)
    if unknown_ground_truth:
        raise ValueError(
            f"expected mapping target is not a mapping unit: {unknown_ground_truth[0]}"
        )
    ambiguous = set(manifest.expected_ambiguous_targets)
    no_match = set(manifest.expected_no_match_targets)
    if len(ambiguous) != len(manifest.expected_ambiguous_targets):
        raise ValueError("manifest contains duplicate expected ambiguous targets")
    if len(no_match) != len(manifest.expected_no_match_targets):
        raise ValueError("manifest contains duplicate expected no-match targets")
    if ambiguous.intersection(no_match):
        raise ValueError("a target cannot be both expected ambiguous and expected no-match")
    unknown_labels = sorted((ambiguous | no_match).difference(target_set), key=split_pointer)
    if unknown_labels:
        raise ValueError(f"manifest outcome label is not a mapping unit: {unknown_labels[0]}")
    if no_match.intersection(expected_targets):
        raise ValueError("a no-match target cannot have a ground-truth mapping rule")
    if not ambiguous.issubset(expected_targets):
        raise ValueError("every ambiguous target requires a ground-truth mapping rule")
    reconciled = set(expected_targets) | no_match
    if reconciled != target_set:
        missing = sorted(target_set.difference(reconciled), key=split_pointer)
        extra = sorted(reconciled.difference(target_set), key=split_pointer)
        raise ValueError(
            f"manifest target counts do not reconcile: missing={missing}, extra={extra}"
        )
    if expected_mapping.source_schema != source_schema.schema_id:
        raise ValueError("ground-truth source schema ID does not match source schema")
    if expected_mapping.target_schema != target_schema.schema_id:
        raise ValueError("ground-truth target schema ID does not match target schema")
    invariant_ids = [invariant.id for invariant in expected_mapping.invariants]
    if len(invariant_ids) != len(set(invariant_ids)):
        raise ValueError("ground-truth mapping contains duplicate invariant IDs")
    static = verify_static(
        expected_mapping, source_schema=source_schema, target_schema=target_schema
    )
    if not static.valid:
        raise ValueError(
            "ground-truth mapping is static-invalid: "
            + "; ".join(issue.message for issue in static.issues[:3])
        )
    if review.mapping_id != expected_mapping.id:
        raise ValueError("review mapping ID does not match the ground-truth mapping")
    review_targets = [decision.target_path for decision in review.decisions]
    if len(review_targets) != len(set(review_targets)):
        raise ValueError("review contains duplicate declared targets")
    unknown_review = sorted(set(review_targets).difference(target_set), key=split_pointer)
    if unknown_review:
        raise ValueError(f"review target is not a mapping unit: {unknown_review[0]}")
    if hints is not None:
        hint_targets = [hint.target for hint in hints.direct]
        hint_targets.extend(hint.target for hint in hints.lookups)
        hint_targets.extend(hint.target for hint in hints.unit_conversions)
        hint_targets.extend(hint.target for hint in hints.dates)
        hint_targets.extend(hint.target for hint in hints.constants)
        hint_targets.extend(hint.target for hint in hints.expressions)
        if len(hint_targets) != len(set(hint_targets)):
            raise ValueError("hints contain duplicate declared targets")
        unknown_hints = sorted(set(hint_targets).difference(target_set), key=split_pointer)
        if unknown_hints:
            raise ValueError(f"hint target is not a mapping unit: {unknown_hints[0]}")
    unknown_gates = sorted(set(manifest.release_gates).difference(BenchmarkMetrics.model_fields))
    if unknown_gates:
        raise ValueError(f"manifest has unknown gate metric: {unknown_gates[0]}")
    return BenchmarkPack(
        directory=pack_dir,
        manifest=manifest,
        source_schema=source_schema,
        target_schema=target_schema,
        samples=samples,
        expected_mapping=expected_mapping,
        hints=hints,
        review=review,
        target_units=target_units,
    )


def find_benchmark_packs(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root.parent,) if root.name in {"manifest.yaml", "manifest.json"} else ()
    manifests = [*root.rglob("manifest.yaml"), *root.rglob("manifest.json")]
    return tuple(
        sorted(
            {path.parent for path in manifests if path.parent.is_dir()},
            key=lambda item: str(item.relative_to(root)),
        )
    )
