"""Validate held-out data integrity without running or tuning a matcher on it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from open_mapping.adapters.json_schema import parse_json_schema


def test_holdout_truth_is_frozen_and_structurally_valid() -> None:
    root = Path("benchmarks/holdout-v1")
    content = (root / "cases.json").read_bytes().replace(b"\r\n", b"\n")
    corpus = json.loads(content)
    lock = json.loads((root / "corpus.lock.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(content).hexdigest() == lock["cases_sha256"]
    assert corpus["corpus_version"] == lock["corpus_version"]
    assert len(corpus["cases"]) == lock["case_count"]
    assert len({case["id"] for case in corpus["cases"]}) == lock["case_count"]
    for case in corpus["cases"]:
        Draft202012Validator.check_schema(case["source"])
        Draft202012Validator.check_schema(case["target"])
        source = parse_json_schema(case["source"], schema_id=None, source_uri="holdout")
        target = parse_json_schema(case["target"], schema_id=None, source_uri="holdout")
        source_paths = {field.pointer for field in source.fields}
        target_paths = {field.pointer for field in target.fields}
        for path, expected in case["expected"].items():
            assert path in target_paths
            assert expected["outcome"] in {"mapping", "abstain"}
            assert set(expected["source_paths"]) <= source_paths
            assert bool(expected["source_paths"]) == (expected["outcome"] == "mapping")
        for sample in case["samples"]:
            Draft202012Validator(case["source"]).validate(sample["input"])
            if "expected" in sample:
                Draft202012Validator(case["target"]).validate(sample["expected"])
