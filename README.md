# Open Mapping Compiler

## What it is

Open Mapping Compiler turns source JSON data or a source contract and a target contract into a reviewable mapping. Give it a JSON record, JSON Schemas, or selected schemas from OpenAPI documents. Optional samples, hints, and context improve the first pass without changing the output contract.

## Add a model

Set `OPEN_MAPPING_MODEL` to a provider-neutral selection such as `openai:<model-id>`, `anthropic:<model-id>`, or `google:<model-id>`, then set that provider's API key. The same `map_schemas` function and `open-mapping map` command return the same typed result. Model proposals are constrained, statically verified, and reviewable; raw samples stay local unless explicitly allowed.

Custom or local endpoints can use an [advanced provider configuration](docs/model-assisted-mapping.md). A runnable provider example is in [`examples/model-assisted`](examples/model-assisted/README.md).

## Local

It returns deterministic suggestions locally and can build a verified `.omc` bundle that transforms JSON in Python, a shell pipeline, or a sidecar. It does not call source or target business APIs.

## Install

```text
python -m pip install "open-mapping @ https://github.com/jacks3tr/Open-Mapping-Compiler/archive/refs/heads/main.zip"
```

## Map source data

```text
open-mapping map input.json target.schema.json --source-format json-data --out mapping.json
```

No API key, source schema, provider, or mapping pack is required. `mapping.json` contains one outcome for every target field, including proposed source paths, transformations, confidence, alternatives, and machine-readable inference diagnostics. Pass a single record object or a non-empty array of record objects. The records stay local unless model use and raw-sample disclosure are both explicitly enabled.

Python applications use the same contract:

```python
from open_mapping import map_schemas

result = map_schemas(source_record, target_schema, source_format="json-data", hints=hints)
```

## Build executable output

```text
open-mapping build input.json target.schema.json --source-format json-data --hints hints.yaml --out mapping.omc
open-mapping apply mapping.omc --input input.json
```

The source records become verification samples automatically, and the inferred schema is embedded in the bundle for inspection. Unambiguous mappings build immediately. When judgment is required, `build` emits a hash-bound review file and exits with code 8; complete it and rerun the printed command. Schema-first use remains available by omitting `--source-format json-data`. See the [working quick start](docs/quick-start.md), [Python SDK](docs/sdk.md), and [workflow integration guide](docs/workflow-integration.md).

The project is licensed under [Apache License 2.0](LICENSE).
