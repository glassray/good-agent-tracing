# good-agent-tracing

An agent skill that teaches Claude Code (or any assistant that reads `SKILL.md` files) to trace AI agents properly: so a person or an LLM judge can follow what the agent did, see where it went wrong, and tell which version did it.

Most teams already pay for tracing and get little out of it. Their traces record that the agent ran, not what it saw or why it answered the way it did. This skill turns the fix into a checklist the assistant can apply to your codebase.

## What it does

Ask your assistant to:

- **Add tracing** to an agent: one trace per task, every model and tool call nested under it, full inputs and outputs, ids, metadata, versioning and feedback, with redaction and size limits.
- **Audit tracing** you already have: a table of 16 checks marked ok, partial or missing, with file and line evidence and what to fix first.
- **Fix** what the audit finds, one item at a time.

It uses OpenTelemetry and its semantic conventions, so it works with any backend that accepts OTLP: Glassray, Langfuse, LangSmith, Braintrust, Arize Phoenix, Jaeger and others.

## The checklist

1. One task per trace
2. Every step under one root span
3. Ids that connect traces (`session.id`, your own ids, span links)
4. Metadata to filter by
5. Request and answer on the root, detail on each step
6. Each model call: full prompt, response, model and tokens
7. The instructions as text
8. Every tool call's input and output
9. For RAG: every chunk in full, which were kept, and the final prompt
10. Empty results and failures recorded explicitly
11. The final answer as structured fields
12. Which version ran: commit, uncommitted changes, prompt hashes
13. Human feedback linked to the answer
14. Cut repetition, not evidence
15. Tracing never breaks the agent
16. Secrets and personal data removed before export

The reasoning and examples for each are in [references/rules.md](references/rules.md), and the long-form guide is [What to do to make your AI traces useful](https://www.glassray.ai/blog/make-ai-traces-useful).

## Install

Claude Code, for all your projects:

```bash
git clone https://github.com/glassray/good-agent-tracing.git ~/.claude/skills/good-agent-tracing
```

Or for one project, clone it into `.claude/skills/good-agent-tracing` in that repository. Other assistants that support the `SKILL.md` format can load the folder the same way.

Then ask, for example: "Audit the tracing in this agent", or "Add tracing to the support agent in `src/agent`".

## What's inside

| File | What it's for |
| --- | --- |
| [`SKILL.md`](SKILL.md) | The checklist and how to add, audit or fix tracing |
| [`references/rules.md`](references/rules.md) | Each rule with the reasoning and examples |
| [`references/python.md`](references/python.md) | OpenTelemetry setup and helpers for Python |
| [`references/typescript.md`](references/typescript.md) | OpenTelemetry setup and helpers for TypeScript |
| [`references/audit.md`](references/audit.md) | The audit report format |

## License

MIT. Made by [Glassray](https://www.glassray.ai).
