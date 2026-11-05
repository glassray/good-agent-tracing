# Python setup

Uses the OpenTelemetry SDK (`pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`). If the project already sets up a tracer provider (or a vendor SDK does), reuse it and only add the helpers.

## Provider, once at startup

```python
import os, subprocess
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


def _git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


resource = Resource.create({
    "service.name": "travel-assistant",
    # CI should set service.version via OTEL_RESOURCE_ATTRIBUTES; fall back to the local commit.
    "service.version": os.environ.get("APP_VERSION") or _git("rev-parse", "HEAD") or "unknown",
    "deployment.environment.name": os.environ.get("APP_ENV", "local"),
    "app.git_dirty": _git("status", "--porcelain", "--untracked-files=no") != "",
})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(timeout=30),   # endpoint and headers from OTEL_EXPORTER_OTLP_* env vars
    max_export_batch_size=32,       # spans carry full documents, so keep batches small
    export_timeout_millis=30_000,
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("travel-assistant")
```

## Helpers: safe, redacted, capped content

Every content write goes through `set_content`, so redaction and the size cap live in one place.

```python
import hashlib, json, logging, re

log = logging.getLogger("tracing")
MAX_CHARS = 1_000_000
_SECRETS = [v for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY") if (v := os.environ.get(k))]
_PATTERNS = [
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"), "[secret]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [secret]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<![\w/.-])\+\d[\d ()-]{8,}\d\b"), "[phone]"),
]


def redact(text: str) -> str:
    for s in _SECRETS:
        text = text.replace(s, "[secret]")
    for pattern, placeholder in _PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


def set_content(span, key: str, value) -> None:
    """Records input.value / output.value: redacted, capped, flagged when cut. Never raises."""
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        text = redact(text)
        span.set_attribute(f"{key}.truncated", len(text) > MAX_CHARS)
        span.set_attribute(key, text[:MAX_CHARS])
    except Exception:
        log.warning("tracing: could not record %s", key, exc_info=True)


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
```

## One task: root span, ids, input and output

```python
from contextlib import contextmanager
from opentelemetry.trace import Status, StatusCode


@contextmanager
def task_span(name: str, *, session_id: str, request, **ids):
    """One trace per task. Model and tool spans opened inside nest under it."""
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("session.id", session_id)
        for k, v in ids.items():
            span.set_attribute(f"app.{k}", v)
        set_content(span, "input.value", request)
        yield span


with task_span("visa_question", session_id=conversation_id, request=user_message,
               customer_id=customer.id) as root:
    answer = run_agent(user_message)                     # model + tool spans nest here
    set_content(root, "output.value", answer)            # structured: decision, reply, claims
    root.set_attribute("app.decision", answer["decision"])
```

## Tool calls: input, full output, empty and failed

```python
def traced_tool(name: str, fn, **kwargs):
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("openinference.span.kind", "TOOL")
        set_content(span, "input.value", kwargs)
        try:
            result = fn(**kwargs)
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        # An empty list stays an empty list: "found nothing" must look different from "not recorded".
        set_content(span, "output.value", result if result is not None else [])
        if isinstance(result, dict) and result.get("error"):   # failure inside a 200
            span.set_status(Status(StatusCode.ERROR, str(result["error"])[:300]))
        return result


results = traced_tool("web_search", search, query="Japan visa UK passport tourist")
```

## Model calls

If an auto-instrumentation package already records model calls (for example `opentelemetry-instrumentation-openai-v2`, `opentelemetry-instrumentation-anthropic`, OpenInference's instrumentors), check that its spans nest under `task_span` and carry the full prompt and response; some packages need content capture switched on (for example `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`). Otherwise record each call manually:

```python
with tracer.start_as_current_span("chat") as span:
    span.set_attribute("openinference.span.kind", "LLM")
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("app.prompt_hash", short_hash(system_prompt))
    set_content(span, "input.value", messages)           # the full prompt as sent
    response = client.messages.create(model=model, system=system_prompt, messages=messages, max_tokens=1024)
    set_content(span, "output.value", response.model_dump())
    span.set_attribute("gen_ai.response.model", response.model)
    span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
```

## Human feedback

```python
def record_feedback(*, session_id: str, answer_trace_id: str, answer_span_id: str, decision: str, reason: str = "", before=None, after=None):
    from opentelemetry.trace import Link, SpanContext, TraceFlags
    link = Link(SpanContext(int(answer_trace_id, 16), int(answer_span_id, 16), is_remote=True, trace_flags=TraceFlags(1)))
    with tracer.start_as_current_span("feedback", context=trace.set_span_in_context(trace.INVALID_SPAN), links=[link]) as span:
        span.set_attribute("session.id", session_id)
        span.set_attribute("feedback.decision", decision)
        set_content(span, "output.value", {"decision": decision, "reason": reason, "before": before, "after": after})
```

Store the answer's root `trace_id` and `span_id` (hex) next to the answer when it is saved, so the feedback can link to it later.

## Background jobs and other services

Same task crossing a process: inject the context on the sending side and extract it on the receiving side.

```python
from opentelemetry.propagate import inject, extract

carrier = {}
inject(carrier)                     # sender: put carrier["traceparent"] in the job payload or headers
ctx = extract(job.payload["trace"]) # receiver
with tracer.start_as_current_span("process_job", context=ctx):
    ...
```

New task started by another: start a new root span with `links=[Link(previous_span.get_span_context())]` instead of continuing the trace.
