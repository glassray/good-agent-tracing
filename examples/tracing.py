"""Tracing setup and helpers for the travel assistant, as the skill writes them (see references/python.md)."""

import hashlib
import json
import logging
import os
import re
import subprocess
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags

log = logging.getLogger("tracing")
MAX_CHARS = 1_000_000


def _git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


provider = TracerProvider(resource=Resource.create({
    "service.name": "travel-assistant",
    "service.version": os.environ.get("APP_VERSION") or _git("rev-parse", "HEAD") or "unknown",
    "deployment.environment.name": os.environ.get("APP_ENV", "local"),
    "app.git_dirty": _git("status", "--porcelain", "--untracked-files=no") != "",
}))
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(timeout=30), max_export_batch_size=32, export_timeout_millis=30_000,
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("travel-assistant")

_SECRETS = [v for k in ("ANTHROPIC_API_KEY", "SEARCH_API_KEY") if (v := os.environ.get(k))]
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


def _jsonable(obj):
    """SDK objects (pydantic models) as their fields, anything else as text."""
    return obj.model_dump() if hasattr(obj, "model_dump") else str(obj)


def set_content(span, key: str, value) -> None:
    """Records input.value / output.value: redacted, capped, flagged when cut. Never raises."""
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=_jsonable)
        text = redact(text)
        span.set_attribute(f"{key}.truncated", len(text) > MAX_CHARS)
        span.set_attribute(key, text[:MAX_CHARS])
    except Exception:
        log.warning("tracing: could not record %s", key, exc_info=True)


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


@contextmanager
def task_span(name: str, *, session_id: str, request, **ids):
    """One trace per task. Model and tool spans opened inside nest under it."""
    with tracer.start_as_current_span(name, context=trace.set_span_in_context(trace.INVALID_SPAN)) as span:
        span.set_attribute("session.id", session_id)
        for k, v in ids.items():
            span.set_attribute(f"app.{k}", v)
        set_content(span, "input.value", request)
        yield span


def record_feedback(*, session_id: str, answer_trace_id: str, answer_span_id: str, decision: str, reason: str = "") -> None:
    """A thumbs up or down as a short span linked to the answer it is about."""
    link = Link(SpanContext(int(answer_trace_id, 16), int(answer_span_id, 16), is_remote=True, trace_flags=TraceFlags(1)))
    with tracer.start_as_current_span("feedback", context=trace.set_span_in_context(trace.INVALID_SPAN), links=[link]) as span:
        span.set_attribute("session.id", session_id)
        span.set_attribute("feedback.decision", decision)
        set_content(span, "output.value", {"decision": decision, "reason": reason})


__all__ = ["tracer", "set_content", "short_hash", "task_span", "record_feedback", "Status", "StatusCode"]
