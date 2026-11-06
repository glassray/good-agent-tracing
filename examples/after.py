"""The same travel assistant after the skill's Fix mode. The prompt, model and tools are unchanged; answer() also returns the ids feedback needs to link back to it."""

import json

import anthropic
import httpx
from opentelemetry import trace

from tracing import Status, StatusCode, record_feedback, set_content, short_hash, task_span, tracer

client = anthropic.Anthropic()
SYSTEM_PROMPT = open("prompts/visa.md").read()
PROMPT_HASH = short_hash(SYSTEM_PROMPT)
SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web",
    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}


def web_search(query: str) -> list[dict]:
    with tracer.start_as_current_span("web_search") as span:
        span.set_attribute("openinference.span.kind", "TOOL")
        set_content(span, "input.value", {"query": query})
        try:
            response = httpx.get("https://search.example.com/v1", params={"q": query}, timeout=10)
            body = response.json()
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        results = body.get("results", [])
        set_content(span, "output.value", results)  # every result in full; an empty list stays empty
        if body.get("error"):  # the search API reports some failures inside a 200
            span.set_status(Status(StatusCode.ERROR, str(body["error"])[:300]))
        return results


def chat(messages: list[dict]):
    with tracer.start_as_current_span("chat") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("gen_ai.request.model", "claude-sonnet-4-6")
        span.set_attribute("app.prompt_hash", PROMPT_HASH)
        set_content(span, "input.value", {"system": SYSTEM_PROMPT, "messages": messages})
        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024, system=SYSTEM_PROMPT, messages=messages, tools=[SEARCH_TOOL]
        )
        set_content(span, "output.value", response.model_dump())
        span.set_attribute("gen_ai.response.model", response.model)
        span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
        return response


def answer(conversation_id: str, messages: list[dict], customer_id: str = "") -> dict:
    """One user message in, one reply out. Returns the reply and the ids feedback needs to link back to it."""
    with task_span("visa_question", session_id=conversation_id, request=messages[-1], customer_id=customer_id) as root:
        sources = []
        while True:
            response = chat(messages)
            if response.stop_reason != "tool_use":
                reply = response.content[0].text
                set_content(root, "output.value", {"reply": reply, "sources": sources})
                ctx = root.get_span_context()
                return {"reply": reply, "trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}"}
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    found = web_search(block.input["query"])
                    sources += [r.get("url") for r in found if r.get("url")]
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(found)})
            messages.append({"role": "user", "content": results})


def on_thumbs(conversation_id: str, saved_answer: dict, thumbs_up: bool, reason: str = "") -> None:
    record_feedback(
        session_id=conversation_id,
        answer_trace_id=saved_answer["trace_id"],
        answer_span_id=saved_answer["span_id"],
        decision="up" if thumbs_up else "down",
        reason=reason,
    )
