# Quick start

## Install

Install from PyPI:

```text
python -m pip install open-mapping
```

## Map with AI

Set `OPEN_MAPPING_MODEL` to `openai:<model-id>`, `anthropic:<model-id>`, or `google:<model-id>`, then set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` for that provider. The package runs in your process and calls the provider directly. You can instead pass `--model provider:model-id` to select a model per command.

Get a structured first pass from a JSON record:

```text
open-mapping map input.json target.schema.json --source-format json-data --hints hints.yaml --require-model --out mapping.json
```

The compiler gives the model sanitized schema context, constrains its response to valid source paths and operations, and statically verifies every proposal. The result contains one outcome for every target field and can be reviewed or consumed by another application. Raw samples stay local unless explicitly allowed.

Build and run an executable mapping:

```text
open-mapping build input.json target.schema.json --source-format json-data --hints hints.yaml --model openai:<model-id> --require-model --out mapping.omc
open-mapping apply mapping.omc --input input.json
```

The source record is automatically used for sample verification, and the bundle retains the inferred schema. Applying the verified bundle is deterministic and does not call the model. The repository's [quick-start files](../examples/quick-start/) exercise the same input and bundle flow. To supply an authoritative source contract, use `source.schema.json` and omit `--source-format json-data`.

## Deterministic offline fallback

Omit `--model` and leave `OPEN_MAPPING_MODEL` unset when a provider is unavailable or the mapping must stay fully offline. No provider, API key, or mapping pack is required. The fallback returns the same typed result, uses schema and privacy-safe value evidence, and leaves uncertain fields for review.
