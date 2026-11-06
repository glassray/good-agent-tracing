<!-- Output of `claude -p "Audit the tracing in agent.py"` in a project with this skill installed and examples/before.py saved as agent.py. Verbatim except the closing question, which offered to run Fix mode. -->

## Tracing audit: travel assistant (`agent.py`)

Read: `agent.py` (45 lines), `.claude/skills/good-agent-tracing/references/rules.md`. No exported trace available — nothing is running and `OTLPSpanExporter()` points at the default localhost collector, so every finding below is from the code.

| # | Item | Status | Evidence | What's wrong |
| --- | --- | --- | --- | --- |
| 1 | One task per trace | missing | `agent.py:31` `answer()` opens no span | One user question produces several unrelated traces instead of one, so there's no "the agent's answer to this" to open or grade |
| 2 | Steps under one root span | missing | `agent.py:15` auto-instrumentation only; `agent.py:32-35` loop | Each pass through the tool loop is its own root-level trace; you can't see which search fed which prompt |
| 3 | Ids that connect traces | missing | `agent.py:31` takes `conversation_id` and never uses it | The one id that would stitch the fragments (and the turns) together is dropped on the floor |
| 4 | Metadata to filter by | missing | `agent.py:13` `TracerProvider()` with no `Resource` | Service name falls back to `unknown_service`; no environment, no customer, no user, so no group-level questions can be asked |
| 5 | Request and answer on root | missing | `agent.py:37` returns the text, records nothing | No span holds the question or the final answer; the trace list shows bare model calls |
| 6 | Each model call | partial | `agent.py:15` instrumentor records model + token counts | Prompt and response content is behind a capture switch in these packages (`TRACELOOP_TRACE_CONTENT` / `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, depending on version) and nothing here sets it — unverified without a real trace |
| 7 | Instructions as text | partial | `agent.py:18` `SYSTEM_PROMPT` sent at `:34` | Visible only if content capture is on, and with no hash you can't group traces by the exact rules that ran |
| 8 | Tool call input and output | missing | `agent.py:26-28`, called at `:42` | Search results are never recorded as a tool span; when an answer is wrong you can't tell a search that missed the rule from an agent that ignored it |
| 9 | RAG | n/a | No retriever; `web_search` is a tool | Covered by item 8 — when you record results, keep each one's url and rank, not a flattened blob |
| 10 | Empty results and failures | missing | `agent.py:28` `.get("results", [])` | A 500, a changed payload shape and a genuine no-hit all become `[]`, with no error status anywhere; an httpx timeout at `:27` propagates with no span recording it |
| 11 | Final answer as structured fields | missing | `agent.py:37` `response.content[0].text` | The decision exists only as prose, so a judge grades the whole reply instead of one claim against one piece of evidence; no `app.decision` to filter on |
| 12 | Which version ran | missing | `agent.py:13`, no `service.version` | You can't tell which code or which `prompts/visa.md` produced an answer — the prompt can change with no deploy at all |
| 13 | Human feedback | missing | No feedback path in the file | No ground truth to check a judge against; without item 3's ids there's nothing to attach it to anyway |
| 14 | Cut repetition, not evidence | missing | `agent.py:34` resends `SYSTEM_PROMPT` + full history each pass; `:14` no batching | With content on, the whole transcript is duplicated into every model span and grows with each loop; no caps, no hashes, no batch sizing |
| 15 | Tracing never breaks the agent | missing | `agent.py:14` `SimpleSpanProcessor(OTLPSpanExporter())` | Every span end blocks the agent on an HTTP round trip to the collector; if the collector is down or slow, user requests stall with it |
| 16 | Secrets and personal data | missing | No span processor between `:13` and the exporter | A visa assistant handles passport numbers, dates of birth and emails; turn content capture on and all of it ships to the backend verbatim |

### Fix first

1. **Items 2 and 1** — open a root span per user message in `answer()`, run the loop inside its context. This alone turns N orphan traces into one readable trace and is what every item below hangs off.
2. **Item 8 (+10)** — wrap `web_search` in a tool span with `input.value`/`output.value`; call `raise_for_status()` and set error status, keeping `[]` as a real empty result distinct from "not recorded".
3. **Item 5** — set `input.value` (the user message) and `output.value` (the final answer) on the root.
4. **Items 6 and 7** — switch on content capture and confirm against one real trace that prompts, responses and the system prompt actually land; add `app.prompt_hash`.
5. **Items 3 and 4** — `session.id = conversation_id` on the root, plus a `Resource` with `service.name`, `service.version`, `deployment.environment.name`.
6. **Item 11** — have the model return decision/reply/claims and copy the decision to `app.decision`.
7. **Items 15, 16 and 14** — `BatchSpanProcessor` with an export timeout and small batches, and one redacting span processor so no future tool can bypass it. Do these together; they're all in the provider setup.
8. **Items 12 and 13** — commit + dirty flag from the deploy script, and a feedback span wherever the product collects thumbs or edits.

Two things outside tracing that the audit turned up: `prompts/visa.md` doesn't exist in this directory, so `agent.py:18` raises at import; and `response.content[0].text` at `:37` assumes the first block is text, which breaks as soon as the model emits a thinking block first.
