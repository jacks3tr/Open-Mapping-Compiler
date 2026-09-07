# Python SDK

Use AI while configuring a mapping, then reuse a deterministic runtime. Your application owns artifact storage, provider credentials, approval UI, scheduling, and delivery.

## Complete in-memory example

```python
from open_mapping import Compiler, Mapper

schema = {
    "$id": "customer-name",
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string", "description": "Canonical customer display name"}
    },
}

built = Compiler(offline=True).build(source=schema, target=schema, mapping_id="customer")
mapper = Mapper.from_bundle(built.require_bundle())
assert mapper.transform({"name": "Ada"}) == {"name": "Ada"}
assert mapper.validate_source({"name": 3})

results = list(mapper.iter_results([{"name": "Ada"}, {"name": 3}, {"name": "Grace"}]))
assert [result.success for result in results] == [True, False, True]
```

`Mapper` prepares validation, rule order, and pointer tokens once. Reuse it; do not reload a bundle for every record. `iter_results` yields a zero-based input index, success flag, output, and structured issues. It catches mapping errors, not programming errors. `transform_many` and `iter_transform` remain fail-fast.

## Generate suggestions or build a bundle

`map_schemas(source, target, ...)` returns a `SuggestionReport`. `Compiler.build(...)` additionally assembles, verifies, and returns a `BuildResult` with `ready` or `needs_review` status. Check the status before calling `require_bundle()`.

Both accept file paths, parsed JSON Schema dictionaries, or normalized `SchemaDocument` objects. OpenAPI dictionaries work without temporary files:

```python
from open_mapping import Compiler

schema = {
    "type": "object",
    "required": ["name"],
    "properties": {"name": {"type": "string", "description": "Canonical customer name"}},
}
openapi = {"openapi": "3.1.0", "components": {"schemas": {"Customer": schema}}}
result = Compiler(offline=True).build(
    source=openapi,
    source_format="openapi",
    source_selector="component:Customer",
    target=schema,
)
assert result.ready
```

Request/response selectors use the same supported syntax as file-based OpenAPI inputs. Remote references remain subject to the existing adapter restrictions.

## Model policy and host-owned inference

Pass `model="provider:model-id"`, a resolved model, or set `OPEN_MAPPING_MODEL`. Explicit selection overrides the environment. `offline=True` overrides both. `require_model=True` rejects missing configuration and invocation failures; combining it with offline mode is an error. Without `require_model`, provider failures are surfaced as warning issues rather than hidden.

Set `model_concurrency` from `1` to `8` to opt into parallel context batches; the default is `1`. Parallel batches use separate transport instances and preserve deterministic report ordering. Your application remains responsible for provider quotas and tenant policy.

`Compiler` and `map_schemas` accept `transport_registry: Mapping[ProviderKind, TransportFactory]`. Public types are available from `open_mapping.providers.protocol`; a factory takes `ResolvedModel` and returns an object implementing `invoke(ModelTransportRequest) -> ModelTransportResult`. Supply the entry matching the resolved provider kind. This lets your existing gateway handle authentication, routing, and usage accounting without environment mutation or monkey-patching. An explicitly empty registry is not replaced with default transports. Factories used concurrently must return independent instances.

The compiler still validates the provider response, allowed paths and operations, and proposed rules. A transport is not an arbitrary-code execution extension.

## Persist and resume the exact draft

Every successful build operation returns `result.draft`. Serialize it with `model_dump_json()` into your own storage. Restore it with `BuildDraft.model_validate_json(...)` or `BuildDraft.load(Path(...))`. Pass the restored draft and completed `SuggestionReviewDocument` to `Compiler().resume(draft, review=review)`.

Resumption does not resolve model settings or regenerate suggestions. It preserves saved samples, verification limits, and complete-review policy. The review must match the original suggestion hash and mapping ID. `build(..., draft=original_draft, review=review)` additionally checks supplied source and target contracts against the snapshot; changed contracts are rejected.

**Migration:** calling `build(..., review=review)` without the original draft is no longer supported. That path used to rerun inference and could invalidate the very proposal being approved. Generate a new draft once, then resume it for subsequent decisions.

Draft hashes detect accidental changes, not authenticity. Drafts include verification sample data and proposal evidence, but not provider credentials. Enforce access controls and retention in your storage; do not commit drafts containing customer records. Changes to hints, instructions, samples, or contracts require a new build rather than editing the sealed draft.

## Schema inference and maintenance

`source_format="json-data"` accepts a record or nonempty record array and uses those records as verification samples. Inference does not infer enums, formats, ranges, or descriptions from values. A property observed in every record becomes required in the inferred contract; a single record is not evidence that the property is always required. Prefer authoritative schemas for production validation, or inspect and deliberately broaden inferred constraints.

`Compiler.analyze_changes(bundle, source=new_source, target=new_target)` reports rule impact without inference or artifact mutation. Unchanged rules are informational, not automatic approval reuse. Any contract change requires review; unsupported reference/array comparisons conservatively consider the full contract. Invariants are separately flagged for review when contracts change.

See [bundle guarantees](bundles.md), [workflow result contracts](workflow-integration.md), and the [runnable AI example](../examples/model-assisted/README.md).
