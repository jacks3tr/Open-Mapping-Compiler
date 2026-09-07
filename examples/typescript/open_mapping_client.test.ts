import assert from "node:assert/strict";
import test from "node:test";
import { MappingClient, MappingHttpError } from "./open_mapping_client.js";

const issue = { code: "SOURCE_SCHEMA_VALIDATION", severity: "error", component: "runtime", message: "Invalid input", correction: "Check the source contract." };

test("transform sends bearer authentication and forbids redirects", async () => {
  let calls = 0;
  const fetcher: typeof fetch = async (input, init) => {
    calls += 1;
    assert.equal(String(input), "https://example.com/mapper/transform");
    assert.equal(new Headers(init?.headers).get("authorization"), "Bearer test-token");
    assert.equal(init?.redirect, "error");
    assert.deepEqual(JSON.parse(String(init?.body)), { input: { name: "Ada" } });
    return Response.json({ output: { displayName: "Ada" } });
  };
  const client = new MappingClient("https://example.com/mapper/", { apiKey: "test-token", fetch: fetcher });
  assert.deepEqual(await client.transform({ name: "Ada" }), { displayName: "Ada" });
  assert.equal(calls, 1);
});

test("validation errors remain typed and are not retried", async () => {
  let calls = 0;
  const client = new MappingClient("http://127.0.0.1:8080", { fetch: async () => {
    calls += 1;
    return Response.json({ issues: [issue] }, { status: 422 });
  } });
  await assert.rejects(client.transform({ name: 3 }), (error: unknown) => {
    assert.ok(error instanceof MappingHttpError);
    assert.equal(error.status, 422);
    assert.equal(error.issues[0]?.code, issue.code);
    return true;
  });
  assert.equal(calls, 1);
});

test("collect mode retains null outputs and record-level failures", async () => {
  const client = new MappingClient("http://localhost:8080", { fetch: async (_input, init) => {
    assert.equal(JSON.parse(String(init?.body)).on_error, "collect");
    return Response.json({ results: [
      { index: 0, success: true, output: null, issues: [] },
      { index: 1, success: false, output: null, issues: [issue] },
    ] });
  } });
  assert.deepEqual((await client.collect([null, 3])).map((item) => item.success), [true, false]);
});

test("malformed success envelopes fail explicitly", async () => {
  const client = new MappingClient("http://localhost:8080", { fetch: async () => Response.json({ wrong: true }) });
  await assert.rejects(client.transform({ name: "Ada" }), /invalid response/);
});

test("credentials embedded in URLs and invalid timeouts are rejected", () => {
  assert.throws(() => new MappingClient("https://user:secret@example.com"), /credentials/);
  assert.throws(() => new MappingClient("https://example.com", { timeoutMs: 0 }), /timeout/);
});
