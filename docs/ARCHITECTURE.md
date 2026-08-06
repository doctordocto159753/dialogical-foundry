# Architecture

## Shape

```text
React SPA -- REST/SSE --> FastAPI service --> RunManager threads
                              |                   |
                              v                   v
                           SQLite          PipelineExecutor
                              |              |    |    |
                              v              v    v    v
                     runs/config/events   LLM  search files
```

FastAPI serves the built SPA and API as one local unit. The synchronous, domain-neutral executor stays independent of HTTP and runs in a bounded thread pool. This avoids rewriting the provider SDK path while leaving the API event loop free for SSE clients.

## Engine invariants

- Pipelines remain data: `Pipeline → Layer → Step → Node/Loop`.
- Every node declares its blackboard inputs. String inputs select the latest value; object inputs can select the complete append-only history.
- Provider output is parsed as JSON and validated against the node contract before it becomes authoritative.
- A node result, token update, next cursor, and layer completion become durable together through an atomic state-file replacement.
- Secrets are resolved from references immediately before provider calls and are never serialized.
- Sessions live through a node's home layer and are cleared after the layer output is written.

## Run state

`state.json` is versioned and contains the pipeline name, output format, status, next action index, token totals, latest blackboard, full artifact history, full open sessions, call history, completed layers, timestamps, and errors. The temporary state file is flushed and atomically replaced.

On a node failure, in-memory changes from the uncommitted node are rolled back before the failed state is recorded. Resume therefore replays only the incomplete node, never an already checkpointed one.

## Persistence

SQLite holds run metadata, monotonic events, app defaults, per-node overrides, and encrypted keys. Large/portable artifacts stay in the per-run filesystem. SQLite uses WAL mode and a process-level write lock for predictable access from the API and worker threads.

## Event model

Executor callbacks create typed persisted events. `run_events.seq` is monotonic per run. SSE immediately replays events after `Last-Event-ID`, then polls for new rows. This makes reconnect behavior correct even when an in-memory subscriber was absent.

## Server evolution

For multi-user deployment, add authentication and a `user_id`/tenant scope to the same tables, APIs, data paths, and key resolver; replace the thread-pool run manager with a durable job system; and migrate SQLite to PostgreSQL. The graph engine and pipeline definitions do not need a domain rewrite.
