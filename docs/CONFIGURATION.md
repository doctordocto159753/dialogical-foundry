# Configuration and providers

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `FOUNDRY_DATA_DIR` | `./data` | SQLite, master key, inputs, checkpoints, outputs |
| `FOUNDRY_HOST` | `127.0.0.1` | Uvicorn bind host |
| `FOUNDRY_PORT` | `8000` | Uvicorn port |
| `FOUNDRY_MASTER_KEY` | generated local file | Optional Fernet key override |

Application settings should normally be managed in the UI.

## Node fields

Every node independently resolves `provider`, `model`, `api_key_ref`, `temperature`, `top_k`, `top_p`, `max_tokens`, and `tools`. An override is stored in SQLite; the original pipeline JSON remains the prompt/configuration baseline.

Providers:

- `mock` — deterministic structured artifacts, supports `top_k`, no key.
- `mock_notopk` — deterministic no-`top_k` capability probe, no key.
- `anthropic` — Anthropic Messages API and returned usage metadata.
- `openai` — OpenAI Chat Completions JSON-object mode and returned usage metadata.

Configure model names supported by your provider account. Paid-provider availability and names can change independently of Foundry.

## Search

`mock` search supplies deterministic offline evidence. `tavily` performs bounded advanced searches and requires a separately referenced Tavily key. Research results are inserted into the Researcher context as untrusted references.

## Sampling fallback

The default Idea Generator uses `temperature=1.0`, `top_k=80`, and `top_p=0.98`. When the provider reports no `top_k` support, the engine swaps to `system_prompt_fallback`, removes the unsupported parameter at the provider boundary, and records `prompt_variant=fallback` in call history.
