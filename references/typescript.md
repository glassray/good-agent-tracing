# TypeScript setup

Uses the OpenTelemetry JS SDK (`npm i @opentelemetry/api @opentelemetry/sdk-trace-base @opentelemetry/resources @opentelemetry/exporter-trace-otlp-http @opentelemetry/context-async-hooks`). If the project already sets up a tracer provider (or a vendor SDK such as `@vercel/otel` does), reuse it and only add the helpers. Keep the SDK packages on one release line (for example `sdk-trace-base`, `resources` and `context-async-hooks` all 2.x, with the matching 0.x exporter); mixing lines fails to install.

## Provider, once at startup

```ts
import { execFileSync } from "node:child_process";
import { context, trace } from "@opentelemetry/api";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BasicTracerProvider, BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";

const git = (...args: string[]): string => {
  try {
    return execFileSync("git", args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return "";
  }
};

const provider = new BasicTracerProvider({
  resource: resourceFromAttributes({
    "service.name": "travel-assistant",
    // CI should set service.version via OTEL_RESOURCE_ATTRIBUTES; fall back to the local commit.
    "service.version": process.env.APP_VERSION || git("rev-parse", "HEAD") || "unknown",
    "deployment.environment.name": process.env.APP_ENV ?? "local",
    "app.git_dirty": git("status", "--porcelain", "--untracked-files=no") !== "",
  }),
  spanProcessors: [
    new BatchSpanProcessor(new OTLPTraceExporter({ timeoutMillis: 30_000 }), {
      maxExportBatchSize: 32, // spans carry full documents, so keep batches small
      exportTimeoutMillis: 30_000,
    }),
  ],
});
// Without a context manager, spans started inside a task don't nest under it across `await`.
context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
trace.setGlobalTracerProvider(provider);
export const tracer = trace.getTracer("travel-assistant");
// On shutdown: await provider.shutdown() so the last batch is sent.
```

## Helpers: safe, redacted, capped content

```ts
import { createHash } from "node:crypto";
import type { Span } from "@opentelemetry/api";

const MAX_CHARS = 1_000_000;
const SECRETS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"].map((k) => process.env[k]).filter((v): v is string => !!v);
const PATTERNS: [RegExp, string][] = [
  [/\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b/g, "[secret]"],
  [/\bBearer\s+[A-Za-z0-9._~+/=-]{16,}/g, "Bearer [secret]"],
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[email]"],
  [/(?<![\w/.-])\+\d[\d ()-]{8,}\d\b/g, "[phone]"],
];

export const redact = (text: string): string => {
  let out = text;
  for (const s of SECRETS) out = out.split(s).join("[secret]");
  for (const [p, r] of PATTERNS) out = out.replace(p, r);
  return out;
};

/** Records input.value / output.value: redacted, capped, flagged when cut. Never throws. */
export const setContent = (span: Span, key: string, value: unknown): void => {
  try {
    const text = redact(typeof value === "string" ? value : JSON.stringify(value) ?? "null");
    span.setAttribute(`${key}.truncated`, text.length > MAX_CHARS);
    span.setAttribute(key, text.slice(0, MAX_CHARS));
  } catch (err) {
    console.warn(`tracing: could not record ${key}`, err);
  }
};

export const shortHash = (text: string): string => createHash("sha256").update(text).digest("hex").slice(0, 12);
```

## One task: root span, ids, input and output

```ts
import { ROOT_CONTEXT, SpanStatusCode, context, trace as api } from "@opentelemetry/api";

export const taskSpan = async <T>(
  name: string,
  attrs: { sessionId: string; ids?: Record<string, string> },
  request: unknown,
  work: () => Promise<T>,
): Promise<T> => {
  const span = tracer.startSpan(name, { attributes: { "session.id": attrs.sessionId, ...Object.fromEntries(Object.entries(attrs.ids ?? {}).map(([k, v]) => [`app.${k}`, v])) } }, ROOT_CONTEXT);
  setContent(span, "input.value", request);
  try {
    const result = await context.with(api.setSpan(ROOT_CONTEXT, span), work);
    setContent(span, "output.value", result);
    return result;
  } catch (err) {
    span.setStatus({ code: SpanStatusCode.ERROR, message: (err as Error).message });
    throw err;
  } finally {
    span.end();
  }
};
```

## Tool calls: input, full output, empty and failed

```ts
export const tracedTool = async <T>(name: string, input: unknown, call: () => Promise<T>): Promise<T> =>
  tracer.startActiveSpan(name, { attributes: { "openinference.span.kind": "TOOL" } }, async (span) => {
    setContent(span, "input.value", input);
    try {
      const result = await call();
      setContent(span, "output.value", result ?? []); // empty stays empty
      if (result && typeof result === "object" && "error" in result) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: String((result as { error: unknown }).error).slice(0, 300) });
      }
      return result;
    } catch (err) {
      span.setStatus({ code: SpanStatusCode.ERROR, message: (err as Error).message });
      throw err;
    } finally {
      span.end();
    }
  });
```

## Model calls

If an auto-instrumentation already records model calls (OpenInference instrumentors, the Vercel AI SDK's `experimental_telemetry`, a vendor SDK), check its spans nest under `taskSpan` and carry the full prompt and response. Otherwise wrap each call like `tracedTool`, with `openinference.span.kind = "LLM"`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` and `app.prompt_hash`.

## Background jobs, links and feedback

- Same task crossing a process: `propagation.inject(context.active(), carrier)` on the sender, `propagation.extract(ROOT_CONTEXT, carrier)` on the receiver, then start the span in that context.
- New task started by another: start a new root span with `links: [{ context: previousSpan.spanContext() }]`.
- Feedback: a short span with the answer's `session.id`, `feedback.decision`, and `output.value` holding the decision, reason and (for edits) the text before and after, linked to the answer's stored trace and span id.
