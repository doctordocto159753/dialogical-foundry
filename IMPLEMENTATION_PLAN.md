# Dialogical Foundry v1 — Implementation Plan

## Objective and boundary

Turn the existing data-driven CLI engine into the local-first Dialogical Foundry v1 specified in `SPEC.md`: a FastAPI-served React SPA that accepts a rough brief and references, runs the locked L0-L3 dialogue pipeline, streams progress and token usage, and produces downloadable, development-ready planning artifacts.

The v1 pipeline ends at the work package. It does not implement, integrate, or test the product described by that package.

## Baseline findings

- `engine/`, `pipelines/foundry_v1.json`, and the node prompts already prove pipeline walking, feedback edges, token accounting, session cleanup, per-layer files, and creativity-prompt selection with mock providers.
- The current checkout is not a Git repository. The target GitHub repository exists, is public and empty, and the authenticated account has admin access.
- The current checkpoint cannot resume: it lacks an execution cursor and full session state.
- Provider responses are stored as strings; JSON contracts are not validated, and `both` does not create semantic JSON and Markdown from one canonical artifact.
- Anthropic is an environment-only stub; OpenAI, per-node key references, search tools, SQLite, FastAPI, the SPA, Docker, and comprehensive tests do not yet exist.

## Recommended architecture

Preserve the `Pipeline -> Layer -> Step -> Node/Loop` data model and extend the engine through small contracts and services rather than coupling it to FastAPI.

### Engine

- Extend `engine/models.py` with `api_key_ref`, output-schema references, validated loop overrides, and backward-compatible input selectors (`latest` by default, `all` where finalizers need iteration history).
- Add `engine/contracts.py` for typed completion requests/results, usage, tool calls, and validation errors.
- Split provider implementations into `engine/providers/{mock,anthropic,openai}.py`, retaining compatibility exports from `engine/provider.py`. Resolve key references only at call time. Mark OpenAI as `supports_top_k = false` so the existing creativity fallback remains effective.
- Add `engine/tools/` with a bounded `SearchProvider` contract, deterministic mock search, and Tavily as the first real search adapter.
- Add `engine/state.py` with a versioned `RunState`: run status, pipeline/config snapshots, normalized intake, exact next-node cursor, complete node sessions, append-only iteration artifacts, latest-value index, retry history, token totals, completed layers, output manifest, and error details.
- Update `engine/executor.py` to emit typed lifecycle events, validate node JSON against schemas, retry malformed responses with concise validation feedback, execute bounded tools, checkpoint atomically after each validated node, and resume idempotently from the next cursor.
- Make structured data canonical. `engine/io_formats.py` writes real JSON objects and deterministically renders Markdown from the same object, keeping `json`, `md`, and `both` consistent.
- Add JSON Schemas for all nine nodes under `pipelines/schemas/`; keep `pipelines/foundry_v1.json` as pipeline/prompt SSOT and add a generated-file drift check for `PROMPTS.md`.

### Local service and persistence

- Create `server/main.py` and `server/api/` for FastAPI, health, run lifecycle, SSE, output downloads, settings, node configuration, and write-only key management.
- Use a background run manager so the existing graph engine remains independent from the web framework. Persist events with monotonic sequence numbers for `Last-Event-ID` replay; use in-memory subscribers only for low-latency delivery.
- Use SQLite with explicit migrations for `runs`, `run_events`, `node_configs`, `keystore`, and `app_settings`; use the filesystem for uploaded/reference inputs, `state.json`, and per-layer outputs.
- Encrypt secrets at rest with a local master key stored outside SQLite. API responses expose only key id, label, provider, and fingerprint; secrets never enter pipeline files, events, state, output, or logs.
- On process startup, mark orphaned `running` jobs as `interrupted`; expose explicit resume from the persisted state.

### API contracts

- `POST /api/runs`: multipart brief, pasted text, uploads, optional public GitHub URL, format, and 4/2/2 loop overrides; return `202` with a run id.
- `GET /api/runs/{id}` and `POST /api/runs/{id}/resume`: status and recovery.
- `GET /api/runs/{id}/events`: typed SSE events with replay.
- `GET /api/runs/{id}/outputs` and `/outputs/{layer}?format=json|md`: manifest, preview, and safe download.
- `GET/PUT /api/settings`, `GET/PUT /api/settings/nodes/{node_id}`: defaults and per-node model/tool configuration.
- `GET/POST/PUT/DELETE /api/keys`: metadata reads and write-only secret mutations.
- `GET /api/health`: local and container health.

### Frontend

Create `frontend/` with Vite, React, and TypeScript:

- `IntakeView`: 2,000-word live counter, long pasted text, bounded uploads, canonical public GitHub URL, output format, loop overrides, and Start.
- `RunView`: node/layer timeline, live token box, reconnecting SSE, errors/retries, resume action, and per-layer preview/download cards.
- `SettingsView`: per-node provider/model/key/sampling/tool controls, search-provider configuration, loop/format defaults, and masked key management.
- Render generated previews as text/structured data, never trusted HTML.

### Intake and security limits

- Enforce brief, file-count, per-file, aggregate-size, repository-file, and extracted-text limits in both UI and backend.
- Store uploads using generated ids and support a documented text/PDF allowlist; reject archives, executables, unsafe names, and unreadable binary input.
- Accept only canonical public `https://github.com/<owner>/<repo>` URLs; construct outbound GitHub endpoints internally, allowlist hosts, apply timeouts/size limits, ignore dependencies/build outputs/likely secrets, and report truncation.
- Treat every attachment and repository file as untrusted prompt context and delimit it explicitly.
- Bind to `127.0.0.1` by default, avoid permissive CORS, validate ids, prevent path traversal, redact secrets, add SPA security headers, and run the container as non-root.

## Implementation sequence

1. Add repository hygiene and packaging: `.gitignore`, `.env.example`, `pyproject.toml`, dependency lock, app settings/paths, and a preserved async-capable CLI using `foundry_v1.json`.
2. Add typed contracts and nine output schemas; implement validation/retry and canonical JSON-to-Markdown rendering with unit tests.
3. Implement append-only iteration artifacts and exact atomic checkpoint/resume. Prove crash recovery before building the API.
4. Implement mock, Anthropic, and OpenAI adapters; key-reference resolution; capability filtering; and provider contract tests.
5. Implement mock/Tavily search, bounded tool execution, citation traces, and error/rate-limit behavior.
6. Add SQLite migrations, repositories, encrypted keystore, settings overlays, and run/event metadata.
7. Add the run manager, REST/SSE endpoints, bounded intake/GitHub ingestion, downloads, restart recovery, and FastAPI static SPA serving.
8. Build the three-view React SPA and production frontend build.
9. Add Dockerfile, `compose.yaml`, persistent data volume, healthcheck, non-root runtime, and the single production command.
10. Complete documentation, run the final verification matrix from the final tree, scan staged content for secrets/runtime data, commit, and publish.

## Verification matrix

- Unit: pipeline/config validation, schema retry/failure, deterministic format parity, output safety, encrypted key storage, input limits, GitHub URL validation, tool dispatch, and creativity fallback.
- Engine integration: complete mock 4/2/2 execution; exact order; token sums; retained iterations; layer session closure; all four structured outputs in `json`, `md`, and `both`.
- Resume: inject a crash after a node checkpoint, reconstruct the executor, resume, and assert that completed provider call ids are never repeated.
- Provider/search contracts: mocked Anthropic/OpenAI/Tavily responses, usage aggregation, parameter filtering, tools, timeouts, retries, and errors. Paid-key smoke tests remain opt-in.
- API: multipart run creation, validation, status, SSE ordering/replay, restart/resume, masked key CRUD, settings overlays, safe output downloads, and static SPA fallback.
- Frontend: word counter, intake controls, Settings validation, token updates, reconnect, preview/download, error and resume states.
- Browser E2E: from mock configuration and intake through all four completed layers and final work-package download; reload/reconnect and interrupted-run resume.
- Packaging: frontend production build, Python lint/type/test, generated-file drift check, Docker build/start/health/mock-run/persistence smoke.

## Documentation deliverables

- Replace `README.md` with product boundary, architecture, prerequisites, mock-first quickstart, development/production commands, Docker path, provider/search setup, output/data locations, resume behavior, test commands, troubleshooting, and security notes.
- Add `docs/WALKTHROUGH.md` for the complete reproducible UI flow.
- Add `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/CONFIGURATION.md`, `docs/DATA_AND_SECURITY.md`, and `docs/DEVELOPMENT.md`.
- Clearly mark six-layer pipeline files as future/reference material so they cannot be mistaken for the v1 entrypoint.

## Safe Git publication

Because the remote has no branch yet, a Draft PR cannot be the first publication. After all validation passes:

1. Reconfirm that `git ls-remote --heads` is empty and initialize this workspace as `main` without rewriting any remote history.
2. Inspect ignored files and staged filenames/diff; exclude `.env`, databases, master keys, uploads, run data, caches, coverage, `node_modules`, and generated state.
3. Create one descriptive initial commit and rerun the release-relevant checks from the committed tree.
4. Push with `git push -u origin main` without force.
5. Verify the public repository contents and CI result. If a base branch appears before publication or direct push is rejected, publish the work on a feature branch and open a Draft PR instead.
