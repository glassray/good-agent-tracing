## Tracing audit: travel assistant (after)

Read: `examples/after.py`, `examples/tracing.py`, and the spans from one run with a stubbed model and search

| # | Item | Status | Evidence | What's wrong |
| --- | --- | --- | --- | --- |
| 1 | One task per trace | ok | `task_span("visa_question", …)` per user message (`after.py:57`) | |
| 2 | Every step under one root span | ok | both `chat` spans and `web_search` share the root's trace in the test run | |
| 3 | Ids that connect traces | ok | `session.id` = `conversation_id` (`after.py:57`); feedback links to the answer's root span | |
| 4 | Metadata to filter by | ok | resource in `tracing.py:29`; `app.customer_id` on the root | |
| 5 | Request and answer on the root | ok | input `after.py:57`, output `after.py:63` | |
| 6 | Each model call | ok | `chat()` (`after.py:39`): prompt as sent, response, model, tokens | |
| 7 | The instructions as text | ok | system prompt in each `chat` span's input, `app.prompt_hash` (`after.py:43`) | |
| 8 | Every tool call's input and output | ok | `web_search` span with query and every result (`after.py:21`) | |
| 9 | RAG | n/a | no retrieval | |
| 10 | Empty results and failures | ok | empty list kept (`after.py:33`); error status for exceptions and errors inside a 200 (`after.py:29`, `:35`) | |
| 11 | The final answer as structured fields | partial | root output is `{reply, sources}` (`after.py:63`) | No decision or claims; adding them means changing the prompt |
| 12 | Which version ran | ok | `service.version`, `app.git_dirty` (`tracing.py:31-33`), `app.prompt_hash` | |
| 13 | Human feedback | ok | `on_thumbs` → `record_feedback`, linked to the answer (`after.py:76`) | |
| 14 | Cut repetition, not evidence | partial | 1M-character cap with `.truncated`, batches of 32 | The system prompt is still recorded in full on every `chat` span |
| 15 | Tracing never breaks the agent | ok | `set_content` never raises; `BatchSpanProcessor` with a 30 s export timeout | |
| 16 | Secrets and personal data removed | ok | `redact` in `set_content`; the test run's email came out as `[email]` | |
