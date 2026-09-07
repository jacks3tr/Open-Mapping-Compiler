/** Native-fetch client for the verified Python sidecar, not the narrower generated evaluator. */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type Issue = {
  code: string;
  severity: string;
  component: string;
  message: string;
  correction: string;
};
export type TransformResult = {
  index: number;
  success: boolean;
  output: JsonValue;
  issues: Issue[];
};

export class MappingHttpError extends Error {
  constructor(public readonly status: number, public readonly issues: readonly Issue[]) {
    super(`Mapping sidecar returned HTTP ${status}`);
    this.name = "MappingHttpError";
  }
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Mapping sidecar returned an invalid response object");
  }
  return value as Record<string, unknown>;
}

function issues(value: unknown): Issue[] {
  if (!Array.isArray(value)) throw new Error("Mapping sidecar returned invalid response issues");
  return value.map((entry) => {
    const item = object(entry);
    for (const key of ["code", "severity", "component", "message", "correction"]) {
      if (typeof item[key] !== "string") throw new Error("Mapping sidecar returned invalid response issues");
    }
    return item as Issue;
  });
}

export class MappingClient {
  private readonly base: URL;
  private readonly fetcher: typeof fetch;
  private readonly timeoutMs: number;
  private readonly apiKey: string | undefined;

  constructor(baseUrl: string, options: { apiKey?: string; timeoutMs?: number; fetch?: typeof fetch } = {}) {
    this.base = new URL(baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
    if (!["http:", "https:"].includes(this.base.protocol) || this.base.username || this.base.password) {
      throw new Error("Use an HTTP(S) sidecar URL without embedded credentials");
    }
    if (this.base.search || this.base.hash) throw new Error("Sidecar URL must not contain a query or fragment");
    this.timeoutMs = options.timeoutMs ?? 30_000;
    if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs < 1) throw new Error("timeoutMs must be a positive integer");
    this.fetcher = options.fetch ?? globalThis.fetch;
    this.apiKey = options.apiKey;
  }

  private async request(path: string, payload: unknown, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const headers = new Headers({ "Content-Type": "application/json", Accept: "application/json" });
    if (this.apiKey !== undefined) headers.set("Authorization", `Bearer ${this.apiKey}`);
    const timeout = AbortSignal.timeout(this.timeoutMs);
    const response = await this.fetcher(new URL(path, this.base), {
      method: payload === undefined ? "GET" : "POST",
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      headers,
      signal: signal === undefined ? timeout : AbortSignal.any([signal, timeout]),
      redirect: "error",
      cache: "no-store",
    });
    const body = object(await response.json());
    if (!response.ok) throw new MappingHttpError(response.status, issues(body.issues));
    return body;
  }

  async transform(input: JsonValue, signal?: AbortSignal): Promise<JsonValue> {
    const body = await this.request("transform", { input }, signal);
    if (!Object.hasOwn(body, "output")) throw new Error("Mapping sidecar returned an invalid response: missing output");
    return body.output as JsonValue;
  }

  async validate(input: JsonValue, signal?: AbortSignal): Promise<{ valid: boolean; issues: Issue[] }> {
    const body = await this.request("validate", { input }, signal);
    if (typeof body.valid !== "boolean") throw new Error("Mapping sidecar returned an invalid response: missing valid");
    return { valid: body.valid, issues: issues(body.issues) };
  }

  async transformMany(inputs: JsonValue[], signal?: AbortSignal): Promise<JsonValue[]> {
    const body = await this.request("transform-batch", { inputs }, signal);
    if (!Array.isArray(body.outputs) || body.outputs.length !== inputs.length) {
      throw new Error("Mapping sidecar returned an invalid response: batch length mismatch");
    }
    return body.outputs as JsonValue[];
  }

  async collect(inputs: JsonValue[], signal?: AbortSignal): Promise<TransformResult[]> {
    const body = await this.request("transform-batch", { inputs, on_error: "collect" }, signal);
    if (!Array.isArray(body.results) || body.results.length !== inputs.length) {
      throw new Error("Mapping sidecar returned an invalid response: batch length mismatch");
    }
    return body.results.map((entry, index) => {
      const item = object(entry);
      if (item.index !== index || typeof item.success !== "boolean" || !Object.hasOwn(item, "output")) {
        throw new Error("Mapping sidecar returned an invalid response: record identity mismatch");
      }
      const recordIssues = issues(item.issues);
      if ((item.success && recordIssues.length !== 0) || (!item.success && recordIssues.length === 0)) {
        throw new Error("Mapping sidecar returned an invalid response: inconsistent record outcome");
      }
      return { index, success: item.success, output: item.output as JsonValue, issues: recordIssues };
    });
  }

  async metadata(signal?: AbortSignal): Promise<Record<string, unknown>> {
    return this.request("metadata", undefined, signal);
  }
}
