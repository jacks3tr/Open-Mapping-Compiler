"""Hostile and accidental mapping bundle mutation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_mapping import Compiler, Mapper, OpenMappingError
from open_mapping.serialization.bundles import dumps_bundle, loads_bundle
from open_mapping.verification.dynamic import VerificationSample
from tests.support.streamlined import source_schema, target_schema


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("mapping", "id", "forged"),
        ("source_schema", "schema_id", "forged"),
        ("target_schema", "schema_id", "forged"),
    ],
)
def test_bundle_rejects_tampering(section: str, field: str, value: str) -> None:
    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    payload = json.loads(dumps_bundle(bundle))
    payload[section][field] = value

    with pytest.raises(OpenMappingError, match="BUNDLE_HASH_MISMATCH"):
        loads_bundle(json.dumps(payload))


def test_mapper_load_rejects_tampered_bundle(tmp_path: Path) -> None:
    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    payload = json.loads(dumps_bundle(bundle))
    payload["mapping_sha256"] = "0" * 64
    path = tmp_path / "tampered.omc"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OpenMappingError, match="BUNDLE_HASH_MISMATCH"):
        Mapper.load(path)


def test_bundle_contains_no_samples_or_secret_values() -> None:
    secret = "sk-test-value-that-must-not-ship"
    bundle = (
        Compiler()
        .build(
            source=source_schema(),
            target=target_schema(),
            samples=(VerificationSample(id="one", input={"name": secret}),),
            mapping_id="customer",
        )
        .require_bundle()
    )
    serialized = dumps_bundle(bundle)
    payload = json.loads(serialized)

    assert secret not in serialized
    assert "samples" not in payload
    assert "expected" not in payload
