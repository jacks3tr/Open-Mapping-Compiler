"""Sidecar responsiveness and opt-in partial batch results."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from open_mapping import Compiler, Mapper
from open_mapping.model.issues import Issue
from open_mapping.model.json_types import JsonValue
from open_mapping.server.app import create_app
from tests.support.streamlined import source_schema, target_schema


def _mapper() -> Mapper:
    return Mapper.from_bundle(
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )


def test_health_remains_responsive_during_transform(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = _mapper()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked(source: JsonValue, *, diagnostic_values: bool = False) -> JsonValue:
        started.set()
        release.wait(3)
        finished.set()
        return source

    monkeypatch.setattr(mapper, "transform", blocked)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=create_app(mapper))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            transform = asyncio.create_task(
                client.post("/transform", json={"input": {"name": "Ada"}})
            )
            try:
                assert await asyncio.to_thread(started.wait, 3)
                response = await asyncio.wait_for(client.get("/health"), 1)
                assert response.status_code == 200
                assert not finished.is_set(), "transform blocked the event loop until completion"
            finally:
                release.set()
                await transform

    asyncio.run(scenario())


def test_batch_collect_preserves_positions_and_fail_fast_default() -> None:
    with TestClient(create_app(_mapper())) as client:
        inputs = [{"name": "Ada"}, {"name": 3}, {"name": "Grace"}]
        fail_fast = client.post("/transform-batch", json={"inputs": inputs})
        assert fail_fast.status_code == 422
        response = client.post("/transform-batch", json={"inputs": inputs, "on_error": "collect"})
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [result["index"] for result in results] == [0, 1, 2]
        assert [result["success"] for result in results] == [True, False, True]
        assert results[1]["issues"]
        assert results[2]["output"] == {"name": "Grace"}


def test_validate_uses_mapper_prepared_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = _mapper()
    called: list[JsonValue] = []
    original = mapper.validate_source

    def validate(source: JsonValue) -> tuple[Issue, ...]:
        called.append(source)
        return original(source)

    monkeypatch.setattr(mapper, "validate_source", validate)
    with TestClient(create_app(mapper)) as client:
        assert client.post("/validate", json={"input": {"name": "Ada"}}).json()["valid"]
    assert called == [{"name": "Ada"}]
