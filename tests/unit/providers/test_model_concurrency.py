"""Bounded parallel inference preserves response order and transport isolation."""

from __future__ import annotations

import json
import threading
from typing import cast

from tests.unit.providers.test_model_orchestrator import (
    _package,
    _resolved_model,
    _response_payload,
    _result,
)

from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ProviderKind, ResolvedModel
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.protocol import ModelTransportRequest, ModelTransportResult


def test_parallel_batches_use_independent_transports_and_keep_order() -> None:
    barrier = threading.Barrier(2, timeout=3)
    lock = threading.Lock()
    packages = tuple(_package(f"batch-{index}") for index in range(4))
    by_id = {package.batch_id: package for package in packages}
    transports: list[Transport] = []
    active = 0
    peak = 0

    class Transport:
        calls = 0

        def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
            nonlocal active, peak
            self.calls += 1
            assert self.calls == 1, "each parallel batch needs its own transport instance"
            package = by_id[json.loads(request.prompt.user_payload_json)["batch_id"]]
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait()
                return _result(cast(JsonValue, _response_payload(package)))
            finally:
                with lock:
                    active -= 1

    def factory(model: ResolvedModel) -> Transport:
        transport = Transport()
        with lock:
            transports.append(transport)
        return transport

    responses, disclosure, issues = invoke_model_mapping(
        packages=tuple(reversed(packages)),
        resolved_model=_resolved_model(),
        config_sha256="c" * 64,
        registry={ProviderKind.OPENAI_COMPATIBLE: factory},
        max_concurrency=2,
    )
    assert issues == ()
    assert peak == 2
    assert len(transports) == 4
    assert [response.batch_id for response in responses] == [
        package.batch_id for package in packages
    ]
    assert [run.batch_id for run in disclosure.batch_runs] == [
        package.batch_id for package in packages
    ]
