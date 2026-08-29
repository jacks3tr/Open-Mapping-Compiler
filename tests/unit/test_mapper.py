"""Prepared public mapper contract."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

import open_mapping.mapper as mapper_module
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.static import require_static_valid


def test_mapper_transforms_many_with_one_prepared_bundle() -> None:
    from open_mapping import Compiler, Mapper
    from tests.support.streamlined import source_schema, target_schema

    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    mapper = Mapper.from_bundle(bundle)

    sources: tuple[JsonValue, ...] = tuple({"name": f"Customer {index}"} for index in range(100))
    assert mapper.transform_many(sources) == sources
    assert tuple(mapper.iter_transform(sources)) == sources


def test_mapper_performs_static_verification_once_for_one_hundred_transforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from open_mapping import Compiler, Mapper
    from tests.support.streamlined import source_schema, target_schema

    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    calls = 0
    original = require_static_valid

    def counted(
        mapping: MappingDocument,
        *,
        source_schema: SchemaDocument,
        target_schema: SchemaDocument,
    ) -> None:
        nonlocal calls
        calls += 1
        original(mapping, source_schema=source_schema, target_schema=target_schema)

    monkeypatch.setattr(mapper_module, "require_static_valid", counted)
    mapper = Mapper.from_bundle(bundle)
    mapper.transform_many(tuple({"name": str(index)} for index in range(100)))

    assert calls == 1


def test_independent_mappers_are_safe_to_use_concurrently() -> None:
    from open_mapping import Compiler, Mapper
    from tests.support.streamlined import source_schema, target_schema

    bundle = (
        Compiler()
        .build(source=source_schema(), target=target_schema(), mapping_id="customer")
        .require_bundle()
    )
    first = Mapper.from_bundle(bundle)
    second = Mapper.from_bundle(bundle)
    payloads: tuple[JsonValue, ...] = tuple({"name": f"Customer {index}"} for index in range(20))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(first.transform_many, payloads)
        second_result = pool.submit(second.transform_many, payloads)

    assert first_result.result() == payloads
    assert second_result.result() == payloads
