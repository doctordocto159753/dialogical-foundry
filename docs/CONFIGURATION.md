# Configuration and providers

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `FOUNDRY_DATA_DIR` | `./data` | SQLite, master key, inputs, checkpoints, outputs |
| `FOUNDRY_HOST` | `127.0.0.1` | Uvicorn bind host |
| `FOUNDRY_PORT` | `8000` | Uvicorn port |
| `FOUNDRY_MASTER_KEY` | generated local file | Optional Fernet key override |
| `FOUNDRY_LLM_TIMEOUT_SECONDS` | `1800` | OpenAI/Anthropic read, write, and pool timeout per request attempt |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Optional OpenAI or OpenAI-compatible endpoint |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Optional Anthropic-compatible endpoint |

The app loads a root `.env` for native runs without overriding variables already
set by the process. Docker Compose interpolates the same variables into the
container. When a provider runs on the Windows host and Foundry runs in Docker,
use `host.docker.internal` instead of `127.0.0.1` in its base URL.

The 30-minute model timeout applies to each OpenAI or Anthropic request attempt.
Connection establishment remains capped at 30 seconds. Tavily and GitHub intake
retain their separate 20-second network limits.

Other application settings should normally be managed in the UI.

## Node fields

Every node independently resolves `provider`, `model`, `api_key_ref`, `temperature`, `top_k`, `top_p`, `max_tokens`, and `tools`. An override is stored in SQLite; the original pipeline JSON remains the prompt/configuration baseline.

Providers:

- `mock` — deterministic structured artifacts, supports `top_k`, no key.
- `mock_notopk` — deterministic no-`top_k` capability probe, no key.
- `anthropic` — Anthropic Messages API and returned usage metadata.
- `openai` — OpenAI Chat Completions JSON-object mode and returned usage metadata.

Configure model names supported by your provider account. Paid-provider availability and names can change independently of Foundry.

OpenAI-compatible gateways must support Chat Completions and JSON-object response
format. Anthropic gateways must implement the Messages API. Base URLs are global
per provider process; node-level model and key selection remains independent.

## Search

`mock` search supplies deterministic offline evidence. `tavily` performs bounded advanced searches and requires a separately referenced Tavily key. Research results are inserted into the Researcher context as untrusted references.

## Sampling fallback

The default Idea Generator uses `temperature=1.0`, `top_k=80`, and `top_p=0.98`. When the provider reports no `top_k` support, the engine swaps to `system_prompt_fallback`, removes the unsupported parameter at the provider boundary, and records `prompt_variant=fallback` in call history.
