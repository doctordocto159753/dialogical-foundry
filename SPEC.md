# Dialogical Foundry — v1 Locked Specification (SSOT)

**Slogan (fa):** «یک ایده‌ی ساده بده؛ مدل‌ها با هم گفت‌وگو می‌کنند و یک محصولِ کامل و آماده‌ی توسعه تحویلت می‌دهند.»

**What it is:** A local-first, single-page app. The user gives a rough idea; a graph
of LLM nodes dialogue, critique, research, and refine it across layers, then emit a
**development-ready work package** (ordered, coded, tagged, prioritized user stories)
plus supporting artifacts, ready to hand to a coding agent (Claude Code / Codex / any dev agent).

**v1 boundary (locked):** the pipeline stops **before** any implementation. It produces
the plan and the work package; it does **not** write, integrate, or test code. Building
from the work package is delegated to an external coding agent.

Codename in code: `foundry`.

---

## 1. Build principles (locked)
1. MVP and simple.
2. Simple deployment.
3. Very simple, user-friendly config.
4. Single-page, local-first; architected so that shifting to a server-deployed,
   multi-user product is an additive change (auth + tenancy), not a rewrite.

---

## 2. Pipeline v1 (locked)

Layers run in order. Each layer's output is written separately and is downloadable.
Loop counts are defaults, overridable per run in the UI.

```
L0 Intake        : intake
L1 Ideation loop : (idea_generator -> researcher -> judge) x4  ->  judge_finalize (PRD)
L2 Architecture  : (architect <-> matcher) x2
L3 Work Package  : (task_writer <-> wp_reviewer) x2   ->  final deliverable
```

Dataflow is explicit: each node declares its inputs (read from a shared blackboard).
Feedback edges are real — e.g. `idea_generator` sees `judge`'s critique only from
loop pass 2 onward, because the judge's output does not exist on pass 1.

### Node contracts

**intake** — *Intake Normalizer.* Objective: turn the raw brief + artifacts into one
clean structured problem statement (goal, context, constraints, explicit asks, open
questions). Inputs: user brief, uploaded files, pasted text, optional public GitHub
repo (fetched read-only). Output: normalized problem statement. Model: low temperature.

**idea_generator** — *Idea Generator.* Objective: expand the problem into a bold,
expansive ideation document; explore the possibility space widely, surface non-obvious
directions and adjacent features. On pass ≥2, incorporate the judge's feedback.
Inputs: `intake`, `judge`. Entropy: high — `temperature=1.0, top_k=80, top_p=0.98`.
**Creativity fallback:** if the configured provider does not support `top_k` (e.g.
OpenAI), the node swaps to `system_prompt_fallback` (a prompt that loosens creative
constraints) and still applies whatever entropy params the provider does support.

**researcher** — *Researcher.* Objective: deep-research each claim/direction in the
ideation doc; attach evidence, precedents, prior art, and risks per point. Tool:
`web_search` (pluggable search provider with its own key). Inputs: `idea_generator`.
Optional: delta-research on later passes (research only new/changed claims).

**judge** — *Wise Judge.* Objective: critically review ideation doc + research; list
flaws, weak assumptions, contradictions, risks, and required fixes as actionable
feedback to the idea generator. Inputs: `idea_generator`, `researcher`.

**judge_finalize** — *Wise Judge (PRD).* After the loop, autonomously produce a
comprehensive professional PRD from the matured ideation doc + research + critiques.
Inputs: `idea_generator`, `researcher`, `judge`. This is L1's canonical output.

**architect** — *Senior Architect.* From the PRD, produce a macro technical
architecture document: components, data model, interfaces/contracts, tech choices +
rationale, cross-cutting concerns. On pass ≥2, incorporate matcher feedback.
Inputs: `judge_finalize`, `matcher`.

**matcher** — *Conformance Matcher.* Check the architecture against the PRD line by
line; report every gap, mismatch, unaddressed requirement as feedback.
Inputs: `architect`, `judge_finalize`.

**task_writer** — *Task Writer.* Turn the architecture into ordered, coded user
stories in execution order. Each task carries: id, title, standard user-story scope,
acceptance criteria, priority, and stack tag (`dev` | `design-frontend` | `devops`).
Emit a work package ready for a coding agent. On pass ≥2, incorporate reviewer feedback.
Inputs: `architect`, `wp_reviewer`. This is L3's canonical output — the final deliverable.

**wp_reviewer** — *Work-Package Reviewer.* Review the work package for scope
correctness, ordering, dependency sanity, coverage vs. architecture, and tag accuracy;
return feedback. Inputs: `task_writer`.

---

## 3. Cross-cutting requirements (locked)

**Token-usage box.** A visible box, updated live after every node call:
`input tokens so far` · `output tokens so far` · `total`. Sourced from each
provider's usage metadata, accumulated by the engine, persisted in `state.json`.
(Implemented and tested.)

**Per-node API key + config.** Every node is independently configurable:
`provider`, `model`, `api_key_ref`, `temperature`, `top_k`, `top_p`, `max_tokens`,
`tools`. Keys live in a **local keystore** (referenced by id, never inlined into
pipeline files) and never leave the machine except to the model/search provider they
belong to. Nodes may share a key or use different ones.

**Idea-generator entropy + fallback.** As above: parameter-level entropy by default;
prompt-level creativity fallback when the provider lacks `top_k`. Provider capability
(`supports_top_k`) drives the automatic switch. (Implemented and tested.)

**Per-node sessions.** Each node keeps its own message history, which persists across
loop passes within its home layer and is closed (cleared) when that layer completes.
(LLM APIs are stateless; a "session" is replayed history.) (Implemented and tested.)

**Output format.** Chosen at run start: `json` (default) · `md` · `both`. Every layer
is written in the chosen format; the final work package is the primary download.

**Intake inputs.** Brief ≤2000 words (live counter), file upload as artifact, long
pasted text, and a **public** GitHub repo URL fetched read-only as reference context.
(Private/own-repo GitHub integration is a later phase.)

**Reliability.** Structured-output validation + retry per node; checkpoint after every
node (resumable run); live progress stream. (Checkpointing implemented; validation/retry
to be added during build.)

---

## 4. Architecture (locked)

**Backend:** Python 3.12 + FastAPI + Uvicorn (async). Serves the built SPA as static
assets (one deployable unit). Hosts the orchestration engine (the existing
dependency-light `engine/` package, unchanged in shape). Endpoints (indicative):
`POST /runs` (start), `GET /runs/{id}/events` (SSE: node progress + live token box),
`GET /runs/{id}/outputs/{layer}` (download), config CRUD for nodes/keys/defaults.

**Frontend:** Vite + React, minimal, single page, three views (see §5). REST + SSE.

**Storage:** SQLite (runs metadata, config, keystore) + filesystem (per-run outputs +
`state.json`). Local-first and portable.

**Providers:** Anthropic first (supports `top_k`, matches the idea-generator default).
OpenAI addable (no `top_k` → exercises the creativity fallback). Search provider
(Tavily/Exa/Brave) pluggable, its own key. A provider is a small class implementing
`complete(...) -> (text, usage)` and a `supports_top_k` flag.

**Deployment:** local single command (Uvicorn serving the built SPA), plus a Dockerfile
/ `docker compose up`. All config through the Settings UI; `.env` optional.

**Shift-to-server path:** add auth + `user_id` scoping on runs/config, swap SQLite→
Postgres. Same engine, same endpoints, same pipeline definitions. No rearchitecting.

---

## 5. UI surfaces (locked, minimal)

1. **Intake.** Brief box (≤2000 words + counter), file upload, paste-long-text,
   public GitHub repo URL, output-format selector (json/md/both, default json),
   per-layer loop-count overrides (defaults 4/2/2), Start.
2. **Run.** Live node-by-node progress, the token-usage box, and one card per layer
   with its output preview + download as it completes.
3. **Settings.** Per-node config (provider/model/key/params/tools), default loop
   counts, search-provider key, output-format default. Keys stored locally.

---

## 6. Out of scope for v1 (architected for later)
- Implementation layers (dev / devops / frontend), integration, QA run/fix — a later
  *software-build* pipeline that delegates execution to an existing coding agent.
- Private / user-owned GitHub integration.
- Multi-user auth and server tenancy (path defined in §4).

---

## 7. Definition of Done (v1)
A run is acceptable when: the user submits a brief (+ optional artifacts), picks format
and loop counts, and starts; sees live progress and a live token box; can download each
layer's output; receives a final work package of ordered, coded, stack-tagged,
prioritized user stories ready for a coding agent; per-node provider/model/key/params
are configurable and the idea-generator fallback works on a no-`top_k` provider; a
crashed run resumes from its last checkpoint; the app runs locally with one command and
is deployable via Docker.

---

## 8. Engine reuse note
The `engine/` package (models, provider abstraction, executor, io_formats) is
domain-agnostic and scope-independent; it is retained as-is. Only the pipeline
definition was narrowed to v1 (`pipelines/foundry_v1.json`). The same engine will later
run the software-build pipeline without code changes.

*Status: engine + token box + creativity fallback + per-layer outputs + checkpointing
implemented and tested with a mock provider. Next: (a) precise node system prompts
[the intellectual core], (b) real provider + web-search wiring, (c) FastAPI backend +
SPA, delivered as piece-by-piece work packages for a coding agent.*
