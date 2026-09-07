# TypeScript sidecar client

Use AI when configuring a mapping; this client only executes already-built bundles through the Python sidecar. It has no runtime package dependency and is tested with Node 24 and native `fetch`.

Copy `open_mapping_client.ts` into your application. Unlike generated expression-only TypeScript, the sidecar retains source/target schema validation and mapping-level invariants.

After starting the [local example sidecar](../../docs/server.md):

```typescript
import { MappingClient, MappingHttpError } from "./open_mapping_client.js";

const client = new MappingClient("http://127.0.0.1:8080", { timeoutMs: 10_000 });
const output = await client.transform({ customer_id: "C-100", name: "Ada" });
console.log(output); // { customerId: "C-100", displayName: "Ada" }

const records = await client.collect([
  { customer_id: "C-100", name: "Ada" },
  { customer_id: 3, name: "Invalid" },
]);
console.log(records.map((record) => [record.index, record.success]));

try {
  await client.transform({ customer_id: 3, name: "Invalid" });
} catch (error) {
  if (!(error instanceof MappingHttpError)) throw error;
  console.log(error.status, error.issues);
}
```

For authenticated servers, pass `apiKey` from your application's secret storage. Never ship a private sidecar token in a public browser bundle. Requests prohibit redirects, support caller cancellation, enforce a timeout, and do not retry automatically.

`transformMany` fails the batch on the first mapping error; `collect` returns each indexed outcome. `validate` checks only the source contract, and `metadata` returns server/bundle metadata. Output is typed as `JsonValue`, not falsely asserted to satisfy an arbitrary TypeScript generic. Your application's concrete domain types remain its responsibility.

Run `npm run typecheck` and `npm run test:client` from the repository to verify the client. The shared [conformance fixture](../conformance/identity.json) describes SDK/sidecar behavior; [expression fixtures](../../tests/golden/codegen/full/cases.jsonl) have a narrower scope and do not establish generated TypeScript validation parity.
