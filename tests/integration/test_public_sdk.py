"""Stable application-facing package exports."""

from __future__ import annotations


def test_public_sdk_exports_only_the_stable_surface() -> None:
    import open_mapping

    assert open_mapping.__all__ == [
        "Compiler",
        "BuildDraft",
        "BuildResult",
        "BuildStatus",
        "MappingBundle",
        "Mapper",
        "TransformResult",
        "SchemaChangeReport",
        "analyze_schema_changes",
        "VerificationLevel",
        "OpenMappingError",
        "map_schemas",
        "infer_source_schema",
        "__version__",
    ]
