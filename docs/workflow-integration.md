# Workflow integration

Use AI to generate the first-pass mapping during a reviewed build step, then deploy the verified `.omc` file with your application. Load the bundle once when the process starts. The runtime path is deterministic and does not call the model.

## Where compilation fits

Compile a mapping when a customer configures a connector, when either schema changes, or as a reviewed CI step. Supply source JSON data or a source contract, the target contract, and any optional hints or business context. The result either builds a verified bundle or returns a hash-bound review file for the decisions the inputs cannot prove.

Do not call a model for every production record. Treat the `.omc` bundle as the versioned integration artifact and rebuild it when its source or target contract changes.

## Runtime options

Python applications can keep one `Mapper` instance and call `transform` for each record. Other runtimes can invoke `open-mapping apply` with one JSON document or a JSONL stream. The command writes data to stdout and diagnostics to stderr.

```python
from open_mapping import Mapper

mapper = Mapper.load("mapping.omc")
target_record = mapper.transform(source_record)
```

Products that do not embed Python can install `open-mapping[server]` and call the local HTTP sidecar. See the [sidecar guide](server.md) for its validation and transform endpoints.

## Review and delivery

Treat exit code 8 from `build` as a review queue item. Store the generated suggestion report and review YAML together. After a reviewer chooses decisions, rerun `build` with `--review`. The hash binding prevents an old review from approving new suggestions.

The compiler does not deliver records to another system. Put network retries, idempotency, credentials, and dead-letter handling in the application that calls it.
