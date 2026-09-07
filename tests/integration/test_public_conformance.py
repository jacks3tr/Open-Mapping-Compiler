"""Published conformance fixtures are executable contracts for embedding adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_mapping import Compiler, Mapper, OpenMappingError
from open_mapping.serialization.bundles import dumps_bundle, loads_bundle
from open_mapping.server.app import create_app


def test_published_identity_contract_matches_sdk_and_sidecar() -> None:
    fixture = json.loads(Path("examples/conformance/identity.json").read_text(encoding="utf-8"))
    bundle = (
        Compiler(offline=True)
        .build(source=fixture["schema"], target=fixture["schema"], mapping_id="conformance")
        .require_bundle()
    )
    mapper = Mapper.from_bundle(loads_bundle(dumps_bundle(bundle)))
    with TestClient(create_app(mapper)) as client:
        for case in fixture["cases"]:
            response = client.post("/transform", json={"input": case["input"]})
            if "issue_code" in case:
                with pytest.raises(OpenMappingError) as error:
                    mapper.transform(case["input"])
                assert any(issue.code.value == case["issue_code"] for issue in error.value.issues)
                assert response.status_code == 422, case["id"]
                assert any(
                    issue["code"] == case["issue_code"] for issue in response.json()["issues"]
                )
            else:
                assert mapper.transform(case["input"]) == case["output"], case["id"]
                assert response.status_code == 200, case["id"]
                assert response.json()["output"] == case["output"], case["id"]
