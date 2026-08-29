# Quick start

## Add a model

Set `OPEN_MAPPING_MODEL` to `openai:<model-id>`, `anthropic:<model-id>`, or `google:<model-id>`, then set that provider's API key. You can instead pass `--model provider:model-id` to a mapping command. Model assistance returns the same typed result as local mapping, and raw samples stay local unless explicitly allowed.

## Local

Install from the public repository. No provider, API key, or mapping pack is required for deterministic local suggestions.

```text
python -m pip install "open-mapping @ https://github.com/jacks3tr/Open-Mapping-Compiler/archive/refs/heads/main.zip"
```

Get a structured first pass directly from a JSON record:

```text
open-mapping map input.json target.schema.json --source-format json-data --hints hints.yaml --out mapping.json
```

The result contains one outcome for every target field and can be reviewed or consumed by another application. `SOURCE_SCHEMA_INFERRED` diagnostics identify the inferred contract. A non-empty JSON array is treated as multiple records, not as one array-valued record.

Build and run an executable mapping:

```text
open-mapping build input.json target.schema.json --source-format json-data --hints hints.yaml --out mapping.omc
open-mapping apply mapping.omc --input input.json
```

The source record is automatically used for sample verification, and the bundle retains the inferred schema. The repository's [quick-start files](../examples/quick-start/) exercise this exact flow. To supply an authoritative source contract, use `source.schema.json` and omit `--source-format json-data`.
