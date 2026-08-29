# Workflow integration

Build bundles in a reviewed build step and deploy the `.omc` file with your application. Load it once when the process starts.

Python applications can keep one `Mapper` instance and call `transform` for each record. Other runtimes can invoke `open-mapping apply` with one JSON document or a JSONL stream. The command writes data to stdout and diagnostics to stderr.

Treat exit code 8 from `build` as a review queue item. Store the generated suggestion report and review YAML together. After a reviewer chooses decisions, rerun `build` with `--review`. The hash binding prevents an old review from approving new suggestions.

The compiler does not deliver records to another system. Put network retries, idempotency, credentials, and dead-letter handling in the application that calls it.
