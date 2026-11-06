"""A travel assistant with the tracing most agents ship with: the LLM SDK's auto-instrumentation and nothing else."""

import json

import anthropic
import httpx
from opentelemetry import trace
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
AnthropicInstrumentor().instrument()

client = anthropic.Anthropic()
SYSTEM_PROMPT = open("prompts/visa.md").read()
SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web",
    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}


def web_search(query: str) -> list[dict]:
    response = httpx.get("https://search.example.com/v1", params={"q": query}, timeout=10)
    return response.json().get("results", [])


def answer(conversation_id: str, messages: list[dict]) -> str:
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024, system=SYSTEM_PROMPT, messages=messages, tools=[SEARCH_TOOL]
        )
        if response.stop_reason != "tool_use":
            return response.content[0].text
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                found = web_search(block.input["query"])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(found)})
        messages.append({"role": "user", "content": results})
