# Workflow integration

Run AI during mapping configuration, not once per business transaction. Persist an approved bundle, load it once per worker, and let the host workflow own retries, idempotency, delivery, quarantine, and storage.

## Machine-readable build lifecycle

For validly parsed `build` and `resume` invocations, `--report-format json` writes exactly one JSON object to stdout:

```json
{
  "status": "needs_review",
  "mapping_id": "customer",
  "issues": [],
  "artifact_paths": {"draft": "work/customer/draft.json", "review": "customer.review.yaml", "suggestions": "work/customer/suggestions.json"},
  "verification": null
}
```

Statuses are `ready`, `needs_review`, and `failed`. `verification` contains bundle verification metadata when ready. On failure, issues explain the error and `artifact_paths` is empty. Human diagnostics do not contaminate JSON stdout. CLI argument/usage errors still use the command parser's standard stderr and exit `2`; do not attempt to parse stdout after an invalid invocation.

| Operation | Exit code |
| --- | --- |
| Build/resume ready | `0` |
| Build/resume needs review | `8` |
| Build/resume invalid input, artifact, or mapping | `2` |
| Required provider invocation fails | `5` |
| Interrupted build/resume | `130` |
| Apply encounters invalid records | `4` |
| Impact report: unchanged and statically valid | `0` |
| Impact report: changed but statically valid | `8` |
| Impact report: static failures | `3` |

Persist the draft returned by a review-required build. After your approval interface writes a matching decision document, invoke `resume DRAFT --review REVIEW --out BUNDLE`. Do not reconstruct a build command or rerun the model to resume. Failed/incomplete review is not permission to weaken verification.

## Stream records

After `open-mapping demo --out-dir example`, create a JSONL input file:

```jsonl
{"customer_id":"C-100","name":"Ada"}
{"customer_id":3,"name":"Invalid"}
{"customer_id":"C-101","name":"Grace"}
```

Apply it with complete per-record outcomes:

```text
open-mapping apply example/mapping.omc --input records.jsonl --jsonl --on-error collect --out results.jsonl
```

Results contain `index`, `success`, `output`, and `issues`. Indices count nonblank records from zero. Malformed JSON lines also produce failed results and do not discard later valid records. The command writes all collected outcomes and exits `4` when any record failed. Inspect the outcome, not whether output is null: a success flag distinguishes valid null data from failure.

Default `--on-error raise` stops at the first failure. `--on-error collect` requires JSONL and is explicit opt-in. File output is buffered and atomically replaced only after a complete run; stdout stays line-flushed for pipelines. `--force` permits replacing an output, never a known input or bundle file. Route failed results to your existing quarantine or retry mechanism rather than introducing another queue inside this library.

## Embedded and HTTP batches

Python `Mapper.iter_results` yields lazily and preserves order. `transform_many` remains eager and fail-fast for compatibility. The HTTP `/transform-batch` endpoint supports `on_error: "collect"`; it limits requests to 1,000 records and 10 MiB. Split larger jobs upstream.

A bundle is data, not an authenticated approval record. Use your existing storage ACLs and artifact promotion process. Drafts include sample data; runtime bundles do not automatically include those samples. See [bundle compatibility](bundles.md) and the [sidecar contract](server.md).
