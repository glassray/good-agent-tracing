# The rules, with reasons

Each section matches a checklist item in [SKILL.md](../SKILL.md). The running examples are a travel assistant (answers visa questions with a web search) and an internal handbook assistant (answers from documents with RAG).

## 1. One task per trace

A task is one job the agent was given, from the moment it starts to its result: answering one question, writing one report, handling one ticket, making one code change. In a chat, one trace per user message: the message and everything the agent did to reply.

The common mistake is a whole batch job in one trace: a nightly job over 200 tickets becomes one trace with 200 answers. Nobody can find the one a customer complained about, and a judge has to be told which part to grade. Start a new trace per item and record the batch as an attribute (`app.batch_id`).

## 2. Every step under one root span

The opposite mistake is a trace that's too small. Most telemetry setups record every call to the model out of the box, but not the searches, tool calls and other steps around it, so one report becomes a dozen loose single-span traces. Nobody can see which search fed which prompt, and the real mistake is usually a few steps before the wrong answer.

Open one root span when the task starts and run the work inside its context, so the model-call spans the SDK already records attach to it. When work moves to a background job or another service, propagate the W3C `traceparent` header so those steps join the same trace.

## 3. Ids that connect traces

A task is often wrong because of something earlier: the travel assistant gets a work-permit question wrong because it misread the traveler's nationality two turns back. With the turns connected, a reader can open the traces before and after, in order.

- Put the broadest id (conversation or workflow run) in `session.id`. Most tracing tools group by it.
- Add the system's other ids as attributes: `app.report_id`, `app.ticket_id`.
- Use the system's real ids, never values built from the data (a domain, a name), so the same thing always gets the same id.
- Same task: continue the same trace. New task started by another (a workflow step handing off to the next): start a new trace and add a span link to the one that started it.

## 4. Metadata to filter by

Most questions are about groups of traces: is one customer getting worse answers, did Tuesday's deploy break something, are test runs in the production numbers. A field that wasn't recorded can't be added to old traces.

| What it records | Attribute | Where |
| --- | --- | --- |
| The conversation or workflow | `session.id` | root span |
| The system's own ids | `app.report_id`, `app.ticket_id`, … | root span |
| Which agent | `service.name` | resource |
| Where it ran | `deployment.environment.name` | resource |
| Which code version | `service.version` (the commit) | resource |
| Which prompt version | `app.prompt_hash` | root span or model span |
| The customer or account | `app.customer_id` | root span |
| The user | `user.id` | root span |

Then add product-specific fields: the kind of request, the template or workflow that ran, the customer's plan, the language. Ask "which groups would I compare if the error rate went up?" and record a field for each.

## 5. Request and answer on the root, detail on each step

Most tracing tools show a trace's input and output from its root. An empty root makes the whole trace look empty in the list, even when every step inside is full. Set `input.value` on the root to what came in and `output.value` to the final result.

Large content goes on the step that produced it, once. A parent that refers to its children points to them (id, source, score) instead of copying their text. Token counts go only on model-call spans: tracing tools sum usage across a trace, so a total on the parent counts twice.

## 6. Each model call

Record every model call as its own span with:

- the full prompt as sent (after templates are filled, search results added and context cut);
- the full response;
- the model and the token counts.

The prompt in code isn't the prompt the model gets. Only the recorded prompt shows whether search results made it in, a value came through empty or something was cut. Use the GenAI attributes so tools can work out cost: `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, plus `gen_ai.usage.cache_read.input_tokens` where the provider reports caching.

## 7. The instructions as text

Put the full instructions on the span that used them: the system prompt plus any rules, policy or template. A label like `prompt v6` forces a grader to find the text elsewhere and hope it matches what ran. Add a short content hash (`app.prompt_hash`, first 12 characters of a SHA-256) so traces can be grouped by exact instructions.

## 8. Every tool call's input and output

Every tool call (web search, database query, page read, MCP tool, API call) gets its own span with `input.value` and `output.value`. The output is the part most traces skip, and the part needed when an answer is wrong: the travel assistant says a UK traveler needs a visa for Japan. Either the search never found the 90-day visa-free rule (a search problem) or it found it and the agent ignored it (a prompt problem). Only the recorded results tell them apart.

## 9. RAG

Record, for each answer:

- the query the retriever actually ran, including rewritten or expanded versions;
- every chunk returned, in full, with source (document and page or URL), id and score;
- which chunks were kept after reranking, filtering or deduplication;
- the final prompt sent to the model.

A RAG answer can go wrong in three places: the retriever never found the passage (fix the search), it was found but dropped before the prompt (fix reranking or the number kept), or the model got it and ignored it (fix the prompt or model). A trace with only the question and answer looks the same in all three. Keep chunks whole; if a list is too large for one span, split it across child spans rather than dropping chunks.

## 10. Empty results and failures

A search that found nothing sets `output.value` to an empty list, so "found nothing" and "not recorded" look different. Failures (a tool error, a timeout, a budget running out mid-run) set the span status to error with the reason. Watch for tools that report failure inside a successful response, such as an HTTP 200 whose body says the search failed.

## 11. The final answer as structured fields

Record the agent's final result on the root span as fields, not one block of prose: the decision, the text the user sees, and each claim with a pointer to the tool output that backs it.

```json
{
  "decision": "visa_required",
  "reply": "Yes. You'll need to apply for a tourist visa before you travel.",
  "claims": [
    { "claim": "UK passport holders need a tourist visa for Japan", "evidence": "web_search result 1 (visa-service.example.com)" }
  ]
}
```

A judge can then check one claim against one piece of evidence instead of grading the whole reply. Copy the decision onto the root span as an attribute (`app.decision`) too: tracing tools filter on attributes, not on fields inside a JSON output.

## 12. Which version ran

An agent changes in three ways, so three fields:

- **Code**: the commit as `service.version`, set from CI or the deploy script (`OTEL_RESOURCE_ATTRIBUTES=service.version=$(git rev-parse HEAD)`).
- **Local runs with uncommitted edits**: a flag such as `app.git_dirty`.
- **Prompts that change without a deploy** (config files, prompt managers): `app.prompt_hash` per prompt and rules file.

## 13. Human feedback

When a person reacts to an answer (thumbs up or down, an edit, a reviewer's approval, a customer's reply), record it as a short span carrying the same ids as the answer's trace (`session.id` and the system's ids), with the decision and the reason. For an edit, record the text before and after. Link it to the answer's root span when its trace and span id were stored with the answer. These are the ground truth an LLM judge is checked against, and what you count to see whether the agent is improving.

## 14. Cut repetition, not evidence

Most trace size is the same content recorded again and again: the same system prompt on every model call, the same document passed to several steps. Record it once with a hash and have other spans refer to it by hash, but only if the tracing tool can show the full content from the reference.

For the rare field that is still enormous (a whole uploaded document), cap it and set `<attribute>.truncated = true`. Size export batches so a request stays under the backend's limit (the default of 512 spans is too many once spans carry full documents). If one trace is too large to keep, skip it and log it rather than failing the whole export.

## 15. Tracing never breaks the agent

Tracing code runs inside the agent: serialising results, hashing prompts, attaching the answer. Wrap it so any error is logged and dropped. Use `BatchSpanProcessor` (exports on a background thread), not `SimpleSpanProcessor` (exports on the agent's thread), and set an export timeout.

## 16. Secrets and personal data

Full prompts, tool results and documents all reach the tracing backend. Before export, remove:

- secrets: API keys, tokens, credentials in tool configs or request headers;
- personal data not needed to grade the answer: emails, phone numbers, passport or account numbers.

Do it in one place, a span processor or exporter wrapper that runs on every span, so no new tool can skip it. Replace values with placeholders (`[email]`, `[secret]`). If a field can't be cleaned safely (a whole uploaded document), record a description and a hash instead of the content.
