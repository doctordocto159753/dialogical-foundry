import { FormEvent, useEffect, useState } from "react";
import { api, AppSettings, LoopCounts, NodeSettings, OutputFormat, Provider, SavedKey, SearchProvider } from "./api";

const FALLBACK_SETTINGS: AppSettings = {
  default_format: "json",
  loops: { ideation: 4, architecture: 2, workpackage: 2 },
  search_provider: "mock",
  search_key_ref: null,
};

export function SettingsView() {
  const [settings, setSettings] = useState<AppSettings>(FALLBACK_SETTINGS);
  const [nodes, setNodes] = useState<NodeSettings[]>([]);
  const [keys, setKeys] = useState<SavedKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingDefaults, setSavingDefaults] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [loadedSettings, loadedNodes, loadedKeys] = await Promise.all([api.settings(), api.nodes(), api.keys()]);
      setSettings(loadedSettings);
      setNodes(loadedNodes);
      setKeys(loadedKeys);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Local settings could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const saveDefaults = async (event: FormEvent) => {
    event.preventDefault();
    setSavingDefaults(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await api.saveSettings(settings);
      setSettings(saved);
      setNotice("Run defaults saved locally.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Defaults could not be saved.");
    } finally {
      setSavingDefaults(false);
    }
  };

  const deleteKey = async (key: SavedKey) => {
    if (!window.confirm(`Delete “${key.label}”? Node references to this key will stop working.`)) return;
    setError(null);
    setNotice(null);
    try {
      await api.deleteKey(key.id);
      setKeys((items) => items.filter((item) => item.id !== key.id));
      if (settings.search_key_ref === key.id) setSettings((current) => ({ ...current, search_key_ref: null }));
      setNotice(`Deleted key metadata for ${key.label}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Key could not be deleted.");
    }
  };

  if (loading) return <div className="view settings-view settings-loading" aria-busy="true"><p className="eyebrow"><span>03</span> Local configuration</p><h1>Opening the instrument cabinet…</h1><div className="loading-lines"><i /><i /><i /><i /></div></div>;

  return (
    <div className="view settings-view page-enter">
      <header className="settings-heading">
        <div><p className="eyebrow"><span>03</span> Local configuration</p><h1>Set the instruments.<br />Keep the keys.</h1></div>
        <p>Mock providers make the complete workflow testable without credentials. When you add a real provider, secrets are stored by the local service and never returned to this page.</p>
      </header>

      <div className="settings-security-strip"><span className="lock-mark" aria-hidden="true" /><strong>Write-only secrets</strong><p>Only provider, label, and a short fingerprint are visible after save.</p><span>LOCAL DATA DIRECTORY</span></div>

      {error ? <div className="inline-alert error" role="alert"><strong>Settings need attention.</strong><span>{error}</span><button type="button" onClick={() => void load()}>Retry</button></div> : null}
      {notice ? <div className="inline-alert success" role="status" aria-live="polite"><strong>Saved.</strong><span>{notice}</span></div> : null}

      <section className="settings-section" aria-labelledby="defaults-title">
        <div className="settings-section-title"><span className="section-index">A</span><div><h2 id="defaults-title">Run defaults</h2><p>Applied to new intake forms. Every value can still be changed before a run.</p></div></div>
        <form className="defaults-form" onSubmit={saveDefaults}>
          <label><span>Output format</span><select value={settings.default_format} onChange={(event) => setSettings((current) => ({ ...current, default_format: event.target.value as OutputFormat }))}><option value="json">JSON</option><option value="md">Markdown</option><option value="both">Both</option></select></label>
          <label><span>Search provider</span><select value={settings.search_provider} onChange={(event) => setSettings((current) => ({ ...current, search_provider: event.target.value as SearchProvider, search_key_ref: event.target.value === "mock" ? null : current.search_key_ref }))}><option value="mock">Mock · offline</option><option value="tavily">Tavily · live web</option></select></label>
          <label><span>Search key</span><select value={settings.search_key_ref ?? ""} disabled={settings.search_provider === "mock"} onChange={(event) => setSettings((current) => ({ ...current, search_key_ref: event.target.value || null }))}><option value="">{settings.search_provider === "mock" ? "Not needed in mock mode" : "Select a saved key"}</option>{keys.filter((key) => key.provider === "tavily").map((key) => <option key={key.id} value={key.id}>{key.label} · {key.fingerprint}</option>)}</select></label>
          <div className="defaults-loops"><span>Default passes</span>{(Object.keys(settings.loops) as Array<keyof LoopCounts>).map((key) => <label key={key}><span>{key === "workpackage" ? "Work pkg." : key}</span><input type="number" min="1" max="10" value={settings.loops[key]} onChange={(event) => setSettings((current) => ({ ...current, loops: { ...current.loops, [key]: Number(event.target.value) } }))} /></label>)}</div>
          <button className="save-action" type="submit" disabled={savingDefaults}>{savingDefaults ? "Saving…" : "Save defaults"}</button>
        </form>
      </section>

      <section className="settings-section key-section" aria-labelledby="keys-title">
        <div className="settings-section-title"><span className="section-index">B</span><div><h2 id="keys-title">Key cabinet</h2><p>Add a secret once; refer to it by label from node settings.</p></div></div>
        <KeyCreator onCreated={(key) => { setKeys((items) => [...items, key]); setNotice(`Stored ${key.label}; the secret is no longer visible.`); }} onError={setError} />
        {keys.length === 0 ? <div className="key-empty"><span>⌁</span><div><strong>No keys stored</strong><p>That is expected for the zero-key mock workflow.</p></div></div> : <ul className="key-list">{keys.map((key) => <li key={key.id}><span className="key-provider">{key.provider.slice(0, 2).toUpperCase()}</span><span><strong>{key.label}</strong><small>{key.provider} · fingerprint {key.fingerprint}</small></span><time dateTime={key.updated_at}>{new Date(key.updated_at).toLocaleDateString()}</time><button type="button" onClick={() => void deleteKey(key)} aria-label={`Delete ${key.label}`}>Delete</button></li>)}</ul>}
      </section>

      <section className="settings-section nodes-section" aria-labelledby="nodes-title">
        <div className="settings-section-title"><span className="section-index">C</span><div><h2 id="nodes-title">Node bench</h2><p>Nine roles, independently configurable. Expand only the instrument you need.</p></div><span className="node-count">{nodes.length.toString().padStart(2, "0")} NODES</span></div>
        <div className="provider-note"><span>i</span><p><strong>OpenAI does not support top-k.</strong> The executor omits that parameter and automatically selects the creative prompt fallback where needed.</p></div>
        <div className="node-list">
          {nodes.map((node, index) => <NodeRow key={node.id} node={node} index={index} keys={keys} onSaved={(saved) => { setNodes((items) => items.map((item) => item.id === node.id ? { ...item, ...saved, role: item.role } : item)); setNotice(`${node.role} configuration saved.`); }} onError={setError} />)}
        </div>
      </section>
    </div>
  );
}

function KeyCreator({ onCreated, onError }: { onCreated: (key: SavedKey) => void; onError: (message: string | null) => void }) {
  const [provider, setProvider] = useState("openai");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!label.trim() || !secret) { onError("A label and secret are required."); return; }
    setSaving(true);
    onError(null);
    try {
      const key = await api.createKey({ provider, label: label.trim(), value: secret });
      onCreated(key);
      setLabel("");
      setSecret("");
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Key could not be stored.");
    } finally {
      setSaving(false);
    }
  };

  return <form className="key-form" onSubmit={submit}><label><span>Provider</span><select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="tavily">Tavily</option></select></label><label><span>Label</span><input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="e.g. personal-openai" maxLength={80} /></label><label className="secret-field"><span>Secret value</span><input type="password" autoComplete="new-password" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="Written once, never displayed" /></label><button className="save-action" type="submit" disabled={saving}>{saving ? "Storing…" : "Store key"}</button></form>;
}

function NodeRow({ node, index, keys, onSaved, onError }: { node: NodeSettings; index: number; keys: SavedKey[]; onSaved: (node: NodeSettings) => void; onError: (message: string | null) => void }) {
  const [draft, setDraft] = useState(node);
  const [saving, setSaving] = useState(false);
  const isOpenAi = draft.provider === "openai";
  const matchingKeys = keys.filter((key) => key.provider === draft.provider);

  const patch = <K extends keyof NodeSettings>(key: K, value: NodeSettings[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    setSaving(true);
    onError(null);
    try {
      const saved = await api.saveNode(node.id, {
        provider: draft.provider,
        model: draft.model,
        api_key_ref: draft.api_key_ref || null,
        temperature: draft.temperature,
        top_k: isOpenAi ? null : draft.top_k,
        top_p: draft.top_p,
        max_tokens: draft.max_tokens,
        tools: draft.tools,
      });
      onSaved({ ...draft, ...saved, role: node.role });
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : `${node.role} could not be saved.`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <details className="node-row">
      <summary>
        <span className="node-number">{String(index + 1).padStart(2, "0")}</span>
        <span className="node-identity"><strong>{node.role}</strong><small>{node.id}</small></span>
        <span className={`provider-badge provider-${draft.provider}`}>{draft.provider}</span>
        <span className="node-model">{draft.model}</span>
        <span className="disclosure-mark" aria-hidden="true" />
      </summary>
      <div className="node-config">
        <label><span>Provider</span><select value={draft.provider} onChange={(event) => patch("provider", event.target.value as Provider)}><option value="mock">Mock</option><option value="mock_notopk">Mock · no top-k</option><option value="anthropic">Anthropic</option><option value="openai">OpenAI</option></select></label>
        <label><span>Model</span><input value={draft.model} onChange={(event) => patch("model", event.target.value)} /></label>
        <label><span>Key reference</span><select value={draft.api_key_ref ?? ""} disabled={draft.provider.startsWith("mock")} onChange={(event) => patch("api_key_ref", event.target.value || null)}><option value="">{draft.provider.startsWith("mock") ? "Not needed" : "Select saved key"}</option>{matchingKeys.map((key) => <option key={key.id} value={key.id}>{key.label} · {key.fingerprint}</option>)}</select></label>
        <label><span>Temperature</span><input type="number" step="0.1" min="0" max="2" value={draft.temperature ?? ""} onChange={(event) => patch("temperature", event.target.value === "" ? undefined : Number(event.target.value))} /></label>
        <label><span>Top-k</span><input type="number" min="1" disabled={isOpenAi} value={isOpenAi ? "" : draft.top_k ?? ""} placeholder={isOpenAi ? "Fallback" : "Unset"} onChange={(event) => patch("top_k", event.target.value === "" ? null : Number(event.target.value))} /></label>
        <label><span>Top-p</span><input type="number" step="0.01" min="0" max="1" value={draft.top_p ?? ""} placeholder="Unset" onChange={(event) => patch("top_p", event.target.value === "" ? null : Number(event.target.value))} /></label>
        <label><span>Max tokens</span><input type="number" min="1" value={draft.max_tokens ?? ""} placeholder="Provider default" onChange={(event) => patch("max_tokens", event.target.value === "" ? null : Number(event.target.value))} /></label>
        <label className="tools-field"><span>Tools <small>comma-separated</small></span><input value={draft.tools.join(", ")} onChange={(event) => patch("tools", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} placeholder="web_search" /></label>
        <div className="node-save"><p>{isOpenAi ? "Creative fallback will be automatic." : draft.provider.startsWith("mock") ? "Deterministic and key-free." : "Uses the selected local key reference."}</p><button type="button" className="save-action" onClick={() => void save()} disabled={saving}>{saving ? "Saving…" : "Save node"}</button></div>
      </div>
    </details>
  );
}
