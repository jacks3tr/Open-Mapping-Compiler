# Advanced usage

Start with the `map` command in [README.md](README.md). This guide covers the lower-level workflow for teams that need direct control over local suggestions, review documents, raw mappings, and generated code.

## Inspect a schema

```text
open-mapping inspect source.schema.json
```

OpenAPI 3.1 and 3.2 inputs need a selector such as `component:Customer`, `request:createCustomer`, or `response:getCustomer:200`.

## Generate suggestions

```text
open-mapping suggest source.schema.json target.schema.json --suggestions-out suggestions.json
```

Add `--samples samples.jsonl` for sample profiles or `--hints hints.yaml` for business rules. The report assigns one disposition to each target field: `suggested`, `review_required`, `ambiguous`, `no_match`, or `manual`.

## Review and create a raw mapping

```text
open-mapping review suggestions.json --decisions review.yaml --source source.schema.json --target target.schema.json --out mapping.yaml --require-complete-review
```

Use `--interactive` only in a terminal. Automation should edit the normal YAML review document and keep the hash binding intact.

## Verify, run, and compile

```text
open-mapping verify mapping.yaml --source source.schema.json --target target.schema.json --samples samples.jsonl
open-mapping run mapping.yaml --source-schema source.schema.json --target-schema target.schema.json --input input.json --out output.json
open-mapping compile mapping.yaml --source source.schema.json --target target.schema.json --target-language python --out generated_mapping.py
```

TypeScript code generation uses `--target-language typescript`.

## Hints

Hints record business decisions that names and types cannot prove. Supported hint forms include direct field selection, constants, lookup tables, date formatting, unit conversion, and typed expressions. Keep reasons specific enough for another reviewer to understand why the rule exists.

## Common errors

- `SOURCE_SCHEMA_INFERRED`: inspect the inferred schema in the bundle or provide an explicit source schema when the observed records are not representative.
- `REQUIRED_TARGET_UNMAPPED`: review the target or add a business hint.
- `AMBIGUOUS_MAPPING`: select the intended candidate in the review document.
- `SOURCE_SCHEMA_VALIDATION`: the sample or input does not match the source schema.
- `TARGET_SCHEMA_VALIDATION`: the output does not match the target schema.
- `BUNDLE_HASH_MISMATCH`: discard the bundle and rebuild it from trusted inputs.
- `REVIEW_REQUIRED`: complete the generated review document before loading a deployable bundle.
