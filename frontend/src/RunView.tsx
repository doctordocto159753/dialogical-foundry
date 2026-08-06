import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, formatBytes, FoundryRun, OutputEntry, RUN_EVENT_TYPES, RunEventEnvelope, RunStatus, TokenUsage } from "./api";

interface RunViewProps {
  runId: string | null;
  onSelectRun: (id: string) => void;
  onNewRun: () => void;
}

const LAYERS = [
  { id: "L0_intake", no: "00", name: "Intake", result: "Normalized brief", nodes: "Intake normalizer" },
  { id: "L1_ideation", no: "01", name: "Ideation", result: "Reviewed PRD", nodes: "Idea generator · Researcher · Wise judge" },
  { id: "L2_architecture", no: "02", name: "Architecture", result: "Conformant system design", nodes: "Senior architect · Matcher" },
  { id: "L3_workpackage", no: "03", name: "Work package", result: "Agent-ready build order", nodes: "Task writer · Reviewer" },
] as const;

const EMPTY_TOKENS: TokenUsage = { input: 0, output: 0, total: 0 };

export function RunView({ runId, onSelectRun, onNewRun }: RunViewProps) {
  const [run, setRun] = useState<FoundryRun | null>(null);
  const [recent, setRecent] = useState<FoundryRun[]>([]);
  const [events, setEvents] = useState<RunEventEnvelope[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "live" | "reconnecting" | "closed">("closed");
  const [resuming, setResuming] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const refreshRun = useCallback(async (id: string) => {
    const next = await api.run(id);
    setRun(next);
    return next;
  }, []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    setEvents([]);
    setRun(null);
    sourceRef.current?.close();

    if (!runId) {
      api.runs()
        .then((items) => { if (current) setRecent(items); })
        .catch((caught) => { if (current) setError(caught instanceof Error ? caught.message : "Recent runs could not be loaded."); })
        .finally(() => { if (current) setLoading(false); });
      return () => { current = false; };
    }

    refreshRun(runId)
      .then((loaded) => {
        if (!current) return;
        setLoading(false);
        if (["completed", "failed", "interrupted"].includes(loaded.status)) setStreamState("closed");
        else setStreamState("connecting");

        const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
        sourceRef.current = source;
        source.onopen = () => { if (current) setStreamState("live"); };

        RUN_EVENT_TYPES.forEach((type) => {
          source.addEventListener(type, (message) => {
            if (!current) return;
            try {
              const envelope = JSON.parse((message as MessageEvent).data) as RunEventEnvelope;
              setEvents((prior) => prior.some((item) => item.seq === envelope.seq) ? prior : [...prior, envelope].sort((a, b) => a.seq - b.seq).slice(-80));
              if (envelope.payload.tokens) {
                setRun((prior) => prior ? { ...prior, tokens: envelope.payload.tokens! } : prior);
              }
              if (type === "run.started") setRun((prior) => prior ? { ...prior, status: "running", error: null } : prior);
              if (type === "layer.completed" && envelope.payload.layer_id) {
                setRun((prior) => prior ? { ...prior, completed_layers: Array.from(new Set([...prior.completed_layers, envelope.payload.layer_id!])) } : prior);
                void refreshRun(runId).catch(() => undefined);
              }
              if (type === "run.failed" || type === "run.completed") {
                source.close();
                setStreamState("closed");
                void refreshRun(runId).catch(() => undefined);
              }
            } catch {
              setError("A live event arrived in an unreadable format.");
            }
          });
        });

        source.onerror = () => {
          if (!current) return;
          void refreshRun(runId)
            .then((latest) => {
              if (["completed", "failed", "interrupted"].includes(latest.status)) {
                source.close();
                setStreamState("closed");
              } else {
                setStreamState("reconnecting");
              }
            })
            .catch(() => setStreamState("reconnecting"));
        };
      })
      .catch((caught) => {
        if (current) {
          setError(caught instanceof Error ? caught.message : "Run could not be loaded.");
          setLoading(false);
        }
      });

    return () => {
      current = false;
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [refreshRun, runId]);

  const resume = async () => {
    if (!run) return;
    setResuming(true);
    setError(null);
    try {
      await api.resumeRun(run.id);
      window.location.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "This run could not be resumed.");
      setResuming(false);
    }
  };

  if (loading) return <RunLoading />;
  if (!runId) return <RecentRuns runs={recent} error={error} onSelectRun={onSelectRun} onNewRun={onNewRun} />;
  if (!run) return <RunNotFound error={error} onNewRun={onNewRun} />;

  const lastNodeStart = [...events].reverse().find((event) => event.type === "node.started");
  const lastLayerStart = [...events].reverse().find((event) => event.type === "layer.started");
  const activeLayer = run.status === "running" || run.status === "pending" ? lastLayerStart?.payload.layer_id : undefined;
  const groupedOutputs = LAYERS.map((layer) => ({ layer, outputs: run.outputs.filter((output) => output.layer === layer.id) }));

  return (
    <div className="view run-view page-enter">
      <header className="run-heading">
        <div>
          <p className="eyebrow"><span>02</span> Live run</p>
          <h1>{run.status === "completed" ? "The work package is cast." : run.status === "failed" ? "The line needs attention." : run.status === "interrupted" ? "The workshop paused." : "Dialogue in motion."}</h1>
          <p className="run-id">RUN <code>{run.id}</code> · started {formatDate(run.created_at)}</p>
        </div>
        <div className="run-heading-actions">
          <span className={`run-status status-${run.status}`}><i aria-hidden="true" />{statusLabel(run.status)}</span>
          <button type="button" className="secondary-action" onClick={onNewRun}>＋ New run</button>
        </div>
      </header>

      {error ? <div className="inline-alert error" role="alert"><strong>Run update failed.</strong><span>{error}</span></div> : null}
      {run.error ? <div className="failure-banner" role="alert"><span>!</span><div><strong>Execution stopped</strong><p>{run.error}</p></div>{["failed", "interrupted"].includes(run.status) ? <button type="button" onClick={resume} disabled={resuming}>{resuming ? "Resuming…" : "Resume from checkpoint →"}</button> : null}</div> : null}
      {run.status === "interrupted" && !run.error ? <div className="failure-banner paused"><span>Ⅱ</span><div><strong>Run interrupted safely</strong><p>The local service stopped mid-run. Its latest checkpoint is intact.</p></div><button type="button" onClick={resume} disabled={resuming}>{resuming ? "Resuming…" : "Resume from checkpoint →"}</button></div> : null}

      <section className="run-console" aria-label="Run overview">
        <div className="foundry-panel">
          <div className="panel-heading">
            <div><span className="section-index">A</span><h2>Foundry line</h2></div>
            <StreamIndicator state={streamState} terminal={["completed", "failed", "interrupted"].includes(run.status)} />
          </div>
          <ol className="foundry-line">
            {LAYERS.map((layer, index) => {
              const completed = run.completed_layers.includes(layer.id);
              const active = activeLayer === layer.id && !completed;
              return (
                <li key={layer.id} className={`${completed ? "complete" : active ? "active" : "waiting"} ${layer.id === "L3_workpackage" ? "primary-layer" : ""}`}>
                  <div className="line-rail" aria-hidden="true"><span>{completed ? "✓" : layer.no}</span>{index < LAYERS.length - 1 ? <i /> : null}</div>
                  <div className="layer-copy">
                    <div className="layer-title"><h3>{layer.name}</h3><span>{completed ? "Stamped" : active ? "Working" : "Queued"}</span></div>
                    <p>{layer.result}</p>
                    <small>{layer.nodes}</small>
                    {active && lastNodeStart ? <div className="now-working"><span className="activity-bars" aria-hidden="true"><i /><i /><i /></span><strong>{humanize(lastNodeStart.payload.node_id ?? "Preparing")}</strong>{lastNodeStart.payload.iteration !== null && lastNodeStart.payload.iteration !== undefined ? <em>pass {lastNodeStart.payload.iteration + 1}</em> : null}</div> : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>

        <aside className="telemetry-panel">
          <div className="panel-heading"><div><span className="section-index">B</span><h2>Live ledger</h2></div></div>
          <div className="token-ledger" role="group" aria-label="Token usage">
            <Token label="Input" value={run.tokens?.input ?? EMPTY_TOKENS.input} />
            <Token label="Output" value={run.tokens?.output ?? EMPTY_TOKENS.output} />
            <Token label="Total" value={run.tokens?.total ?? EMPTY_TOKENS.total} total />
          </div>
          <div className="run-spec">
            <div><span>Format</span><strong>{run.format === "md" ? "Markdown" : run.format}</strong></div>
            <div><span>Dialogue passes</span><strong>{run.loops.ideation} · {run.loops.architecture} · {run.loops.workpackage}</strong></div>
            <div><span>Layers stamped</span><strong>{run.completed_layers.length} / 4</strong></div>
          </div>
          <ActivityLog events={events} />
        </aside>
      </section>

      <section className="outputs-section" aria-labelledby="outputs-title">
        <div className="outputs-heading"><div><span className="section-index">C</span><div><h2 id="outputs-title">Planning artifacts</h2><p>Plain-text previews. Downloaded files are the source of truth.</p></div></div><span>{run.outputs.length} file{run.outputs.length === 1 ? "" : "s"}</span></div>
        <div className="artifact-list">
          {groupedOutputs.map(({ layer, outputs }) => <ArtifactCard key={layer.id} layer={layer} outputs={outputs} complete={run.completed_layers.includes(layer.id)} />)}
        </div>
      </section>
    </div>
  );
}

function RunLoading() {
  return <div className="view run-view run-loading" aria-busy="true" aria-live="polite"><div className="loading-rule" /><p className="eyebrow"><span>02</span> Opening the ledger</p><h1>Recovering workshop state…</h1><div className="loading-lines"><i /><i /><i /><i /></div></div>;
}

function RunNotFound({ error, onNewRun }: { error: string | null; onNewRun: () => void }) {
  return <div className="view centered-state page-enter"><span className="empty-mark">×</span><p className="eyebrow">Run unavailable</p><h1>This ledger could not be opened.</h1><p>{error ?? "The run may no longer exist in the local data directory."}</p><button className="primary-action" type="button" onClick={onNewRun}><span>Start a new run</span><i>→</i></button></div>;
}

function RecentRuns({ runs, error, onSelectRun, onNewRun }: { runs: FoundryRun[]; error: string | null; onSelectRun: (id: string) => void; onNewRun: () => void }) {
  return (
    <div className="view recent-view page-enter">
      <header className="recent-heading"><div><p className="eyebrow"><span>02</span> Run archive</p><h1>Return to the workshop.</h1><p>Open a local run to inspect its live ledger and outputs.</p></div><button className="primary-action" type="button" onClick={onNewRun}><span>Start a new run</span><i>→</i></button></header>
      {error ? <div className="inline-alert error" role="alert"><strong>Archive unavailable.</strong><span>{error}</span></div> : null}
      {!error && runs.length === 0 ? <div className="empty-ledger"><span className="empty-mark">◇</span><h2>No pages in the ledger yet.</h2><p>Your first dialogue will appear here and remain available after a restart.</p><button className="text-action" type="button" onClick={onNewRun}>Write the first brief →</button></div> : null}
      {runs.length > 0 ? <div className="recent-table">{runs.map((item) => <button type="button" key={item.id} onClick={() => onSelectRun(item.id)}><span className={`run-status status-${item.status}`}><i />{statusLabel(item.status)}</span><span className="recent-brief" dir="auto"><strong>{item.brief}</strong><small>{item.completed_layers.length}/4 layers · {item.outputs.length} files</small></span><time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time><span className="row-arrow">→</span></button>)}</div> : null}
    </div>
  );
}

function Token({ label, value, total = false }: { label: string; value: number; total?: boolean }) {
  return <div className={total ? "total" : ""}><span>{label}</span><strong>{value.toLocaleString()}</strong></div>;
}

function StreamIndicator({ state, terminal }: { state: "connecting" | "live" | "reconnecting" | "closed"; terminal: boolean }) {
  const label = terminal ? "Ledger closed" : state === "live" ? "Live stream" : state === "reconnecting" ? "Reconnecting" : "Connecting";
  return <span className={`stream-indicator ${terminal ? "closed" : state}`} role="status"><i aria-hidden="true" />{label}</span>;
}

function ActivityLog({ events }: { events: RunEventEnvelope[] }) {
  const activity = events.filter((event) => ["node.started", "node.retry", "node.completed", "layer.completed", "run.completed", "run.failed"].includes(event.type)).slice(-10).reverse();
  return (
    <div className="activity-log" aria-live="polite">
      <div className="activity-heading"><h3>Activity</h3><span>{events.length ? `#${events[events.length - 1].seq}` : "waiting"}</span></div>
      {activity.length === 0 ? <p className="activity-empty"><i />Waiting for the first node…</p> : <ol tabIndex={0} aria-label="Recent run activity; scroll for earlier events">{activity.map((event) => <li key={event.seq} className={event.type.includes("retry") || event.type.includes("failed") ? "warning" : ""}><span>{eventIcon(event.type)}</span><div><strong>{eventMessage(event)}</strong><small>event {event.seq}</small></div></li>)}</ol>}
    </div>
  );
}

function ArtifactCard({ layer, outputs, complete }: { layer: (typeof LAYERS)[number]; outputs: OutputEntry[]; complete: boolean }) {
  const [selected, setSelected] = useState<"json" | "md">((outputs.find((item) => item.format === "md")?.format ?? outputs[0]?.format ?? "json") as "json" | "md");
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const selectedOutput = outputs.find((item) => item.format === selected) ?? outputs[0];

  useEffect(() => {
    if (!open || !selectedOutput) return;
    let current = true;
    setPreview(null);
    setPreviewError(null);
    api.outputText(selectedOutput.url)
      .then((text) => { if (current) setPreview(text); })
      .catch((caught) => { if (current) setPreviewError(caught instanceof Error ? caught.message : "Preview unavailable."); });
    return () => { current = false; };
  }, [open, selectedOutput]);

  const isPrimary = layer.id === "L3_workpackage" && complete;
  return (
    <article className={`artifact-card ${complete ? "ready" : "waiting"} ${isPrimary ? "primary-artifact" : ""}`}>
      <div className="artifact-index"><span>{complete ? "✓" : layer.no}</span></div>
      <div className="artifact-main">
        <div className="artifact-title"><div><p>{layer.name}</p><h3>{layer.result}</h3></div>{isPrimary ? <span className="primary-stamp">PRIMARY DELIVERABLE</span> : null}</div>
        {!outputs.length ? <p className="artifact-waiting">{complete ? "Manifest is refreshing…" : "Appears when this layer is stamped."}</p> : <div className="artifact-actions"><div className="format-tabs" role="tablist" aria-label={`${layer.name} format`}>{outputs.map((output) => <button key={output.format} role="tab" aria-selected={selectedOutput?.format === output.format} type="button" onClick={() => setSelected(output.format)}>{output.format === "md" ? "Markdown" : "JSON"}</button>)}</div><span>{selectedOutput ? formatBytes(selectedOutput.bytes) : null}</span><button className="preview-toggle" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>{open ? "Close preview" : "Preview"}</button>{selectedOutput ? <a className="download-action" href={selectedOutput.url} download>Download ↓</a> : null}</div>}
        {open && selectedOutput ? <div className="artifact-preview">{previewError ? <p role="alert">{previewError}</p> : preview === null ? <div className="preview-loading"><i /><i /><i /></div> : <pre dir="auto" tabIndex={0} aria-label={`${layer.result} ${selectedOutput.format === "md" ? "Markdown" : "JSON"} preview; scroll to read the full artifact`}>{preview}</pre>}</div> : null}
      </div>
    </article>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function statusLabel(status: RunStatus): string {
  return ({ pending: "Queued", running: "Running", completed: "Complete", failed: "Failed", interrupted: "Interrupted" })[status];
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventIcon(type: string): string {
  if (type === "node.retry" || type === "run.failed") return "!";
  if (type === "node.completed" || type === "layer.completed" || type === "run.completed") return "✓";
  return "·";
}

function eventMessage(event: RunEventEnvelope): string {
  const node = humanize(event.payload.node_id ?? event.payload.node ?? "node");
  if (event.type === "node.started") return `${node} started${event.payload.iteration !== null && event.payload.iteration !== undefined ? ` · pass ${event.payload.iteration + 1}` : ""}`;
  if (event.type === "node.completed") return `${node} finished${event.payload.ms ? ` · ${event.payload.ms} ms` : ""}`;
  if (event.type === "node.retry") return `${node} retry ${event.payload.attempt ?? ""}`.trim();
  if (event.type === "layer.completed") return `${humanize(event.payload.layer_id ?? "Layer")} stamped`;
  if (event.type === "run.completed") return "Run completed";
  if (event.type === "run.failed") return "Run failed";
  return humanize(event.type);
}
