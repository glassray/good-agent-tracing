---
name: good-agent-tracing
description: Add, audit or fix OpenTelemetry tracing for an AI agent so a person or an LLM judge can follow what the agent did, see where it went wrong, and tell which version did it. Covers trace structure (one task per trace, nested steps, linking ids, metadata), what to record (model calls, instructions, tool calls, RAG chunks, empty results and failures, structured answers), versioning, human feedback, size limits, safe tracing and redaction. Use when asked to add tracing or observability to an agent or LLM app, to review or improve existing traces, to make traces usable for evals or LLM judges, or when traces are "too noisy", "empty" or "useless".
version: 0.1.0
license: MIT
compatibility: Any AI coding assistant that supports the SKILL.md format (Claude Code, Cursor, VS Code Copilot, OpenHands, etc.). Examples use OpenTelemetry in Python and TypeScript; the rules apply to any tracing backend that accepts OTLP (Glassray, Langfuse, LangSmith, Braintrust, Arize Phoenix, Jaeger and others).
metadata:
  author: Glassray
  repository: https://github.com/glassray/good-agent-tracing
  tags: tracing observability opentelemetry llm agents evals llm-as-judge
---

# Good agent tracing

A trace is useful when whoever reads it, a person or an LLM judge, can follow what the agent did, see where it went wrong, and tell which version of the agent did it. Most agent traces fail that test: they record that the agent ran, not what it saw or why it answered the way it did.

This skill has three modes. Pick the one the user asked for:

- **Add**: instrument an agent that has no tracing, or only the default per-call tracing.
- **Audit**: check existing tracing against the checklist below and report what's missing, without changing code.
- **Fix**: apply the audit's findings, one item at a time.

When the request is vague ("make our traces better"), run Audit first and show the findings before changing anything.

## The checklist

Every item is something a trace needs. Details, the reasoning and code for each are in [references/rules.md](references/rules.md).

**Structure**
1. **One task per trace.** One trace = one job the agent was given (one question, one report, one ticket, one code change). In a chat, one trace per user message. Never one trace for a whole batch.
2. **Every step under one root span.** Model calls, tool calls and retrieval for that task are children of one root span. Not one loose trace per model call.
3. **Ids that connect traces.** The broadest id (conversation, workflow run) in `session.id`; the system's own ids (report, ticket, booking) as attributes; a span link when one task starts another.
4. **Metadata to filter by.** `service.name`, `service.version`, `deployment.environment.name` on the resource; customer, user and product-specific fields on the root span.
5. **Request and answer on the root, detail on each step.** The root's input is what came in, its output is the final result. Token counts only on model-call spans.

**What to record**
6. **Each model call**: full prompt as sent, full response, model, token counts (OpenTelemetry GenAI attributes).
7. **The instructions as text**: system prompt and any rules or policy, not just a version label.
8. **Every tool call's input and output**: search results, page text, rows, API responses.
9. **For RAG**: the query actually run, every chunk returned in full with source, id and score, which chunks were kept, and the final prompt.
10. **Empty results and failures explicitly**: an empty list for "found nothing"; error status for failures, including failures hidden inside a 200 response.
11. **The final answer as structured fields**: decision, reply, claims with pointers to evidence; the decision copied to a root attribute so it can be filtered.

**Comparing versions**
12. **Which version ran**: the commit as `service.version`, a flag for uncommitted changes, a hash of each prompt and rules file.
13. **Human feedback**: thumbs, edits (before and after), reviewer decisions and customer replies as spans carrying the same ids as the answer's trace.

**Safe and affordable**
14. **Cut repetition, not evidence**: record repeated content (system prompt, shared documents) once with a hash; cap only the rare enormous field and flag it as truncated; size export batches.
15. **Tracing never breaks the agent**: tracing code wrapped so errors are logged and dropped; `BatchSpanProcessor` with an export timeout.
16. **Secrets and personal data removed before export**: in one span processor, with placeholders such as `[email]`.

## How to work

### Add

1. **Find the task boundary.** Read the code to find where one task starts and ends (the request handler, the job loop, the chat turn handler). That is where the root span goes. If a batch loop exists, the root span goes inside the loop, per item.
2. **Check what's already there.** Look for existing OpenTelemetry setup, an LLM SDK's auto-instrumentation (OpenAI, Anthropic, LangChain, LlamaIndex, Vercel AI SDK) or a vendor SDK. Reuse it; don't add a second tracer provider.
3. **Set up the provider once** with the resource attributes from item 4 and a `BatchSpanProcessor`. See [references/python.md](references/python.md) or [references/typescript.md](references/typescript.md).
4. **Open the root span per task**, set its input, the ids (item 3) and metadata (item 4), run the work inside its context, and set its output at the end.
5. **Wrap each tool call and retrieval step** in its own child span with input and output (items 8 to 10). Model calls usually come from auto-instrumentation; check they nest under the root and carry the prompt, response, model and tokens (item 6). Add a manual span if not.
6. **Structure the final answer** (item 11) if the agent returns free text that contains a decision.
7. **Add versioning** (item 12) and a **feedback hook** (item 13) where the product already collects feedback.
8. **Add the safety layer**: a redacting span processor (item 16), size caps (item 14) and safe wrappers (item 15).
9. **Verify** with a local run against a console exporter or a local OTLP collector: one trace per task, everything nested, root input and output set, tool outputs present. Show the user one trace's span tree.

### Audit

Read the tracing code and, if the user can share one, a real exported trace. Go through the checklist and report each item as **ok**, **partial** or **missing**, with the file and line that shows it and one sentence on what's wrong. Use the format in [references/audit.md](references/audit.md). Put the items that block grading first: missing tool outputs (8), one trace per call (2) and empty roots (5) usually matter most.

### Fix

Work through the audit's findings in order of impact, one item per change, so each can be reviewed on its own. After each change, re-run the verification step from Add.

## Rules of thumb

- **Record in full, then trim repetition.** Never trim evidence by default; excerpts cut off exactly the sentence that explains a mistake.
- **Same task, same trace. New task, new trace plus a link.**
- **Use the system's real ids, never ids derived from the data.**
- **Don't invent attribute names when a standard one exists.** Prefer OpenTelemetry semantic conventions (`session.id`, `user.id`, `service.version`, `gen_ai.*`), OpenInference (`input.value`, `output.value`) for content, and an `app.` prefix for the rest.
- **Don't change the agent's behaviour.** Tracing is read-only: no new retries, no changed prompts, no extra model calls.
- **Ask before sending data somewhere new.** If the user hasn't chosen a tracing backend, set up a console or local exporter and ask.
