"""Canonical mapping bundle model contracts."""

from __future__ import annotations


def test_bundle_requires_verified_hash_metadata() -> None:
    from open_mapping.model.bundles import (
        BundleProvenance,
        BundleVerification,
        MappingBundle,
        VerificationLevel,
    )
    from open_mapping.serialization.bundles import create_bundle
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
            verification_report_sha256="a" * 64,
        ),
        provenance=BundleProvenance(),
    )

    assert isinstance(bundle, MappingBundle)
    assert bundle.bundle_version == "0.1"
    assert bundle.verification.mapping_sha256 == bundle.mapping_sha256
    assert bundle.verification.level is VerificationLevel.STATIC
