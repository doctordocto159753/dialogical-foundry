# API reference

Interactive OpenAPI documentation is available at `/api/docs` while the app is running.

## Runs

- `POST /api/runs` — multipart intake. Fields: `brief`, `pasted_text`, `github_url`, `output_format`, `loop_counts` JSON, repeated `files`. Returns `202` and a run id.
- `GET /api/runs` — recent runs with output manifests.
- `GET /api/runs/{id}` — persisted status, tokens, completed layers, error, and outputs.
- `POST /api/runs/{id}/resume` — resume a non-completed run with a checkpoint.
- `DELETE /api/runs/{id}` — permanently delete an inactive run, its events, inputs, checkpoints, and outputs. Returns `409` while the in-process run is active.
- `GET /api/runs/{id}/events` — SSE. Use `Last-Event-ID` or `?after=<seq>` to replay later events.
- `GET /api/runs/{id}/outputs` — ready output manifest.
- `GET /api/runs/{id}/outputs/{layer}?format=json|md` — safe, allowlisted download.

Event envelope:

```json
{
  "seq": 12,
  "run_id": "...",
  "type": "node.completed",
  "at": "2026-08-06T12:00:00+00:00",
  "payload": {
    "node": "judge",
    "iteration": 1,
    "tokens": {"input": 1200, "output": 430, "total": 1630}
  }
}
```

Event types are `run.started`, `run.interrupted`, `layer.started`, `node.started`, `node.research.started`, `node.research.poll`, `node.research.completed`, `node.retry`, `node.completed`, `tokens.updated`, `layer.completed`, `run.failed`, and `run.completed`.

## Configuration

- `GET/PUT /api/settings` — format/loop defaults and search provider/key reference.
- `GET /api/settings/nodes` — merged pipeline defaults and stored node overrides.
- `PUT /api/settings/nodes/{node_id}` — provider, exact model ID, `api_key_ref`, per-node Base URL, sampling, max tokens, tools, execution mode, and Deep Research controls. `deep_research` is accepted only for `researcher` with Anthropic, OpenAI, or Gemini and a non-empty normalization model ID.

## Keys

- `GET /api/keys` — metadata only.
- `POST /api/keys` — `{provider,label,value}`; secret is write-only.
- `PUT /api/keys/{id}` — replace metadata and secret.
- `DELETE /api/keys/{id}` — delete a key.

No endpoint returns an encrypted blob, plaintext value, or master key.

## Health

`GET /api/health` returns service status, version, and active data directory.
