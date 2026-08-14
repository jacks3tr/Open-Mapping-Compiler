# Quick start: map two schemas

Open Mapping Compiler takes a source schema and a target schema and creates a checked data transformation between them.

The source schema describes the data you have. The target schema describes the data you need. The compiler does not call APIs or move messages between systems. Your application handles that part.

This guide uses standalone JSON Schema files.

## Install the project

Run these commands from the repository root:

```text
uv sync --frozen --all-extras
npm ci
```

## Create a mapping folder

```text
my-mapping/
├── source.schema.json
├── target.schema.json
├── samples.jsonl
├── input.json
├── hints.yaml
└── build/
```

You need the two schema files and at least one source sample. Create `hints.yaml` only if the tool cannot safely resolve every target field.

## 1. Check the schemas

```text
uv run open-mapping inspect my-mapping/source.schema.json
uv run open-mapping inspect my-mapping/target.schema.json
```

Check the field paths, types, required fields, enums, and descriptions. Fix either schema if the printed structure does not match the real payload.

Descriptions matter when the systems use different names for the same concept.

## 2. Add one sample

Create `my-mapping/samples.jsonl`. Each line contains one sample source record:

```json
{"id":"basic","input":{"customerId":"C-1001","status":"ACTIVE"}}
```

The value under `input` must match `source.schema.json`.

You can also include the expected target result:

```json
{"id":"basic","input":{"customerId":"C-1001","status":"ACTIVE"},"expected":{"accountNumber":"C-1001","state":"Open","sourceSystem":"CRM"}}
```

Save one source payload as `my-mapping/input.json` so you can test the finished mapping.

## 3. Generate suggestions

```text
uv run open-mapping suggest my-mapping/source.schema.json my-mapping/target.schema.json --samples my-mapping/samples.jsonl --suggestions-out my-mapping/build/suggestions.json --report-format text
```

The report gives every target field one result:

- `suggested`: strong match
- `review_required`: likely match that needs your decision
- `ambiguous`: more than one source field could be correct
- `no_match`: no safe match was found
- `manual`: rule supplied through `hints.yaml`

Do not force an ambiguous match. Add a hint that records the business decision.

## 4. Add hints when needed

Suppose the source has `/customerId` and `/status`, while the target requires `/accountNumber`, `/state`, and `/sourceSystem`.

Create `my-mapping/hints.yaml`:

```yaml
hints_version: "0.1"
id: customer-to-account

direct:
  - target: /accountNumber
    source: /customerId
    reason: The account number uses the source customer ID.

lookups:
  - target: /state
    source: /status
    values:
      ACTIVE: Open
      INACTIVE: Closed
    default: Closed
    reason: Approved status translation.

constants:
  - target: /sourceSystem
    value: CRM
    reason: These records come from CRM.
```

Use a direct hint to approve a likely field match. Other hints can define lookup tables, constants, date formatting, unit conversions, and typed expressions.

## 5. Build the mapping

```text
uv run open-mapping suggest my-mapping/source.schema.json my-mapping/target.schema.json --samples my-mapping/samples.jsonl --hints my-mapping/hints.yaml --suggestions-out my-mapping/build/suggestions.json --mapping-out my-mapping/build/mapping.yaml --mapping-id customer-to-account --assembly-policy high-and-manual --report-format text --force
```

This includes strong automatic matches and valid hints. It does not silently accept weaker or ambiguous suggestions.

If a required target is still unmapped, read `build/suggestions.json`, add the missing business decision to `hints.yaml`, and run the command again.

## 6. Verify the mapping

```text
uv run open-mapping verify my-mapping/build/mapping.yaml --source my-mapping/source.schema.json --target my-mapping/target.schema.json --samples my-mapping/samples.jsonl --report-format text
```

Verification runs the mapping against the samples and checks the target schema. Add samples for null values, optional fields, enum values, arrays, and other cases that matter to the integration.

Do not use the mapping until verification succeeds.

## 7. Transform a payload

```text
uv run open-mapping run my-mapping/build/mapping.yaml --source-schema my-mapping/source.schema.json --target-schema my-mapping/target.schema.json --input my-mapping/input.json --out my-mapping/build/output.json --force
```

The transformed record is written to `my-mapping/build/output.json`.

## Compile for an application

Python:

```text
uv run open-mapping compile my-mapping/build/mapping.yaml --source my-mapping/source.schema.json --target my-mapping/target.schema.json --target-language python --out my-mapping/build/generated_mapping.py --force
```

TypeScript:

```text
uv run open-mapping compile my-mapping/build/mapping.yaml --source my-mapping/source.schema.json --target my-mapping/target.schema.json --target-language typescript --out my-mapping/build/generated_mapping.ts --force
```

Your application reads the source payload, calls the generated transformation, and sends the result to the target system.

## OpenAPI schemas

OpenAPI 3.1 files need a selector. Examples include `component:Customer`, `request:createCustomer`, and `response:getCustomer:200`.

Add the format and selector options to `inspect`, `suggest`, `verify`, or `compile`:

```text
--source-format openapi --source-selector "response:getCustomer:200"
--target-format openapi --target-selector "request:createAccount"
```

You can use OpenAPI on one side and standalone JSON Schema on the other.

## Common errors

- `REQUIRED_TARGET_UNMAPPED`: add or correct a hint for that target.
- `AMBIGUOUS_MAPPING`: record the business decision in `hints.yaml`.
- `SOURCE_SCHEMA_VALIDATION`: the sample or input does not match the source schema.
- `TARGET_SCHEMA_VALIDATION`: the mapping output does not match the target schema.

## The whole workflow

```text
inspect schemas
create suggestions
add hints where needed
build mapping.yaml
verify with samples
run or compile
```
