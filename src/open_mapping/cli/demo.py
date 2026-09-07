"""Installed, offline first success using package resources rather than the checkout."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import typer

from open_mapping.cli.common import preflight_outputs, write_outputs
from open_mapping.compiler import Compiler
from open_mapping.mapper import Mapper
from open_mapping.serialization.bundles import dumps_bundle
from open_mapping.verification.dynamic import VerificationSample


def demo_command(*, out_dir: Path | None = None, force: bool = False) -> int:
    example = json.loads(files("open_mapping").joinpath("demo.json").read_text(encoding="utf-8"))
    sample = VerificationSample(id="demo", input=example["input"], expected=example["expected"])
    exports: dict[Path, str] = {}
    if out_dir is not None:
        for filename, key in (
            ("source.json", "source_schema"),
            ("target.json", "target_schema"),
            ("input.json", "input"),
            ("expected.json", "expected"),
        ):
            exports[out_dir / filename] = json.dumps(example[key], indent=2) + "\n"
        exports[out_dir / "samples.jsonl"] = sample.model_dump_json() + "\n"
        preflight_outputs((*exports, out_dir / "mapping.omc"), force=force)
    result = Compiler(offline=True).build(
        source=example["source_schema"],
        target=example["target_schema"],
        mapping_id="customer-demo",
        samples=(sample,),
        require_samples=True,
    )
    bundle = result.require_bundle()
    output = Mapper.from_bundle(bundle).transform(example["input"])
    if out_dir is not None:
        exports[out_dir / "mapping.omc"] = dumps_bundle(bundle)
        write_outputs(exports, force=force)
    typer.echo(
        json.dumps(
            {
                "status": result.status.value,
                "source_schema": example["source_schema"],
                "target_schema": example["target_schema"],
                "input": example["input"],
                "output": output,
                "expected": example["expected"],
                "verification": bundle.verification.model_dump(mode="json"),
                "model_used": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0
