# Python SDK

`map_schemas` gives AI models a constrained mapping task and returns a typed, statically verified `SuggestionReport`.

## Map with AI

Pass `model="provider:model-id"` or set `OPEN_MAPPING_MODEL`, then set the matching provider's API key. The model sees sanitized schema context, allowed source paths, allowed operations, and a strict response contract. Raw samples stay local unless explicitly allowed.

```python
from open_mapping import map_schemas

result = map_schemas(source_schema, target_schema, hints=hints, model="openai:<model-id>")
```

For the shortest path, pass a JSON record or a non-empty record array and select explicit inference:

```python
from open_mapping import infer_source_schema, map_schemas

source = {"customerId": "C-1001", "fullName": "Ada Lovelace"}
result = map_schemas(
    source,
    target_schema,
    source_format="json-data",
    hints=hints,
    model="openai:<model-id>",
)
inferred = infer_source_schema(source)
```

The inferred schema is deterministic, remains open to extra object properties, and does not infer enums, formats, ranges, or descriptions from observed values. Properties present in every observed object are required by the inferred record contract; supply more records or an explicit schema when that contract needs to be broader. Empty observed arrays produce a warning because their item shape is unknown.

`source_schema` and `target_schema` can also be file paths, parsed JSON Schema objects, or selected schemas from OpenAPI files.

The returned `SuggestionReport` contains typed proposals, transformations, evidence, alternatives, unresolved fields, issues, and sanitized model-run metadata.

Use `Compiler.build(...)` to produce a verified bundle and `Mapper.from_bundle(...)` to transform records. JSON-data source records become verification samples automatically, and the bundle embeds the inferred schema. Applying a bundle is deterministic and does not call the model.

## Deterministic offline fallback

Omit `model` when a provider is unavailable or the mapping must stay fully offline:

```python
from open_mapping import map_schemas

result = map_schemas(source_schema, target_schema, hints=hints)
mapping_json = result.model_dump_json()
```

The fallback needs no provider credentials or mapping pack and returns the same `SuggestionReport` contract.
