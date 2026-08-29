"""Canonical mapping bundle serialization contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_mapping.errors import OpenMappingError


def test_bundle_round_trip_is_canonical_and_tamper_evident(tmp_path: Path) -> None:
    from open_mapping.model.bundles import BundleProvenance, BundleVerification, VerificationLevel
    from open_mapping.serialization.bundles import (
        bundle_sha256,
        create_bundle,
        dump_bundle,
        dumps_bundle,
        load_bundle,
        loads_bundle,
    )
    from tests.support.streamlined import identity_mapping, source_schema, target_schema

    bundle = create_bundle(
        mapping=identity_mapping(),
        source_schema=source_schema(),
        target_schema=target_schema(),
        verification=BundleVerification(
            level=VerificationLevel.STATIC,
            valid=True,
            sample_count=0,
            mapping_sha256="",
            verification_report_sha256="b" * 64,
        ),
        provenance=BundleProvenance(),
    )
    first = dumps_bundle(bundle)
    second = dumps_bundle(loads_bundle(first))
    assert first == second
    assert first.endswith("\n") and not first.endswith("\n\n")
    path = tmp_path / "mapping.omc"
    dump_bundle(bundle, path)
    assert load_bundle(path) == bundle
    assert len(bundle_sha256(bundle)) == 64

    tampered = json.loads(first)
    tampered["mapping"]["rules"][0]["target"] = "/changed"
    with pytest.raises(OpenMappingError, match="BUNDLE_HASH_MISMATCH"):
        loads_bundle(json.dumps(tampered))


@pytest.mark.parametrize("content", ['{"a":1,"a":2}', '{"value":NaN}', '{"value":Infinity}'])
def test_bundle_loader_rejects_noncanonical_json(content: str) -> None:
    from open_mapping.serialization.bundles import loads_bundle

    with pytest.raises((OpenMappingError, ValueError)):
        loads_bundle(content)


def test_bundle_loader_uses_precise_errors_for_unverified_and_incompatible_bundles() -> None:
    from open_mapping.model.bundles import BundleProvenance, BundleVerification, VerificationLevel
    from open_mapping.serialization.bundles import create_bundle, dumps_bundle, loads_bundle
    from tests.support.streamlined import identity_mapping, source_schema, target_schema

    bundle = create_bundle(
        mapping=identity_mapping(),
        source_schema=source_schema(),
        target_schema=target_schema(),
        verification=BundleVerification(
            level=VerificationLevel.STATIC,
            valid=True,
            sample_count=0,
            mapping_sha256="",
            verification_report_sha256="b" * 64,
        ),
        provenance=BundleProvenance(),
    )
    unverified = json.loads(dumps_bundle(bundle))
    unverified["verification"]["valid"] = False
    with pytest.raises(OpenMappingError, match="BUNDLE_NOT_VERIFIED"):
        loads_bundle(json.dumps(unverified))

    incompatible = json.loads(dumps_bundle(bundle))
    incompatible["compiler_version"] = "99.0.0"
    with pytest.raises(OpenMappingError, match="UNSUPPORTED_BUNDLE_VERSION"):
        loads_bundle(json.dumps(incompatible))

    invalid_compiler = json.loads(dumps_bundle(bundle))
    invalid_compiler["compiler_version"] = "not-a-version"
    with pytest.raises(OpenMappingError, match="UNSUPPORTED_BUNDLE_VERSION"):
        loads_bundle(json.dumps(invalid_compiler))


def test_bundle_rejects_machine_specific_schema_locations() -> None:
    from open_mapping.model.bundles import BundleProvenance, BundleVerification, VerificationLevel
    from open_mapping.serialization.bundles import create_bundle
    from tests.support.streamlined import identity_mapping, source_schema, target_schema

    source = source_schema()
    source = source.model_copy(
        update={
            "fields": (
                source.fields[0].model_copy(
                    update={"source_location": str(Path.cwd() / "private.schema.json")}
                ),
            )
        }
    )
    with pytest.raises(OpenMappingError, match="machine-specific"):
        create_bundle(
            mapping=identity_mapping(),
            source_schema=source,
            target_schema=target_schema(),
            verification=BundleVerification(
                level=VerificationLevel.STATIC,
                valid=True,
                sample_count=0,
                mapping_sha256="",
                verification_report_sha256="b" * 64,
            ),
            provenance=BundleProvenance(),
        )
