"""Run the public three-command example against installed entry points."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.integration.cli.conftest import ROOT


def test_documented_build_apply_and_sdk_workflow(tmp_path: Path) -> None:
    bundle = tmp_path / "customer.omc"
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "open_mapping.cli.app",
            "build",
            str(ROOT / "examples/quick-start/input.json"),
            str(ROOT / "examples/quick-start/target.schema.json"),
            "--source-format",
            "json-data",
            "--hints",
            str(ROOT / "examples/quick-start/hints.yaml"),
            "--work-dir",
            str(tmp_path / "audit"),
            "--out",
            str(bundle),
        ],
        cwd=tmp_path,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    applied = subprocess.run(
        [
            sys.executable,
            "-m",
            "open_mapping.cli.app",
            "apply",
            str(bundle),
            "--input",
            str(ROOT / "examples/quick-start/input.json"),
        ],
        cwd=tmp_path,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert build.returncode == 0, build.stderr
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout) == {
        "accountName": "Ada Lovelace",
        "customerId": "C-1001",
    }
    assert applied.stderr == ""

    sdk = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from open_mapping import Mapper; "
                f"mapper=Mapper.load(r'{bundle}'); "
                "print(mapper.transform({'customerId':'C-1001','fullName':'Ada Lovelace'}))"
            ),
        ],
        cwd=tmp_path,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert sdk.returncode == 0, sdk.stderr
    assert "Ada Lovelace" in sdk.stdout


def test_documented_jsonl_pipeline_streams_two_records(tmp_path: Path) -> None:
    bundle = tmp_path / "customer.omc"
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "open_mapping.cli.app",
            "build",
            str(ROOT / "examples/quick-start/input.json"),
            str(ROOT / "examples/quick-start/target.schema.json"),
            "--source-format",
            "json-data",
            "--hints",
            str(ROOT / "examples/quick-start/hints.yaml"),
            "--work-dir",
            str(tmp_path / "audit"),
            "--out",
            str(bundle),
        ],
        cwd=tmp_path,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    pipeline_input = (ROOT / "examples/pipeline/input.jsonl").read_text(encoding="utf-8")
    applied = subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", "apply", str(bundle), "--jsonl"],
        cwd=tmp_path,
        env=os.environ,
        input=pipeline_input,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert applied.returncode == 0, applied.stderr
    assert [json.loads(line) for line in applied.stdout.splitlines()] == [
        {"accountName": "Ada Lovelace", "customerId": "C-1001"},
        {"accountName": "Grace Hopper", "customerId": "C-1002"},
    ]
