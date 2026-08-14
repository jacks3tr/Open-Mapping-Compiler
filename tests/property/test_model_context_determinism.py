"""Property checks for model-context input-order independence."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.hints import DirectHint, MappingHints
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import Evidence, EvidenceKind
from open_mapping.model.model_config import ContextMode
from open_mapping.model.model_protocol import MappingContextPackage
from open_mapping.model.schema import JsonType, SchemaDocument, SchemaField
from open_mapping.model.suggestions import MatchCandidate, TargetCandidateSet
from open_mapping.providers.context import ContextPackingOptions, build_mapping_context_batches
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _package_bytes(packages: tuple[MappingContextPackage, ...]) -> bytes:
    payload = [package.model_dump(mode="json") for package in packages]
    return canonical_json_bytes(cast(JsonValue, payload))


def test_public_package_serialization_is_stable_across_fresh_processes() -> None:
    script = textwrap.dedent(
        """
        import sys

        from open_mapping.matching.profiles import FieldProfile
        from open_mapping.model.model_config import ContextMode
        from open_mapping.model.model_protocol import MappingContextPackage
        from open_mapping.model.schema import JsonType
        from open_mapping.serialization.canonical_json import canonical_json_bytes

        observed_types = frozenset(JsonType(value) for value in sys.argv[1].split(","))
        package = MappingContextPackage(
            protocol_version="0.1",
            prompt_version="mapping-agent-v1",
            batch_id="batch-0001-determinism",
            context_mode=ContextMode.TARGETED,
            source_schema_id="source",
            source_schema_version="1",
            target_schema_id="target",
            target_schema_version="1",
            source_fields=(),
            target_requests=(),
            sample_profiles=(
                FieldProfile(
                    pointer="/value",
                    observed_types=observed_types,
                    sample_count=1,
                    missing_count=0,
                    null_count=0,
                    distinct_count=1,
                ),
            ),
            business_instructions=(),
            expression_operations=(),
            allowed_source_paths=(),
            raw_samples=None,
        )
        print(package.model_dump_json())
        print(canonical_json_bytes(package.model_dump(mode="json")).decode("utf-8"))
        """
    )
    forward = "null,boolean,integer,number,string,array,object"
    reverse = "object,array,string,number,integer,boolean,null"
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script, order],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed, order in (("1", forward), ("2", reverse), ("3", forward), ("4", reverse))
    }

    assert len(outputs) == 1


@pytest.mark.property
@given(
    source_order=st.permutations((0, 1, 2, 3)),
    target_order=st.permutations((0, 1)),
    candidate_set_order=st.permutations((0, 1)),
    candidate_order=st.permutations((0, 1)),
    profile_order=st.permutations((0, 1)),
    hint_order=st.permutations((0, 1)),
)
def test_shuffled_schema_candidates_profiles_and_hints_are_byte_identical(
    source_order: list[int],
    target_order: list[int],
    candidate_set_order: list[int],
    candidate_order: list[int],
    profile_order: list[int],
    hint_order: list[int],
) -> None:
    source_fields = (
        SchemaField(pointer="/account", types=frozenset({JsonType.OBJECT}), required=True),
        SchemaField(pointer="/account/id", types=frozenset({JsonType.STRING}), required=True),
        SchemaField(pointer="/account/name", types=frozenset({JsonType.STRING}), required=True),
        SchemaField(pointer="/fallback", types=frozenset({JsonType.STRING}), required=False),
    )
    target_fields = (
        SchemaField(pointer="/id", types=frozenset({JsonType.STRING}), required=True),
        SchemaField(pointer="/name", types=frozenset({JsonType.STRING}), required=True),
    )
    source = SchemaDocument(
        schema_id="source",
        schema_version="1",
        dialect="draft",
        root_types=frozenset({JsonType.OBJECT}),
        fields=tuple(source_fields[index] for index in source_order),
        canonical_source_json="{}",
    )
    target = SchemaDocument(
        schema_id="target",
        schema_version="1",
        dialect="draft",
        root_types=frozenset({JsonType.OBJECT}),
        fields=tuple(target_fields[index] for index in target_order),
        canonical_source_json="{}",
    )
    candidates_by_target = (
        TargetCandidateSet(
            target_path="/id",
            candidates=tuple(
                (
                    MatchCandidate(
                        source_path="/account/id",
                        target_path="/id",
                        raw_score=0.9,
                        evidence=(Evidence(kind=EvidenceKind.EXACT_NAME, detail="ID matches."),),
                    ),
                    MatchCandidate(
                        source_path="/fallback",
                        target_path="/id",
                        raw_score=0.4,
                    ),
                )[index]
                for index in candidate_order
            ),
        ),
        TargetCandidateSet(
            target_path="/name",
            candidates=(
                MatchCandidate(
                    source_path="/account/name",
                    target_path="/name",
                    raw_score=0.95,
                ),
            ),
        ),
    )
    profiles = (
        FieldProfile(
            pointer="/account/id",
            observed_types=frozenset({JsonType.STRING}),
            sample_count=2,
            missing_count=0,
            null_count=0,
            distinct_count=2,
        ),
        FieldProfile(
            pointer="/account/name",
            observed_types=frozenset({JsonType.STRING}),
            sample_count=2,
            missing_count=0,
            null_count=0,
            distinct_count=2,
        ),
    )
    direct_hints = (
        DirectHint(target="/id", source="/account/id", reason="Use account ID."),
        DirectHint(target="/name", source="/account/name", reason="Use account name."),
    )
    hints = MappingHints(
        hints_version="0.1",
        id="stable",
        direct=tuple(direct_hints[index] for index in hint_order),
    )

    observed = build_mapping_context_batches(
        source_schema=source,
        target_schema=target,
        candidate_sets=tuple(candidates_by_target[index] for index in candidate_set_order),
        source_profiles=tuple(profiles[index] for index in profile_order),
        hints=hints,
        instruction="Use business identifiers.",
        raw_samples=(),
        options=ContextPackingOptions(
            mode=ContextMode.TARGETED,
            input_token_budget=100_000,
            target_batch_size=2,
            candidate_limit_per_target=2,
            include_raw_samples=False,
        ),
    )
    canonical = build_mapping_context_batches(
        source_schema=source.model_copy(update={"fields": source_fields}),
        target_schema=target.model_copy(update={"fields": target_fields}),
        candidate_sets=candidates_by_target,
        source_profiles=profiles,
        hints=MappingHints(hints_version="0.1", id="stable", direct=direct_hints),
        instruction="Use business identifiers.",
        raw_samples=(),
        options=ContextPackingOptions(
            mode=ContextMode.TARGETED,
            input_token_budget=100_000,
            target_batch_size=2,
            candidate_limit_per_target=2,
            include_raw_samples=False,
        ),
    )

    assert _package_bytes(observed) == _package_bytes(canonical)
