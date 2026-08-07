# Configuration and providers

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `FOUNDRY_DATA_DIR` | `./data` | SQLite, master key, inputs, checkpoints, outputs |
| `FOUNDRY_HOST` | `127.0.0.1` | Uvicorn bind host |
| `FOUNDRY_PORT` | `8000` | Uvicorn port |
| `FOUNDRY_MASTER_KEY` | generated local file | Optional Fernet key override |
| `FOUNDRY_LLM_TIMEOUT_SECONDS` | `1800` | OpenAI/Anthropic/Gemini read, write, and pool timeout per request attempt |
| `FOUNDRY_OPENAI_COMPAT_USER_AGENT` | `curl/8.0` | User-Agent for non-official OpenAI-compatible gateways; useful when a gateway WAF blocks the SDK default |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Optional OpenAI or OpenAI-compatible endpoint |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Optional Anthropic-compatible endpoint |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Optional Gemini API or compatible endpoint root |

The app loads a root `.env` for native runs without overriding variables already
set by the process. Docker Compose interpolates the same variables into the
container. When a provider runs on the Windows host and Foundry runs in Docker,
use `host.docker.internal` instead of `127.0.0.1` in its base URL.

The 30-minute model timeout applies to each OpenAI, Anthropic, or Gemini request attempt.
Connection establishment remains capped at 30 seconds. Tavily and GitHub intake
retain their separate 20-second network limits.

Other application settings should normally be managed in the UI.

## Node fields

Every node independently resolves `provider`, `model`, `api_key_ref`, `base_url`, `openai_api`, `temperature`, `top_k`, `top_p`, `max_tokens`, and `tools`. An override is stored in SQLite; the original pipeline JSON remains the prompt/configuration baseline.

Base URL precedence is:

1. the non-empty Base URL saved on the node;
2. the provider environment variable;
3. the provider's official default.

The UI and API reject embedded credentials, query strings, and fragments in Base URLs. Local HTTP gateways remain valid. Store credentials in the key cabinet, not in a URL. OpenAI Base URLs should normally end at the API root, such as `https://api.openai.com/v1`. For recovery from a common configuration mistake, a trailing `/chat/completions` or `/responses` is removed before constructing the SDK client, so the SDK does not append the endpoint twice.

Providers:

- `mock` — deterministic structured artifacts, supports `top_k`, no key.
- `mock_notopk` — deterministic no-`top_k` capability probe, no key.
- `anthropic` — Anthropic Messages API and returned usage metadata.
- `openai` — selectable Chat Completions or streamed Responses API execution and returned usage metadata.
- `gemini` — Gemini `models.generateContent` with JSON-schema output and returned usage metadata.

Configure model names supported by your provider account. Foundry does not alias, upgrade, trim, prefix, or otherwise replace a saved model ID. OpenAI and Anthropic receive it as the request `model`; Gemini standard calls use it as the `{model}` path value; Gemini Deep Research receives it as the request `agent`. Leading/trailing whitespace is rejected rather than silently changed. Paid-provider availability and names can change independently of Foundry.

For an OpenAI node, `openai_api=chat_completions` sends a non-streaming `/chat/completions` JSON-object request. `openai_api=responses` sends a streaming `/responses` request, collects `response.output_text.delta` events, and reads usage from `response.completed`. Streaming is useful when a compatible gateway or reverse proxy requires response traffic during long model work. Official OpenAI receives JSON-object format configuration; compatible gateways receive a minimal Responses payload and rely on the explicit JSON-only prompt plus Foundry's schema validation. Deep Research always uses the provider-native Responses background-job path regardless of this standard-completion selector.

An OpenAI-compatible gateway must implement the selected route. Its Deep Research mode must additionally support Responses background creation and retrieval. For non-official gateways, Foundry disables hidden OpenAI SDK retries and leaves retry authority with the visible three-attempt node loop; it also sends `FOUNDRY_OPENAI_COMPAT_USER_AGENT`. Anthropic gateways must implement the Messages API and its server-side web-search tool for Deep Research. Gemini-compatible endpoints must implement GenerateContent and, for Deep Research, the Interactions API.

For official OpenAI Chat Completions, `gpt-5*`, `o1*`, `o3*`, and `o4*` model IDs use `max_completion_tokens` and omit `temperature`/`top_p`, matching the restricted reasoning-model parameter surface. Other official models and OpenAI-compatible gateways retain `max_tokens`, `temperature`, and `top_p`. Non-official gateways receive `FOUNDRY_OPENAI_COMPAT_USER_AGENT`; override it only when the gateway requires a different single-line User-Agent.

## Researcher execution modes

`standard` retains the existing flow: the configured model produces Researcher JSON, optionally using separately configured Tavily search results injected into its context.

`deep_research` is restricted to the Researcher node and requires Anthropic, OpenAI, or Gemini plus a `normalization_model`. The first call produces a provider-native long-form report; a second standard-model call converts that report into the unchanged Researcher JSON schema. Both the research ID/agent ID and normalization model ID are sent exactly as saved.

| Provider | Research request | Provider-specific controls |
| --- | --- | --- |
| OpenAI | `POST /responses`, `background=true`, `web_search_preview`; poll `GET /responses/{id}` | `research_max_tool_calls`, timeout, poll interval |
| Gemini | `POST /interactions` with the model field sent as `agent`, `background=true`, and `store=true`; poll `GET /interactions/{id}` | timeout, poll interval, thinking summaries, visualization |
| Anthropic | Messages API with `web_search_20250305` | `research_max_tool_calls` mapped to web-search `max_uses` |

The default `research_timeout_seconds` is 1,800 seconds. It is an overall polling deadline for OpenAI/Gemini and documents the intended long-call budget for Anthropic. `research_poll_interval_seconds` defaults to 5 seconds. OpenAI/Gemini remote IDs are atomically checkpointed immediately after creation; a resumed run retrieves that job rather than posting a duplicate. A completed raw report is also checkpointed before normalization, so JSON correction retries repeat only normalization.

Deep Research uses the provider's native web access and therefore does not invoke the separate Tavily adapter. It runs on every Researcher action. The default four-pass ideation loop consequently means four provider research jobs; reduce the Ideation pass count if that cost/latency is not intended.

Gemini Deep Research does not accept `system_instruction`. Foundry therefore preserves the complete Researcher instructions by prepending them to the interaction `input`, as required by Gemini's agent contract, rather than dropping them.

OpenAI GPT-4.1 is not the dedicated Deep Research model. OpenAI documents GPT-4.1 as an optional intermediate clarification/prompt-rewriting model; the actual research call uses a supported Deep Research model ID through Responses. It can still be selected as the normalization model if supported by the account and endpoint.

Provider references: [OpenAI Deep Research](https://developers.openai.com/api/docs/guides/deep-research), [OpenAI background mode](https://developers.openai.com/api/docs/guides/background), [Gemini Deep Research Agent](https://ai.google.dev/gemini-api/docs/deep-research), [Gemini GenerateContent](https://ai.google.dev/api/generate-content), and [Anthropic web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool).

## Search

`mock` search supplies deterministic offline evidence. `tavily` performs bounded advanced searches and requires a separately referenced Tavily key. Research results are inserted into the Researcher context as untrusted references.

## Sampling fallback

The default Idea Generator uses `temperature=1.0`, `top_k=80`, and `top_p=0.98`. When the provider reports no `top_k` support, the engine swaps to `system_prompt_fallback`, removes the unsupported parameter at the provider boundary, and records `prompt_variant=fallback` in call history.
