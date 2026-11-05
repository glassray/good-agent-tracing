# Audit report format

Report every checklist item, in checklist order, as a table, then list the fixes in order of impact.

```markdown
## Tracing audit: <agent name>

Read: <files read>, <trace inspected, if any>

| # | Item | Status | Evidence | What's wrong |
| --- | --- | --- | --- | --- |
| 1 | One task per trace | ok | `worker/run.py:42` starts a span per ticket | |
| 2 | Steps under one root span | missing | no root span; `openai` auto-instrumentation only | Each model call is its own trace |
| 8 | Tool call inputs and outputs | partial | `tools/search.py:18` records the query | Results not recorded |
| … | | | | |

### Fix first
1. **Item 2**: open a root span per ticket in `worker/run.py` so model calls nest under it.
2. **Item 8**: record search results as `output.value` in `tools/search.py`.
3. …
```

Rules:

- **Status** is `ok`, `partial` or `missing`. Use `n/a` only when the item can't apply (item 9 for an agent with no retrieval).
- **Evidence** is a file and line, or a span name from a real trace. Never mark an item `ok` without evidence.
- **What's wrong** is one plain sentence about the effect ("you can't tell a missed rule from an ignored one"), not the implementation.
- **Fix first** is ordered by how much each fix helps a reader grade an answer. Items 2, 5, 8 and 9 usually come first; 12 to 16 after.
