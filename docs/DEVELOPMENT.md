# Development and testing

## Repository map

```text
engine/       domain-neutral pipeline runtime, providers, search, state and formats
server/       FastAPI, SQLite, keystore, ingestion and run management
frontend/     React/Vite SPA
pipelines/    v1 SSOT and archived six-layer reference
tests/        engine and API tests
scripts/      prompt generation and PowerShell helpers
```

## Setup

```powershell
uv sync --extra dev
Set-Location frontend
npm.cmd ci
```

Use `scripts/dev.ps1` or start the API and Vite server in separate terminals as described in the README.

## Backend tests

```console
uv run pytest
uv run ruff check engine server tests run.py
```

Offline workflow tests use mock model/search providers. Provider-contract tests use in-process fake SDKs and HTTP transports to assert exact model/agent IDs, endpoints, Base URLs, tools, polling, normalization, and token aggregation without making billed calls. API tests isolate data under pytest temporary directories. Exact-resume coverage injects both local-node and post-remote-creation crashes, reconstructs the executor, and confirms completed calls and remote job creation are not duplicated.

## Frontend tests and build

```powershell
Set-Location frontend
npm.cmd run test
npm.cmd run build
```

## Prompt SSOT

`pipelines/foundry_v1.json` is the runtime SSOT. `pipelines/build_v1.py` documents/builds that definition and `scripts/gen_prompts_md.py` renders `PROMPTS.md`. When prompt definitions change, regenerate both and inspect the semantic diff.

The `software_product.json` and `_full_6layer_reference.json` files are future/reference six-layer pipelines. They are not v1 entrypoints and must not be used to claim v1 completion.

## Release checklist

1. Run backend tests/lint, frontend tests/build, and CLI mock run.
2. Build and smoke the Docker image when the daemon is available.
3. Inspect `git status`, ignored files, staged names, `git diff --cached --check`, and the complete staged diff.
4. Confirm `.env`, data, databases, keys, uploads, checkpoints, output runs, caches, and `node_modules` are absent.
5. Commit only the validated tree and verify the GitHub checks from the pushed commit.
