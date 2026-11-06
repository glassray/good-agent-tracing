## Tracing audit: travel assistant (before)

Read: `examples/before.py`

| # | Item | Status | Evidence | What's wrong |
| --- | --- | --- | --- | --- |
| 1 | One task per trace | missing | `before.py:33`, model calls traced by `AnthropicInstrumentor` only | Each model call is its own trace, so one answer is spread over several |
| 2 | Every step under one root span | missing | no span around `answer()` (`before.py:31`) | You can't see which search fed which reply |
| 3 | Ids that connect traces | missing | `conversation_id` (`before.py:31`) is never recorded | The turns of one conversation can't be found together |
| 4 | Metadata to filter by | missing | `TracerProvider()` with no resource (`before.py:13`) | Every trace says `unknown_service`, with no environment or customer |
| 5 | Request and answer on the root | missing | no root span | The trace list shows no question and no answer |
| 6 | Each model call | partial | `AnthropicInstrumentor` (`before.py:15`) | Model and tokens are recorded; prompt and response only if the instrumentation's content capture is on, and nothing here sets it |
| 7 | The instructions as text | partial | `SYSTEM_PROMPT` sent on every call (`before.py:34`) | Recorded only with content capture on, and there is no hash to group runs by prompt |
| 8 | Every tool call's input and output | missing | `web_search` (`before.py:26`) has no span | When a reply is wrong, you can't tell whether the search missed the rule or the model ignored it |
| 9 | RAG | n/a | no retrieval | |
| 10 | Empty results and failures | missing | `.get("results", [])` (`before.py:28`) | A search that failed inside a 200 looks the same as one that found nothing |
| 11 | The final answer as structured fields | missing | free text (`before.py:37`) | A judge has to grade the whole reply at once |
| 12 | Which version ran | missing | no `service.version` or prompt hash | You can't compare answers before and after a change |
| 13 | Human feedback | missing | no feedback recorded | Nothing to check an LLM judge against |
| 14 | Cut repetition, not evidence | missing | default batch settings, no size cap | A long prompt can push an export over the backend's size limit |
| 15 | Tracing never breaks the agent | missing | `SimpleSpanProcessor` (`before.py:14`) | Every span is exported on the agent's thread, so a slow backend slows every reply |
| 16 | Secrets and personal data removed | missing | no redaction | Emails and phone numbers in user messages go to the backend as typed |

### Fix first

1. **Items 1, 2 and 5**: open a root span per user message around `answer()`, with the message as input and the reply as output, so the model calls nest under it.
2. **Items 8 and 10**: wrap `web_search` in a span with the query and every result, an empty list when it found nothing, and error status when the body reports an error.
3. **Items 6 and 7**: record each model call with the full prompt as sent, the response, model, tokens and a prompt hash.
4. **Items 3 and 4**: put `conversation_id` in `session.id`, the customer on the root, and `service.name`, `service.version` and the environment on the resource.
5. **Items 15, 16 and 14**: switch to `BatchSpanProcessor` with an export timeout, redact in one helper, cap fields and size batches.
6. **Items 12 and 13**: record the commit and a dirty flag, and a feedback span linked to the answer.
7. **Item 11**: structuring the reply means changing the prompt, so it's left to you.
