import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, countWords, createRun, formatBytes, isCanonicalGithubUrl, LoopCounts, OutputFormat } from "./api";

interface IntakeViewProps {
  onRunCreated: (id: string) => void;
}

const DEFAULT_LOOPS: LoopCounts = { ideation: 4, architecture: 2, workpackage: 2 };
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;

const layers = [
  { no: "00", label: "Intake", text: "Normalizes your brief without inventing requirements." },
  { no: "01", label: "Ideation", text: "Diverges, researches, and judges the strongest direction." },
  { no: "02", label: "Architecture", text: "Designs the system and audits it against the PRD." },
  { no: "03", label: "Work package", text: "Orders build-ready stories and runs a final review." },
];

export function IntakeView({ onRunCreated }: IntakeViewProps) {
  const [brief, setBrief] = useState("");
  const [pastedText, setPastedText] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [format, setFormat] = useState<OutputFormat>("json");
  const [loops, setLoops] = useState<LoopCounts>(DEFAULT_LOOPS);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [defaultsNote, setDefaultsNote] = useState("Loading local defaults…");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let current = true;
    api.settings()
      .then((settings) => {
        if (!current) return;
        setFormat(settings.default_format);
        setLoops(settings.loops);
        setDefaultsNote(settings.search_provider === "mock" ? "Mock mode is ready—no API key required." : `Search: ${settings.search_provider}`);
      })
      .catch(() => {
        if (current) setDefaultsNote("Using built-in defaults. Start the local service to load saved settings.");
      });
    return () => { current = false; };
  }, []);

  const words = countWords(brief);
  const totalFileBytes = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);

  const validation = useMemo(() => {
    if (!brief.trim()) return "Write a brief to begin.";
    if (words > 2000) return `Brief is ${words - 2000} words over the limit.`;
    if (pastedText.length > 100_000) return "Pasted context exceeds 100,000 characters.";
    if (!isCanonicalGithubUrl(githubUrl)) return "Use a canonical public URL: https://github.com/owner/repo";
    if (files.length > 5) return "Select at most 5 files.";
    if (files.some((file) => file.size > MAX_FILE_BYTES)) return "Each attachment must be 2 MB or smaller.";
    if (totalFileBytes > MAX_TOTAL_BYTES) return "Attachments exceed the 8 MB combined limit.";
    return null;
  }, [brief, files, githubUrl, pastedText.length, totalFileBytes, words]);

  const updateFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const additions = Array.from(event.target.files ?? []);
    setFiles((current) => [...current, ...additions].slice(0, 6));
    event.target.value = "";
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (validation) {
      setError(validation);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await createRun({ brief: brief.trim(), pastedText, githubUrl: githubUrl.trim(), outputFormat: format, loopCounts: loops, files });
      onRunCreated(result.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The run could not be started.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="view intake-view page-enter">
      <section className="intake-intro" aria-labelledby="intake-title">
        <p className="eyebrow"><span>01</span> Feed the foundry</p>
        <h1 id="intake-title">From rough thought<br />to buildable truth.</h1>
        <p className="lede">Describe the product you want to make. Nine specialized roles will challenge, research, structure, and package it—while you keep every artifact on your machine.</p>

        <ol className="orientation-layers" aria-label="Four planning layers">
          {layers.map((layer) => (
            <li key={layer.no}>
              <span className="orientation-number">{layer.no}</span>
              <div><strong>{layer.label}</strong><p>{layer.text}</p></div>
            </li>
          ))}
        </ol>

        <aside className="local-note">
          <span className="shield-mark" aria-hidden="true">⌂</span>
          <div><strong>Your workshop, your machine.</strong><p>Briefs, files, outputs, and saved credentials stay in the local data directory.</p></div>
        </aside>
      </section>

      <form className="intake-sheet" onSubmit={submit} noValidate>
        <div className="sheet-heading">
          <span className="folio">INTAKE / A</span>
          <div><h2>Project brief</h2><p>Give the dialogue a precise place to start.</p></div>
          <span className={`word-meter ${words > 2000 ? "over" : ""}`} aria-live="polite">{words.toLocaleString()} / 2,000 words</span>
        </div>

        <label className="field-block brief-field">
          <span className="field-label">What are you trying to build? <em>Required</em></span>
          <textarea
            value={brief}
            onChange={(event) => { setBrief(event.target.value); setError(null); }}
            rows={10}
            dir="auto"
            maxLength={30_000}
            aria-describedby="brief-help"
            aria-invalid={words > 2000}
            placeholder="Start with the problem, who feels it, and the constraints that matter…"
            autoFocus
          />
          <span id="brief-help" className="field-help">Persian and right-to-left briefs are preserved throughout the pipeline.</span>
        </label>

        <details className="context-disclosure">
          <summary><span>Supporting context</span><small>Optional · pasted text, files, or a public repository</small></summary>
          <div className="context-body">
            <label className="field-block">
              <span className="field-label">Long pasted text <em>Optional</em></span>
              <textarea
                className="compact-textarea"
                value={pastedText}
                onChange={(event) => setPastedText(event.target.value)}
                rows={5}
                dir="auto"
                maxLength={100_001}
                placeholder="Research notes, an earlier specification, customer feedback…"
              />
              <span className="field-help">{pastedText.length.toLocaleString()} / 100,000 characters</span>
            </label>

            <div className="field-block">
              <span className="field-label">Reference files <em>Optional</em></span>
              <button className="file-drop" type="button" onClick={() => fileInput.current?.click()}>
                <span className="plus-mark" aria-hidden="true">+</span>
                <span><strong>Select files</strong><small>PDF, text, Markdown, code, JSON, YAML, CSV · 5 max · 2 MB each</small></span>
              </button>
              <input ref={fileInput} className="visually-hidden" type="file" multiple onChange={updateFiles} accept=".pdf,.txt,.md,.rst,.json,.yaml,.yml,.toml,.py,.js,.jsx,.ts,.tsx,.css,.html,.sql,.csv,text/*" />
              {files.length > 0 ? (
                <ul className="selected-files" aria-label="Selected files">
                  {files.map((file, index) => (
                    <li key={`${file.name}-${file.lastModified}-${index}`}>
                      <span className="file-glyph" aria-hidden="true" />
                      <span><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></span>
                      <button type="button" onClick={() => setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))} aria-label={`Remove ${file.name}`}>×</button>
                    </li>
                  ))}
                </ul>
              ) : null}
              <span className="field-help">{files.length}/5 files · {formatBytes(totalFileBytes)} / 8 MB</span>
            </div>

            <label className="field-block">
              <span className="field-label">Public GitHub repository <em>Optional</em></span>
              <div className="input-with-prefix"><span aria-hidden="true">↗</span><input type="url" value={githubUrl} onChange={(event) => setGithubUrl(event.target.value)} placeholder="https://github.com/owner/repo" aria-invalid={!isCanonicalGithubUrl(githubUrl)} /></div>
              <span className="field-help">Canonical public repository URLs only. Branch and issue URLs are not accepted.</span>
            </label>
          </div>
        </details>

        <fieldset className="format-fieldset">
          <legend>Output format</legend>
          <div className="segmented-control">
            {(["json", "md", "both"] as OutputFormat[]).map((value) => (
              <label key={value} className={format === value ? "selected" : ""}>
                <input type="radio" name="format" value={value} checked={format === value} onChange={() => setFormat(value)} />
                <strong>{value === "md" ? "Markdown" : value[0].toUpperCase() + value.slice(1)}</strong>
                <small>{value === "json" ? "For agents" : value === "md" ? "For humans" : "Two copies"}</small>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="loop-fieldset">
          <legend>Dialogue passes</legend>
          <p>More passes deepen critique and increase model usage.</p>
          {(Object.keys(loops) as Array<keyof LoopCounts>).map((key) => (
            <label className="range-row" key={key}>
              <span><strong>{key === "workpackage" ? "Work package" : key[0].toUpperCase() + key.slice(1)}</strong><small>{key === "ideation" ? "idea · research · judge" : key === "architecture" ? "architect · matcher" : "writer · reviewer"}</small></span>
              <input type="range" min="1" max="10" value={loops[key]} onChange={(event) => setLoops((current) => ({ ...current, [key]: Number(event.target.value) }))} />
              <output>{loops[key]}</output>
            </label>
          ))}
        </fieldset>

        <div className="form-end">
          <div className="form-status" role="status" aria-live="polite">
            <span className="status-stamp" aria-hidden="true">M</span>
            <span><strong>Zero-key quickstart</strong><small>{defaultsNote}</small></span>
          </div>
          <button className="primary-action" type="submit" disabled={submitting || Boolean(brief.trim() && validation)}>
            <span>{submitting ? "Preparing the workshop…" : "Start the dialogue"}</span>
            <i aria-hidden="true">→</i>
          </button>
        </div>
        {error ? <div className="inline-alert error" role="alert"><strong>Intake needs attention.</strong><span>{error}</span></div> : null}
      </form>
    </div>
  );
}
