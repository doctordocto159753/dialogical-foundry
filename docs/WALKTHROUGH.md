# Product walkthrough

This walkthrough proves the complete local v1 path without a paid key.

## 1. Start the app

Build and launch from the repository root:

```powershell
uv sync --extra dev
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
uv run foundry
```

Open <http://127.0.0.1:8000>. The header should report that Foundry is local and ready.

## 2. Confirm mock configuration

Open **Settings**.

1. Under Search & defaults, leave Search provider set to `mock`.
2. Confirm loop defaults are 4 for Ideation, 2 for Architecture, and 2 for Work package.
3. Expand a few node rows. Their provider should be `mock`; no key is required.
4. Do not add a real key for this walkthrough.

The key manager is used only when configuring Anthropic, OpenAI, or Tavily. A saved key appears only as metadata and a fingerprint; its secret value is never displayed again.

## 3. Submit an intake

Open **Intake** and enter:

> A local-first studio for independent game designers. It should turn a loose game concept into a small, testable vertical-slice plan while preserving the unusual creative hook.

Optionally:

- paste notes into the long-text field;
- attach a small `.md`, `.txt`, `.json`, or PDF artifact;
- add a canonical public GitHub repository URL;
- choose `Both` to create JSON and Markdown.

Watch the word counter remain below 2,000. Keep the default loop counts or lower them for a faster smoke run. Choose **Start the dialogue**.

## 4. Observe the run

The app moves to Run and opens an SSE connection.

- The foundry line advances through Intake, Ideation, Architecture, and Work Package.
- Node events show the active role, loop pass, retries, and completion.
- Input, output, and total tokens update after every node call.
- A layer card becomes available when that layer is checkpointed and written.

Reload the page while the run is active. The run metadata and persisted event history are loaded again. If the service was stopped mid-run, restart it, open the interrupted run, and choose **Resume**. The engine starts at the persisted next-node cursor.

## 5. Inspect and download artifacts

Open each completed layer card:

1. **Intake** — normalized goal, constraints, artifacts, assumptions, and questions.
2. **Ideation / PRD** — the judge's finalized product definition after the dialogue loop.
3. **Architecture** — components, data model, interfaces, decisions, and conformance work.
4. **Work Package** — the primary deliverable: ordered `T-###` stories with acceptance criteria, priority, dependencies, and `dev`, `design-frontend`, or `devops` stack tags.

Use JSON for a coding agent and Markdown for human review. Both are generated from the same validated canonical object.

## 6. Optional real-provider run

In Settings:

1. Add an Anthropic, OpenAI, or Gemini key.
2. Assign it to one or more nodes, enter the exact supported model ID, and optionally set a per-node Base URL.
3. Add a Tavily key and choose Tavily for evidence-backed research.
4. Save and start a new intake.

Anthropic and Gemini keep Idea Generator `top_k`. OpenAI automatically selects the creativity fallback prompt because it has no `top_k` parameter.

For provider-native research, expand **Researcher**, choose a real provider, switch **Execution mode** to **Provider Deep Research**, and enter both the exact research model/agent ID and exact standard normalization model ID. Keep the default 1,800-second research timeout unless the provider/account needs a different limit. OpenAI/Gemini background jobs survive local interruption through Resume. Remember that every ideation pass starts a research job; use one pass for an inexpensive first live proof.

Real calls may incur provider charges. Foundry surfaces returned usage counts but does not calculate monetary cost.

## Acceptance checklist

- [ ] Intake accepts brief, paste, files, GitHub URL, format, and loop counts.
- [ ] Progress and token totals update live.
- [ ] Four layer outputs are previewable and downloadable.
- [ ] Final work package contains ordered, coded, prioritized, tagged stories.
- [ ] Settings persist per-node provider/model/key/Base URL/sampling/tools and Researcher mode.
- [ ] Saved secrets cannot be read back from the UI or API.
- [ ] A stopped run can be resumed from its checkpoint.
- [ ] A terminal run can be deleted from its detail page or the Run archive after confirmation; active runs are protected.
- [ ] The same flow works from the Docker image.
