# Open Mapping Compiler

## What it is

Open Mapping Compiler uses AI (bring your own keys) to turn source JSON data or a source contract and a target contract into a reviewable, typed mapping. Give it a JSON record, JSON Schemas, or selected schemas from OpenAPI documents. It compares field names, descriptions, types, formats, constraints, examples, and optional context to produce a strong first pass even when two systems use different language.

## Start with AI

Install the package from PyPI:

```text
python -m pip install open-mapping
```

Choose any supported provider and model. Your key stays in your process environment; Open Mapping Compiler calls the provider directly and does not require an Open Mapping account or proxy.

| Model selection | API key environment variable |
| --- | --- |
| `openai:<model-id>` | `OPENAI_API_KEY` |
| `anthropic:<model-id>` | `ANTHROPIC_API_KEY` |
| `google:<model-id>` | `GOOGLE_API_KEY` |

For example, in PowerShell:

```powershell
$env:OPEN_MAPPING_MODEL = "openai:<model-id>"
$env:OPENAI_API_KEY = "<your-api-key>"
```

On macOS or Linux, use `export OPEN_MAPPING_MODEL="openai:<model-id>"` and `export OPENAI_API_KEY="<your-api-key>"`. Custom or local endpoints can use an [advanced provider configuration](docs/model-assisted-mapping.md). A runnable provider example is in [`examples/model-assisted`](examples/model-assisted/README.md).

## Map source data

```text
open-mapping map input.json target.schema.json --source-format json-data --require-model --out mapping.json
```

`mapping.json` contains one outcome for every target field, including proposed source paths, transformations, confidence, alternatives, and machine-readable inference diagnostics. Pass a single record object or a non-empty array of record objects. Add optional hints and context when the schemas alone do not capture the business meaning. Raw samples stay local unless you explicitly allow them.

Python applications use the same contract:

```python
from open_mapping import map_schemas

result = map_schemas(
    source_record,
    target_schema,
    source_format="json-data",
    hints=hints,
    require_model=True,
)
```

Pass `model="provider:model-id"` or `--model provider:model-id` to select a model per call instead of using `OPEN_MAPPING_MODEL`. The compiler gives the model sanitized schema context and a strict response contract, then constrains and statically verifies every proposal.

## Use it in your software

Compile once when a connector is configured or either schema changes: source data or contract + target contract + optional context → AI proposal → review when needed → verified `.omc` bundle. At runtime, load that bundle once and transform as many records as needed without another model call:

```python
from open_mapping import Mapper

mapper = Mapper.load("mapping.omc")
target_record = mapper.transform(source_record)
```

Use `open-mapping apply` in a shell pipeline or install `open-mapping[server]` for an HTTP sidecar. Your integration remains responsible for reading and writing business APIs, credentials, retries, idempotency, and dead-letter handling.

## Deterministic offline fallback

The deterministic offline fallback is available when a provider is unavailable or data must stay fully offline. Omit `--model` or the SDK's `model` argument and leave `OPEN_MAPPING_MODEL` unset. It requires no API key or mapping pack and returns the same typed result. It combines types, constraints, common software abbreviations, typed business concepts, schema context, and privacy-safe value profiles, while leaving uncertain decisions for review.

## Build executable output

```text
open-mapping build input.json target.schema.json --source-format json-data --hints hints.yaml --model openai:<model-id> --require-model --out mapping.omc
open-mapping apply mapping.omc --input input.json
```

The source records become verification samples automatically, and the inferred schema is embedded in the bundle for inspection. Unambiguous mappings build immediately. When judgment is required, `build` emits a hash-bound review file and exits with code 8; complete it and rerun the printed command. The resulting `.omc` bundle transforms JSON deterministically in Python, a shell pipeline, or a sidecar without calling a model at runtime. See the [working quick start](docs/quick-start.md), [Python SDK](docs/sdk.md), and [workflow integration guide](docs/workflow-integration.md).

## Tested across seven industries

In a blind Luna Max evaluation, the model used our structured schema context and strict response contract to score 100% accuracy across 7 mappings across different industries. It did not receive expected mappings, ambiguity or no-match labels, reviews, results, provenance, or raw samples. The offline deterministic fallback scored 45.7% across the same tests.

| Measure | Result |
| --- | ---: |
| Direct mapping precision | 63/63 (100%) |
| Direct mapping recall | 63/63 (100%) |
| Ambiguities left for review | 7/7 (100%) |
| Missing source fields left unmapped | 35/35 (100%) |
| Target decisions returned | 105/105 (100%) |
| Static-valid direct proposals | 63/63 (100%) |
| Complete industry cases | 7/7 (100%) |

The [blind multi-industry corpus](benchmarks/blind-multi-industry-v1/README.md) contains all 105 independently frozen target decisions across healthcare, payments, retail supply chain, observability, geospatial data, energy utilities, and air cargo.

The project is licensed under [Apache License 2.0](LICENSE).
